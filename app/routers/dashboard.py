from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db import get_db
from app.models import Transaction, RetryAttempt

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

@router.get("/summary")
def get_dashboard_summary(db: Session = Depends(get_db)):
    total_count = db.query(Transaction).count()
    
    # Query count of transactions grouped by their current_status
    status_counts_query = db.query(
        Transaction.current_status, 
        func.count(Transaction.id)
    ).group_by(Transaction.current_status).all()
    
    # Convert query result to dict
    status_counts = {status: count for status, count in status_counts_query}
    
    # Ensure all required keys exist
    for status in ["failed", "retrying", "recovered", "lost", "skipped_non_retryable"]:
        if status not in status_counts:
            status_counts[status] = 0
            
    return {
        "total_count": total_count,
        "status_counts": status_counts
    }

@router.get("/queue/live")
def get_live_queue(db: Session = Depends(get_db)):
    # Find retry attempts that haven't been executed yet, joining with Transaction for context
    pending_retries = (
        db.query(RetryAttempt, Transaction)
        .join(Transaction)
        .filter(RetryAttempt.executed_timestamp.is_(None))
        .all()
    )
    
    return [
        {
            "transaction_id": tx.id,
            "attempt_number": retry.attempt_number,
            "scheduled_timestamp": retry.scheduled_timestamp,
            "predicted_success_probability": retry.predicted_success_probability,
            "failure_reason": tx.failure_reason
        }
        for retry, tx in pending_retries
    ]