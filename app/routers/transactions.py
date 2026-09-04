from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Transaction

router = APIRouter(prefix="/transactions", tags=["Transactions"])

@router.get("/{transaction_id}")
def get_transaction_details(transaction_id: str, db: Session = Depends(get_db)):
    tx = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
        
    # Python sorting guarantees chronological order (fallback if not default ordered in DB)
    retries = sorted(tx.retry_attempts, key=lambda x: x.created_at)
    dunning = sorted(tx.dunning_messages, key=lambda x: x.created_at)
    
    # Convert SQLAlchemy relationships into standard dictionaries
    return {
        "transaction": {
            "id": tx.id,
            "customer_id": tx.customer_id,
            "transaction_type": tx.transaction_type,
            "amount_inr": tx.amount_inr,
            "payment_method": tx.payment_method,
            "issuing_bank": tx.issuing_bank,
            "original_timestamp": tx.original_timestamp,
            "failure_reason": tx.failure_reason,
            "is_retryable": tx.is_retryable,
            "current_status": tx.current_status,
            "created_at": tx.created_at
        },
        "retry_attempts": [
            {
                "id": r.id,
                "attempt_number": r.attempt_number,
                "scheduled_timestamp": r.scheduled_timestamp,
                "executed_timestamp": r.executed_timestamp,
                "predicted_success_probability": r.predicted_success_probability,
                "outcome": r.outcome,
                "created_at": r.created_at
            } for r in retries
        ],
        "dunning_messages": [
            {
                "id": d.id,
                "message_text": d.message_text,
                "reason_context": d.reason_context,
                "created_at": d.created_at
            } for d in dunning
        ]
    }