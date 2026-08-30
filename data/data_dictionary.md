# Data Dictionary

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
