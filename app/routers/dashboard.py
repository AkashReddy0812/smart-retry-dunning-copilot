import os
import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
import csv
import os
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

@router.get("/efficiency")
def get_retry_efficiency():
    # Resolve absolute path to data/transactions.csv
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    csv_path = os.path.join(base_dir, "data", "transactions.csv")
    
    if not os.path.exists(csv_path):
        raise HTTPException(
            status_code=404, 
            detail="transactions.csv not found in the data/ directory."
        )
        
    total_failed = 0
    non_retryable_count = 0
    retryable_count = 0
    breakdown = {}
    
    with open(csv_path, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Check status (handling both 'initial_status' and 'status' column naming variations)
            status = row.get("initial_status", row.get("status", ""))
            
            if status == "failed":
                total_failed += 1
                
                # Check is_retryable flag (parse string from CSV)
                is_retryable_str = str(row.get("is_retryable", "true")).strip().lower()
                is_retryable = is_retryable_str not in ("false", "0", "")
                
                if not is_retryable:
                    non_retryable_count += 1
                    reason = row.get("failure_reason", "unknown")
                    breakdown[reason] = breakdown.get(reason, 0) + 1
                else:
                    retryable_count += 1
                    
    naive_wasted_attempts = non_retryable_count * 3
    
    return {
        "total_failed": total_failed,
        "non_retryable_count": non_retryable_count,
        "retryable_count": retryable_count,
        "naive_wasted_attempts": naive_wasted_attempts,
        "smart_retries_avoided": naive_wasted_attempts,
        "non_retryable_breakdown": breakdown
    }