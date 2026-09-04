import uuid
from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db import Base

class Transaction(Base):
    __tablename__ = "transactions"

    # Using a string to store UUIDs
    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    customer_id = Column(String, index=True, nullable=False)
    transaction_type = Column(String, nullable=False)
    amount_inr = Column(Float, nullable=False)
    payment_method = Column(String, nullable=False)
    issuing_bank = Column(String, nullable=False)
    original_timestamp = Column(DateTime, nullable=False)
    failure_reason = Column(String, nullable=True)
    is_retryable = Column(Boolean, nullable=False, default=True)
    
    # "failed", "retrying", "recovered", "lost", "skipped_non_retryable"
    current_status = Column(String, nullable=False, default="failed")
    
    # func.now() delegates the default timestamp to the database server
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    # Relationships
    retry_attempts = relationship(
        "RetryAttempt", 
        back_populates="transaction", 
        cascade="all, delete-orphan"
    )
    dunning_messages = relationship(
        "DunningMessage", 
        back_populates="transaction", 
        cascade="all, delete-orphan"
    )


class RetryAttempt(Base):
    __tablename__ = "retry_attempts"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    transaction_id = Column(String, ForeignKey("transactions.id"), nullable=False)
    attempt_number = Column(Integer, nullable=False)
    scheduled_timestamp = Column(DateTime, nullable=False)
    executed_timestamp = Column(DateTime, nullable=True)
    predicted_success_probability = Column(Float, nullable=True)
    
    # "success" or "failed"
    outcome = Column(String, nullable=True)
    
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    # Relationship
    transaction = relationship("Transaction", back_populates="retry_attempts")


class DunningMessage(Base):
    __tablename__ = "dunning_messages"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    transaction_id = Column(String, ForeignKey("transactions.id"), nullable=False)
    message_text = Column(String, nullable=False)
    reason_context = Column(String, nullable=False)
    
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    # Relationship
    transaction = relationship("Transaction", back_populates="dunning_messages")