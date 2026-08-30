import pandas as pd
import numpy as np
import uuid
import random
from datetime import datetime, timedelta

def main():
    # Set fixed seeds for reproducibility
    np.random.seed(42)
    random.seed(42)

    # ==========================================
    # 1. TRANSACTIONS GENERATION
    # ==========================================
    N = 15000
    NUM_CUSTOMERS = 3000
    
    # Split customers into subscription and one-time pools
    sub_customers = [f"CUST_{i}" for i in range(2000)]
    one_time_customers = [f"CUST_{i}" for i in range(2000, NUM_CUSTOMERS)]

    # Assign a fixed billing anchor day for each subscription customer
    sub_anchors = {c: random.randint(1, 28) for c in sub_customers}

    start_date = datetime(2026, 1, 1)
    
    n_sub = int(N * 0.65)
    
    # Helper to generate dates with a slight weekend bias
    def get_one_time_date(start, days_window=180):
        while True:
            d = start + timedelta(
                days=random.randint(0, days_window - 1), 
                hours=random.randint(0, 23), 
                minutes=random.randint(0, 59)
            )
            # Higher acceptance chance on weekends (5=Sat, 6=Sun)
            if d.weekday() >= 5: 
                if random.random() < 0.8: return d
            else:
                if random.random() < 0.4: return d

    transactions = []
    
    print("Generating transactions...")
    for i in range(N):
        tx_id = str(uuid.uuid4())
        is_sub = (i < n_sub)
        tx_type = "subscription_renewal" if is_sub else "one_time"

        if is_sub:
            c_id = random.choice(sub_customers)
            month_offset = random.randint(0, 5)
            anchor = sub_anchors[c_id]
            
            # Cluster around billing anchor day with small noise
            day_noise = random.randint(-1, 1)
            tx_date = start_date + timedelta(days=(month_offset * 30) + anchor - 1 + day_noise)
            tx_date = tx_date.replace(hour=random.randint(0,23), minute=random.randint(0,59))
            
            # Amount: sample from {199, 499, 999, 1999} + noise
            base_amt = random.choice([199, 499, 999, 1999])
            noise = random.uniform(-0.05, 0.05)
            amt = round(base_amt * (1 + noise), 2)
        else:
            c_id = random.choice(one_time_customers)
            tx_date = get_one_time_date(start_date, 180)
            
            # Amount: log-normal with mean ~1200
            amt = round(np.random.lognormal(mean=7.0, sigma=0.5), 2)
            if amt < 10: amt = 10.0 # Safety floor

        pmt = np.random.choice(["UPI", "card", "netbanking"], p=[0.55, 0.35, 0.10])
        
        bank_choices = ["SBI", "HDFC", "ICICI", "Axis", "Kotak", "PNB", "BOB", "Yes Bank", "IndusInd", "IDFC First"]
        bank_weights = [0.25, 0.20, 0.15, 0.10, 0.08, 0.07, 0.05, 0.04, 0.03, 0.03]
        bank = np.random.choice(bank_choices, p=bank_weights)

        status = np.random.choice(["success", "failed"], p=[0.85, 0.15])

        transactions.append({
            "transaction_id": tx_id,
            "customer_id": c_id,
            "transaction_type": tx_type,
            "amount_inr": amt,
            "payment_method": pmt,
            "issuing_bank": bank,
            "timestamp": tx_date,
            "initial_status": status,
            "failure_reason": None,
            "is_retryable": None
        })

    df_tx = pd.DataFrame(transactions)

    # ==========================================
    # 2. FAILURE REASON ASSIGNMENT
    # ==========================================
    print("Assigning failure reasons...")
    def assign_failure(row):
        if row['initial_status'] != 'failed':
            return None, None

        pmt = row['payment_method']
        if pmt == 'UPI':
            reason = np.random.choice(
                ['insufficient_funds', 'bank_server_timeout', 'invalid_upi_pin'], 
                p=[0.82, 0.09, 0.09]
            )
        elif pmt == 'card':
            reason = np.random.choice(
                ['insufficient_funds', 'card_expired', 'card_lost_stolen', 'issuer_decline_risk'], 
                p=[0.05, 0.43, 0.14, 0.38]
            )
        else: # netbanking
            reason = 'bank_server_timeout'

        is_retryable = reason in ['insufficient_funds', 'bank_server_timeout', 'invalid_upi_pin']
        return reason, is_retryable

    df_tx[['failure_reason', 'is_retryable']] = df_tx.apply(assign_failure, axis=1, result_type='expand')

    # ==========================================
    # 3. RETRY ATTEMPTS SIMULATION
    # ==========================================
    print("Simulating retries...")
    retry_records = []
    failed_retryable = df_tx[(df_tx['initial_status'] == 'failed') & (df_tx['is_retryable'] == True)]

    for _, row in failed_retryable.iterrows():
        tx_id = row['transaction_id']
        fail_reason = row['failure_reason']
        orig_time = row['timestamp']
        
        current_time = orig_time

        base_success_prob = {
            "insufficient_funds": 0.35,
            "bank_server_timeout": 0.70,
            "invalid_upi_pin": 0.45,
        }[fail_reason]

        for attempt in range(1, 5):
            # Realistic attempt spacing (increasing gaps)
            if attempt == 1:
                gap = timedelta(hours=random.uniform(1, 12))
            elif attempt == 2:
                gap = timedelta(hours=random.uniform(12, 36))
            elif attempt == 3:
                gap = timedelta(hours=random.uniform(36, 72))
            else:
                gap = timedelta(hours=random.uniform(72, 120))
                
            current_time += gap

            hours_since_failure = (current_time - orig_time).total_seconds() / 3600.0
            retry_day_of_month = current_time.day

            # EXACT Formula Application
            prob = base_success_prob

            # Time-of-retry adjustment
            if fail_reason == "insufficient_funds":
                if retry_day_of_month in [1, 2, 3, 28, 29, 30, 31]:
                    prob *= 1.6
                if hours_since_failure < 6:
                    prob *= 0.5

            if fail_reason == "bank_server_timeout":
                if hours_since_failure < 2:
                    prob *= 1.3
                if hours_since_failure > 48:
                    prob *= 0.8

            # Retry count decay
            prob *= (0.85 ** (attempt - 1))

            # Noise
            prob = prob + random.gauss(0, 0.05)
            prob = max(0, min(1, prob))

            retry_outcome = "success" if random.random() < prob else "failed"

            retry_records.append({
                "transaction_id": tx_id,
                "attempt_number": attempt,
                "retry_timestamp": current_time,
                "hours_since_original_failure": round(hours_since_failure, 2),
                "retry_day_of_month": retry_day_of_month,
                "retry_outcome": retry_outcome
            })

            # Stop simulating further retries if successful
            if retry_outcome == "success":
                break

    df_retries = pd.DataFrame(retry_records)

    # Save CSVs
    df_tx.to_csv("transactions.csv", index=False)
    df_retries.to_csv("retry_attempts.csv", index=False)

    # ==========================================
    # 4. WRITE DATA DICTIONARY
    # ==========================================
    dict_content = """# Data Dictionary

## `transactions.csv`
| Column Name | Type | Description |
|---|---|---|
| `transaction_id` | String (UUID) | Unique identifier for the transaction. |
| `customer_id` | String | Identifier for the customer. Sourced from a pool of ~3000 users. |
| `transaction_type` | Categorical | `subscription_renewal` or `one_time`. |
| `amount_inr` | Float | Transaction value in INR. |
| `payment_method` | Categorical | `UPI`, `card`, or `netbanking`. |
| `issuing_bank` | Categorical | Bank handling the transaction (e.g., `SBI`, `HDFC`, etc). |
| `timestamp` | Datetime | Original time of the transaction attempt. |
| `initial_status` | Categorical | `success` or `failed`. |
| `failure_reason` | Categorical | The specific reason for failure (e.g., `insufficient_funds`, `card_expired`). NULL if successful. |
| `is_retryable` | Boolean | True if the failure reason is eligible for a retry algorithm. NULL if successful. |

## `retry_attempts.csv`
| Column Name | Type | Description |
|---|---|---|
| `transaction_id` | String (UUID) | Foreign key linking to `transactions.csv`. |
| `attempt_number` | Integer | The sequence number of this retry (1-4). |
| `retry_timestamp` | Datetime | The scheduled time this retry occurred. |
| `hours_since_original_failure`| Float | Elapsed time in hours since the original transaction failure. |
| `retry_day_of_month` | Integer | The day of the month (1-31) of the retry. |
| `retry_outcome` | Categorical | `success` or `failed`. |

---
**Note:** The failure_reason distribution and the retry probability formula were specifically calibrated against published payments-industry research regarding soft vs. hard decline ratios, insufficient-funds payday timing impacts, and issuer-timeout retry windows. This provides realistic signal for ML training as no public dataset with real failure-reason + retry-outcome data currently exists.
"""
    with open("data_dictionary.md", "w") as f:
        f.write(dict_content)

    # ==========================================
    # 5. SUMMARY STATS
    # ==========================================
    print("\n" + "="*40)
    print("SUMMARY STATISTICS")
    print("="*40)
    
    total_tx = len(df_tx)
    failed_tx = df_tx[df_tx['initial_status'] == 'failed']
    fail_rate = len(failed_tx) / total_tx
    
    print(f"Total Transactions: {total_tx}")
    print(f"Initial Failure Rate: {fail_rate:.2%}")
    print("\nFailure Reason Distribution (% of failed):")
    print(failed_tx['failure_reason'].value_counts(normalize=True).map(lambda x: f"{x:.2%}").to_string())
    
    print("\nRetryable vs Non-Retryable:")
    print(failed_tx['is_retryable'].value_counts(normalize=True).map(lambda x: f"{x:.2%}").to_string())

    if len(df_retries) > 0:
        overall_retry_success = (df_retries['retry_outcome'] == 'success').mean()
        print(f"\nOverall Retry Success Rate: {overall_retry_success:.2%}")
        
        # Merge for deeper stats
        merged = df_retries.merge(df_tx[['transaction_id', 'failure_reason']], on='transaction_id')
        print("\nRetry Success Rate by Failure Reason:")
        
        # FIXED: Explicitly select the outcome column before applying to avoid DataFrameGroupBy warning
        reason_success = merged.groupby('failure_reason')['retry_outcome'].apply(
            lambda x: (x == 'success').mean()
        )
        
        for reason, rate in reason_success.items():
            print(f"  {reason}: {rate:.2%}")
    
    print("\nArtifacts generated: transactions.csv, retry_attempts.csv, data_dictionary.md")

if __name__ == "__main__":
    main()