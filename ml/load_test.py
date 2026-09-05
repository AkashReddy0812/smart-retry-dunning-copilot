import time
import uuid
import random
import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# Configuration
API_BASE_URL = "http://localhost:8000"
SIMULATE_ENDPOINT = f"{API_BASE_URL}/simulate/failure"
SUMMARY_ENDPOINT = f"{API_BASE_URL}/dashboard/summary"
TOTAL_REQUESTS = 500
MAX_WORKERS = 20

# System Design 2.2 Calibrated Distribution
# (Reason, Probability Weight, Is Retryable)
FAILURE_DISTRIBUTION = [
    ("insufficient_funds", 45, True),
    ("bank_server_timeout", 15, True),
    ("invalid_upi_pin", 5, True),
    ("card_expired", 15, False),
    ("card_lost_stolen", 5, False),
    ("issuer_decline_risk", 15, False)
]

def generate_payload():
    """Generates a synthetic failure payload matching the calibrated distribution."""
    reasons = [item[0] for item in FAILURE_DISTRIBUTION]
    weights = [item[1] for item in FAILURE_DISTRIBUTION]
    
    chosen_reason = random.choices(reasons, weights=weights, k=1)[0]
    is_retryable = next(item[2] for item in FAILURE_DISTRIBUTION if item[0] == chosen_reason)
    
    return {
        "transaction_id": f"loadtest-{uuid.uuid4()}",
        "customer_id": f"cust-loadtest-{random.randint(100, 999)}",
        "transaction_type": random.choice(["subscription_renewal", "one_time"]),
        "amount_inr": round(random.uniform(100.0, 5000.0), 2),
        "payment_method": random.choice(["UPI", "netbanking", "card"]),
        "issuing_bank": random.choice(["HDFC", "SBI", "ICICI", "AXIS"]),
        "original_timestamp": datetime.utcnow().isoformat(),
        "failure_reason": chosen_reason,
        "is_retryable": is_retryable
    }

def send_request(payload):
    """POSTs a single payload to the API and returns the status code."""
    try:
        response = requests.post(SIMULATE_ENDPOINT, json=payload, timeout=5)
        return response.status_code
    except requests.RequestException:
        return 500

def run_load_test():
    print(f"Generating {TOTAL_REQUESTS} synthetic failure payloads...")
    payloads = [generate_payload() for _ in range(TOTAL_REQUESTS)]
    
    print(f"Starting load test with {MAX_WORKERS} concurrent workers...")
    success_count = 0
    error_count = 0
    
    # Track full end-to-end time
    start_time = time.time()
    
    # Execute requests concurrently
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_req = {executor.submit(send_request, p): p for p in payloads}
        for future in as_completed(future_to_req):
            status = future.result()
            if status == 200:
                success_count += 1
            else:
                error_count += 1

    ingestion_end_time = time.time()
    ingestion_time = ingestion_end_time - start_time
    rps = TOTAL_REQUESTS / ingestion_time
    success_rate = (success_count / TOTAL_REQUESTS) * 100
    
    print(f"\nSent {TOTAL_REQUESTS} failure events in {ingestion_time:.2f} seconds ({rps:.2f} req/sec), {success_rate:.1f}% succeeded")
    print(f"200 OK: {success_count} | Errors: {error_count}")
    
    print("\nPolling for async processing completion...")
    
    poll_start = time.time()
    previous_failed = None
    max_duration = 90
    
    while True:
        elapsed_poll = time.time() - poll_start
        if elapsed_poll >= max_duration:
            print("Max polling time (90s) reached. Stopping monitor.")
            break
            
        try:
            summary_res = requests.get(SUMMARY_ENDPOINT, timeout=5)
            if summary_res.status_code == 200:
                data = summary_res.json()
                status_counts = data.get('status_counts', {})
                current_failed = status_counts.get('failed', 0)
                
                print(f"[{elapsed_poll:.1f}s] Status - Total: {data.get('total_count', 0)} | Failed: {current_failed} | Retrying: {status_counts.get('retrying', 0)} | Skipped: {status_counts.get('skipped_non_retryable', 0)}")
                
                if previous_failed is not None and current_failed >= previous_failed:
                    print("Processing stabilized (failed count stopped decreasing).")
                    break
                    
                previous_failed = current_failed
            else:
                print(f"Failed to fetch dashboard summary (HTTP {summary_res.status_code})")
        except requests.RequestException as e:
            print(f"Could not reach dashboard API: {e}")
            
        time.sleep(3)
        
    full_end_time = time.time()
    total_end_to_end = full_end_time - start_time
    
    print("\n--- Load Test Complete ---")
    print(f"Full pipeline processed {TOTAL_REQUESTS} failure events in {total_end_to_end:.2f} seconds end-to-end (ingestion + async processing)")

if __name__ == "__main__":
    run_load_test()