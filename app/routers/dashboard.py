import os
import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db import get_db
from app.models import Transaction, RetryAttempt

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

@router.get("/summary")
def get_dashboard_summary(db: Session = Depends(get_db)):
    total_count = db.query(Transaction).count()
    
    status_counts_query = db.query(
        Transaction.current_status, 
        func.count(Transaction.id)
    ).group_by(Transaction.current_status).all()
    
    status_counts = {status: count for status, count in status_counts_query}
    
    for status in ["failed", "retrying", "recovered", "lost", "skipped_non_retryable"]:
        if status not in status_counts:
            status_counts[status] = 0
            
    return {
        "total_count": total_count,
        "status_counts": status_counts
    }

@router.get("/comparison")
def get_baseline_comparison():
    # Resolve the absolute path to ml/baseline_comparison.json
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    json_path = os.path.join(base_dir, "ml", "baseline_comparison.json")
    
    if not os.path.exists(json_path):
        raise HTTPException(
            status_code=404, 
            detail="baseline_comparison.json not found. Did you run evaluate_model.py?"
        )
        
    with open(json_path, "r") as f:
        return json.load(f)

@router.get("/queue/live")
def get_live_queue(db: Session = Depends(get_db)):
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