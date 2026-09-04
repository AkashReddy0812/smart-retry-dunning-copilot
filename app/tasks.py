import sys
import os
import random
import math
import joblib
from datetime import datetime, timedelta

# Ensure we can import from the 'ml' folder
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from ml.retry_policy import choose_best_retry
from app.celery_app import celery_app
from celery.utils.log import get_task_logger
from app.db import SessionLocal
from app.models import Transaction, RetryAttempt, DunningMessage

logger = get_task_logger(__name__)

# Load the ML model and features exactly as retry_policy does
MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "ml", "model.pkl")
FEATURES_PATH = os.path.join(os.path.dirname(__file__), "..", "ml", "feature_columns.pkl")

try:
    MODEL = joblib.load(MODEL_PATH)
    FEATURE_COLUMNS = joblib.load(FEATURES_PATH)
    logger.info("Successfully loaded ML model and feature columns.")
except Exception as e:
    logger.error(f"Could not load ML model from {MODEL_PATH}: {e}")
    MODEL, FEATURE_COLUMNS = None, None


@celery_app.task(name="app.tasks.process_failed_payment")
def process_failed_payment(transaction_id: str):
    """
    Evaluates a failed transaction and schedules the next optimal retry attempt.
    """
    logger.info(f"[{transaction_id}] Starting process_failed_payment pipeline.")
    db = SessionLocal()
    try:
        transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
        if not transaction:
            logger.error(f"[{transaction_id}] Transaction not found in DB.")
            return

        # Handle hard-declines / non-retryables
        if not transaction.is_retryable:
            logger.info(f"[{transaction_id}] Transaction is NOT retryable. Skipping.")
            transaction.current_status = "skipped_non_retryable"
            db.commit()
            generate_dunning_message.delay(transaction_id, transaction.failure_reason)
            return

        # Determine attempt number
        existing_attempts = db.query(RetryAttempt).filter(RetryAttempt.transaction_id == transaction_id).count()
        attempt_number = existing_attempts + 1

        # Check maximum retries
        if attempt_number > 3:
            logger.info(f"[{transaction_id}] Exhausted all 3 retries. Marking as lost.")
            transaction.current_status = "lost"
            db.commit()
            generate_dunning_message.delay(transaction_id, "retries_exhausted")
            return

        # Consult ML model for the best retry schedule
        chosen_timestamp, chosen_prob = choose_best_retry(
            model=MODEL,
            feature_columns=FEATURE_COLUMNS,
            failure_reason=transaction.failure_reason,
            payment_method=transaction.payment_method,
            issuing_bank=transaction.issuing_bank,
            transaction_type=transaction.transaction_type,
            amount_inr=transaction.amount_inr,
            original_failure_timestamp=transaction.original_timestamp,
            attempt_number=attempt_number
        )

        # The model can also return None if it dynamically determines the failure reason shouldn't be retried
        if chosen_timestamp is None:
            logger.info(f"[{transaction_id}] ML policy determined transaction is non-retryable. Skipping.")
            transaction.current_status = "skipped_non_retryable"
            db.commit()
            generate_dunning_message.delay(transaction_id, transaction.failure_reason)
            return

        logger.info(f"[{transaction_id}] ML Model scheduled retry {attempt_number} for {chosen_timestamp} (Predicted prob: {chosen_prob:.2%})")

        # Create retry attempt record
        retry_attempt = RetryAttempt(
            transaction_id=transaction_id,
            attempt_number=attempt_number,
            scheduled_timestamp=chosen_timestamp,
            predicted_success_probability=chosen_prob
        )
        db.add(retry_attempt)
        db.commit()

        # Schedule execution and notify user
        execute_retry.apply_async(args=[transaction_id, attempt_number], eta=chosen_timestamp)
        generate_dunning_message.delay(transaction_id, transaction.failure_reason)

        transaction.current_status = "retrying"
        db.commit()

    except Exception as e:
        logger.error(f"[{transaction_id}] Error in process_failed_payment: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()


@celery_app.task(name="app.tasks.execute_retry")
def execute_retry(transaction_id: str, attempt_number: int):
    """
    Executes a scheduled retry attempt and calculates the outcome.
    """
    logger.info(f"[{transaction_id}] Executing retry attempt #{attempt_number}.")
    db = SessionLocal()
    try:
        transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
        retry_attempt = db.query(RetryAttempt).filter(
            RetryAttempt.transaction_id == transaction_id, 
            RetryAttempt.attempt_number == attempt_number
        ).first()

        if not transaction or not retry_attempt:
            logger.error(f"[{transaction_id}] Transaction or RetryAttempt not found.")
            return

        # IDEMPOTENCY CHECK
        if transaction.current_status in ("recovered", "lost"):
            logger.info(f"[{transaction_id}] Skipping execution, transaction is already resolved ({transaction.current_status}).")
            return

        # Mark execution time
        retry_attempt.executed_timestamp = datetime.now()

        # Recompute the ground-truth outcome
        hours_since_failure = (retry_attempt.scheduled_timestamp - transaction.original_timestamp).total_seconds() / 3600
        retry_day_of_month = retry_attempt.scheduled_timestamp.day

        base_success_prob = {
            "insufficient_funds": 0.35,
            "bank_server_timeout": 0.70,
            "invalid_upi_pin": 0.45,
        }.get(transaction.failure_reason, 0.0)

        prob = base_success_prob

        if transaction.failure_reason == "insufficient_funds":
            if retry_day_of_month in [1, 2, 3, 28, 29, 30, 31]:
                prob *= 1.6
            if hours_since_failure < 6:
                prob *= 0.5

        if transaction.failure_reason == "bank_server_timeout":
            if hours_since_failure < 2:
                prob *= 1.3
            if hours_since_failure > 48:
                prob *= 0.8

        prob *= (0.85 ** (attempt_number - 1))
        prob = prob + random.gauss(0, 0.05)
        prob = max(0, min(1, prob))

        outcome = "success" if random.random() < prob else "failed"
        logger.info(f"[{transaction_id}] Retry #{attempt_number} outcome: {outcome} (True prob was {prob:.2%})")

        # Save outcome
        retry_attempt.outcome = outcome
        db.commit()

        if outcome == "success":
            transaction.current_status = "recovered"
            logger.info(f"[{transaction_id}] Successfully recovered transaction!")
            db.commit()
        else:
            # Trigger the next attempt evaluation
            process_failed_payment.delay(transaction_id)

    except Exception as e:
        logger.error(f"[{transaction_id}] Error in execute_retry: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()


@celery_app.task(name="app.tasks.generate_dunning_message")
def generate_dunning_message(transaction_id: str, reason: str):
    """
    Generates a context-aware dunning communication to send to the user.
    """
    from app.dunning.templates import generate_message
    
    logger.info(f"[{transaction_id}] Generating dunning message for reason: '{reason}'")
    db = SessionLocal()
    try:
        transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
        
        if not transaction:
            logger.error(f"[{transaction_id}] Transaction not found for dunning message generation.")
            return

        scheduled_retry_time = None
        retryable_reasons = ["insufficient_funds", "bank_server_timeout", "invalid_upi_pin"]
        
        if reason in retryable_reasons:
            # Look up the latest retry attempt to get its scheduled time
            latest_retry = (
                db.query(RetryAttempt)
                .filter(RetryAttempt.transaction_id == transaction_id)
                .order_by(RetryAttempt.attempt_number.desc())
                .first()
            )
            if latest_retry and latest_retry.scheduled_timestamp:
                scheduled_retry_time = latest_retry.scheduled_timestamp

        # Generate the dynamic template text
        message_text = generate_message(
            failure_reason=reason,
            transaction_type=transaction.transaction_type,
            amount_inr=transaction.amount_inr,
            scheduled_retry_time=scheduled_retry_time
        )
        
        dunning_msg = DunningMessage(
            transaction_id=transaction_id,
            message_text=message_text,
            reason_context=reason
        )
        db.add(dunning_msg)
        db.commit()
        logger.info(f"[{transaction_id}] Dunning message saved.")

    except Exception as e:
        logger.error(f"[{transaction_id}] Error in generate_dunning_message: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()