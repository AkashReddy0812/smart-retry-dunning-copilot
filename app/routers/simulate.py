from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional

from app.db import get_db
from app.models import Transaction
from app.tasks import process_failed_payment

router = APIRouter(prefix="/simulate", tags=["Simulate"])

class SimulateFailureRequest(BaseModel):
    transaction_id: str
    customer_id: str
    transaction_type: str
    amount_inr: float
    payment_method: str
    issuing_bank: str
    original_timestamp: Optional[datetime] = Field(default_factory=datetime.now)
    failure_reason: str
    is_retryable: bool

@router.post("/failure")
def simulate_failure(req: SimulateFailureRequest, db: Session = Depends(get_db)):
    # Check if transaction exists
    tx = db.query(Transaction).filter(Transaction.id == req.transaction_id).first()
    
    if not tx:
        # Create it if it doesn't exist
        tx = Transaction(
            id=req.transaction_id,
            customer_id=req.customer_id,
            transaction_type=req.transaction_type,
            amount_inr=req.amount_inr,
            payment_method=req.payment_method,
            issuing_bank=req.issuing_bank,
            original_timestamp=req.original_timestamp,
            failure_reason=req.failure_reason,
            is_retryable=req.is_retryable,
            current_status="failed"
        )
        db.add(tx)
        db.commit()
        db.refresh(tx)
    
    # Trigger celery task asynchronously
    process_failed_payment.delay(req.transaction_id)
    
    return {"status": "failure event submitted", "transaction_id": req.transaction_id}