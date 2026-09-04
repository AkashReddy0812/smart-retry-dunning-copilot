import os
import joblib
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import warnings

# Suppress sklearn/pandas alignment warnings during prediction
warnings.filterwarnings('ignore')

# Load models at the module level using absolute paths relative to this file
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(_THIS_DIR, "model.pkl")
FEATURES_PATH = os.path.join(_THIS_DIR, "feature_columns.pkl")

try:
    MODEL = joblib.load(MODEL_PATH)
    FEATURE_COLUMNS = joblib.load(FEATURES_PATH)
except FileNotFoundError:
    MODEL = None
    FEATURE_COLUMNS = None
    print(f"Warning: Could not find model files at {MODEL_PATH} or {FEATURES_PATH}.")

def _get_next_month_boundary(current_timestamp: datetime) -> datetime:
    """Finds the next upcoming month-boundary date (1-3, 28-31) strictly after the current_timestamp."""
    boundary_days = {1, 2, 3, 28, 29, 30, 31}
    next_ts = current_timestamp + timedelta(hours=24)
    while next_ts.day not in boundary_days:
        next_ts += timedelta(hours=24)
    return next_ts

def choose_best_retry(
    model, 
    feature_columns, 
    failure_reason, 
    payment_method, 
    issuing_bank, 
    transaction_type, 
    amount_inr, 
    original_failure_timestamp, 
    attempt_number,
    return_details=False  # Added optional param for debugging/sanity checks
):
    """
    Evaluates candidate retry times and returns the best option based on predicted success probability.
    
    Returns:
        tuple: (chosen_retry_timestamp, predicted_success_probability)
        if return_details is True, returns (timestamp, prob, list_of_all_candidates)
    """
    if failure_reason in ["card_expired", "card_lost_stolen", "issuer_decline_risk"]:
        return (None, None, []) if return_details else (None, None)
        
    # Ensure candidates are scheduled into the future from when this function is actually called
    anchor_time = max(original_failure_timestamp, datetime.now())
        
    # Start with the standard 4 candidate times relative to the anchor_time
    candidate_timestamps = [
        anchor_time + timedelta(hours=2),
        anchor_time + timedelta(hours=6),
        anchor_time + timedelta(hours=24),
        anchor_time + timedelta(hours=72)
    ]
    candidate_labels = ["+2h", "+6h", "+24h", "+72h"]
    
    # Exclude the "next month boundary" strategy for technical/timeout errors 
    # where day-of-month timing has no semantic relationship to recovery.
    if failure_reason not in ("bank_server_timeout", "invalid_upi_pin"):
        candidate_timestamps.append(_get_next_month_boundary(anchor_time))
        candidate_labels.append("Next Month Boundary")
    
    candidates_data = []
    for cand_ts in candidate_timestamps:
        # Note: The ML model feature must still calculate total elapsed time from the ORIGINAL failure, 
        # not the anchor time, so we keep original_failure_timestamp here.
        hours_diff = (cand_ts - original_failure_timestamp).total_seconds() / 3600.0
        day_of_month = cand_ts.day
        is_near_boundary = int(day_of_month in [1, 2, 3, 28, 29, 30, 31])
        
        candidates_data.append({
            'failure_reason': failure_reason,
            'payment_method': payment_method,
            'issuing_bank': issuing_bank,
            'transaction_type': transaction_type,
            'amount_inr': amount_inr,
            'attempt_number': attempt_number,
            'hours_since_original_failure': hours_diff,
            'retry_day_of_month': day_of_month,
            'is_near_month_boundary': is_near_boundary
        })
        
    df_candidates = pd.DataFrame(candidates_data)
    
    cat_features = ['failure_reason', 'payment_method', 'issuing_bank', 'transaction_type']
    df_encoded = pd.get_dummies(df_candidates, columns=cat_features)
    
    df_aligned = df_encoded.reindex(columns=feature_columns, fill_value=0)
    
    probs = model.predict_proba(df_aligned)[:, 1]
    
    best_idx = int(np.argmax(probs))
    best_timestamp = candidate_timestamps[best_idx]
    best_prob = float(probs[best_idx])
    
    if return_details:
        details = list(zip(candidate_labels, candidate_timestamps, probs))
        return best_timestamp, best_prob, details
        
    return best_timestamp, best_prob


if __name__ == "__main__":
    if MODEL is None or FEATURE_COLUMNS is None:
        print("Cannot run examples: Model or feature columns missing. Train the model first.")
    else:
        print("Running Sanity Checks...\n")
        
        # Hardcoding the current time context for reproducibility in output display
        now = datetime(2026, 9, 2, 10, 43, 8)
        
        def print_test_case(test_name, result):
            print(f"--- {test_name} ---")
            best_time, prob, details = result
            if not details:
                print(f"Outcome: Non-retryable (Timestamp={best_time}, Prob={prob})\n")
                return
            
            print(f"Original Failure: {now.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'Candidate Label':<20} | {'Timestamp':<20} | {'Predicted Prob'}")
            print("-" * 65)
            for label, ts, p in details:
                print(f"{label:<20} | {ts.strftime('%Y-%m-%d %H:%M:%S'):<20} | {p:.2%}")
            print("-" * 65)
            print(f"Chosen Retry Time: {best_time.strftime('%Y-%m-%d %H:%M:%S')} (Predicted success prob: {prob:.2%})\n")

        # Test Case 1: Non-retryable
        res1 = choose_best_retry(
            model=MODEL, feature_columns=FEATURE_COLUMNS,
            failure_reason="card_expired", payment_method="credit_card",
            issuing_bank="hdfc", transaction_type="subscription_renewal",
            amount_inr=999.0, original_failure_timestamp=now, attempt_number=1,
            return_details=True
        )
        print_test_case("Test Case 1: Non-retryable Failure", res1)
        
        # Test Case 2: Insufficient Funds (Should favor a boundary date)
        res2 = choose_best_retry(
            model=MODEL, feature_columns=FEATURE_COLUMNS,
            failure_reason="insufficient_funds", payment_method="upi",
            issuing_bank="sbi", transaction_type="emi_payment",
            amount_inr=4500.0, original_failure_timestamp=now, attempt_number=1,
            return_details=True
        )
        print_test_case("Test Case 2: Insufficient Funds", res2)

        # Test Case 3: Technical Glitch (Should favor sooner retries)
        res3 = choose_best_retry(
            model=MODEL, feature_columns=FEATURE_COLUMNS,
            failure_reason="technical_glitch", payment_method="debit_card",
            issuing_bank="icici", transaction_type="one_time",
            amount_inr=150.0, original_failure_timestamp=now, attempt_number=2,
            return_details=True
        )
        print_test_case("Test Case 3: Technical Glitch", res3)