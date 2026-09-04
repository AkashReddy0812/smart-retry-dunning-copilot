from datetime import datetime

def generate_message(failure_reason: str, transaction_type: str, amount_inr: float, scheduled_retry_time: datetime = None) -> str:
    # Format amount with 2 decimal places and commas
    amount = f"{amount_inr:,.2f}"
    
    # Determine the context string
    plan_or_purchase = "subscription" if transaction_type == "subscription_renewal" else "purchase"
    
    messages = {
        "insufficient_funds": f"Hi! Your payment of ₹{amount} for your {plan_or_purchase} couldn't go through — it looks like there weren't sufficient funds available. No action needed — we'll automatically retry shortly.",
        "bank_server_timeout": f"Hi! Your payment of ₹{amount} couldn't be completed due to a temporary issue with your bank's servers. We'll automatically retry shortly — no action needed.",
        "invalid_upi_pin": f"Hi! Your payment of ₹{amount} failed because of an incorrect UPI PIN entry. We'll retry shortly, but please make sure your UPI PIN is correct to avoid this happening again.",
        "card_expired": f"Hi! Your card on file has expired, so we couldn't process your payment of ₹{amount}. Please update your payment method to continue.",
        "card_lost_stolen": f"Hi! We weren't able to process your payment of ₹{amount} because your card appears to be reported lost or stolen. Please add a new payment method to continue.",
        "issuer_decline_risk": f"Hi! Your payment of ₹{amount} was declined by your bank for security reasons. Please contact your bank or try an alternate payment method.",
        "retries_exhausted": f"Hi! Unfortunately we were unable to process your payment of ₹{amount} after multiple attempts. Please update your payment method or contact support to continue your {plan_or_purchase}."
    }
    
    # Generic fallback
    base_msg = messages.get(
        failure_reason,
        f"Hi! We were unable to process your payment of ₹{amount} for your {plan_or_purchase}. Please check your payment method and try again."
    )
    
    # Append the retry time if applicable
    retryable_reasons = {"insufficient_funds", "bank_server_timeout", "invalid_upi_pin"}
    if scheduled_retry_time and failure_reason in retryable_reasons:
        formatted_time = scheduled_retry_time.strftime("%b %d, %I:%M %p")
        base_msg += f" We'll try again around {formatted_time}."
        
    return base_msg