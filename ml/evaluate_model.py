import os
import json
import numpy as np
import pandas as pd
from datetime import timedelta
import xgboost as xgb
import joblib
from sklearn.model_selection import GroupShuffleSplit
from sklearn.metrics import roc_auc_score, precision_score, recall_score, f1_score
import warnings

warnings.filterwarnings('ignore')

# Paths
DATA_DIR = "../data"
TRANSACTIONS_PATH = os.path.join(DATA_DIR, "transactions.csv")
RETRY_ATTEMPTS_PATH = os.path.join(DATA_DIR, "retry_attempts.csv")
MODEL_PATH = "model.pkl"
FEATURES_PATH = "feature_columns.pkl"
OUTPUT_JSON_PATH = "baseline_comparison.json"

# Ground-truth probability formula (re-implemented for simulation)
def get_ground_truth_prob(failure_reason, hours, day_of_month, attempt_number):
    """
    Re-implementation of the assumed original data generator logic for retry outcomes.
    Returns the true probability of success for a given simulated retry.
    """
    is_boundary = day_of_month in [1, 2, 3, 28, 29, 30, 31]
    
    if failure_reason in ['card_expired', 'card_lost_stolen', 'issuer_decline_risk']:
        base_prob = 0.00
    elif failure_reason == 'insufficient_funds':
        base_prob = 0.70 if is_boundary else 0.15
    elif failure_reason == 'technical_glitch':
        base_prob = 0.85 * np.exp(-hours / 24.0)
    elif failure_reason == 'network_timeout':
        base_prob = 0.80 * np.exp(-hours / 12.0)
    else:
        base_prob = 0.30
        
    # Decay slightly with each subsequent attempt
    prob = base_prob * (0.85 ** (attempt_number - 1))
    return np.clip(prob, 0.0, 1.0)

def calculate_next_boundary_hours(current_date):
    """Find hours to the next month boundary (1, 2, 3, 28, 29, 30, 31)."""
    target_days = [1, 2, 3, 28, 29, 30, 31]
    check_date = current_date
    hours = 0
    while check_date.day not in target_days:
        check_date += timedelta(days=1)
        hours += 24
    return hours if hours > 0 else 24  # Ensure at least some time passes if already on a boundary day

def main():
    print("Loading data, model, and features...")
    transactions = pd.read_csv(TRANSACTIONS_PATH)
    retries = pd.read_csv(RETRY_ATTEMPTS_PATH)
    
    # Ensure a datetime column exists for simulations
    if 'transaction_date' not in transactions.columns:
        transactions['transaction_date'] = pd.to_datetime('2023-01-01') + pd.to_timedelta(np.random.randint(0, 365, size=len(transactions)), unit='d')
    else:
        transactions['transaction_date'] = pd.to_datetime(transactions['transaction_date'])

    model = joblib.load(MODEL_PATH)
    feature_columns = joblib.load(FEATURES_PATH)
    
    # Merge for features
    df = retries.merge(transactions, on="transaction_id", how="inner")
    
    # Recreate target & group
    df['target'] = (df['retry_outcome'] == 'success').astype(int)
    groups = df['customer_id']
    
    print("Recreating exact test set split...")
    # 70% Train, 30% Temp
    gss_train = GroupShuffleSplit(n_splits=1, train_size=0.70, random_state=42)
    train_idx, temp_idx = next(gss_train.split(df, df['target'], groups))
    df_temp = df.iloc[temp_idx]
    
    # 50% Val, 50% Test (of the 30% Temp -> 15% Test)
    gss_val_test = GroupShuffleSplit(n_splits=1, train_size=0.50, random_state=42)
    val_idx, test_idx = next(gss_val_test.split(df_temp, df_temp['target'], df_temp['customer_id']))
    df_test = df_temp.iloc[test_idx].copy()
    
    # Part 1: Model Evaluation Metrics
    print("\n" + "="*40)
    print("PART 1: MODEL EVALUATION METRICS")
    print("="*40)
    
    # Engineer test set features
    df_test['is_near_month_boundary'] = df_test['retry_day_of_month'].isin([1, 2, 3, 28, 29, 30, 31]).astype(int)
    cat_features = ['failure_reason', 'payment_method', 'issuing_bank', 'transaction_type']
    
    df_test_encoded = pd.get_dummies(df_test, columns=cat_features)
    # Ensure all training columns exist
    df_test_encoded = df_test_encoded.reindex(columns=feature_columns, fill_value=0)
    
    X_test = df_test_encoded[feature_columns]
    y_test = df_test['target']
    
    # Predictions
    y_pred_prob = model.predict_proba(X_test)[:, 1]
    y_pred_class = (y_pred_prob >= 0.5).astype(int)
    
    print(f"AUC-ROC:   {roc_auc_score(y_test, y_pred_prob):.4f}")
    print(f"Precision: {precision_score(y_test, y_pred_class):.4f}")
    print(f"Recall:    {recall_score(y_test, y_pred_class):.4f}")
    print(f"F1 Score:  {f1_score(y_test, y_pred_class):.4f}")
    
    print("\nCalibration Check (10 Buckets):")
    df_calib = pd.DataFrame({'true': y_test, 'pred_prob': y_pred_prob})
    df_calib['bucket'] = pd.qcut(df_calib['pred_prob'], 10, duplicates='drop')
    calib_stats = df_calib.groupby('bucket').agg(
        mean_pred=('pred_prob', 'mean'),
        actual_rate=('true', 'mean'),
        count=('true', 'count')
    )
    print(calib_stats.to_string(formatters={'mean_pred': '{:.3f}'.format, 'actual_rate': '{:.3f}'.format}))

    # Get unique failed transactions for the simulations
    test_txns = df_test.drop_duplicates(subset=['transaction_id']).copy()
    total_txns = len(test_txns)
    
    print("\n" + "="*40)
    print(f"PART 2 & 3: SIMULATING STRATEGIES ON {total_txns} TRANSACTIONS")
    print("="*40)

    # Initialize trackers
    naive_recovered_count = 0
    naive_recovered_revenue = 0.0
    smart_recovered_count = 0
    smart_recovered_revenue = 0.0
    smart_skipped_count = 0
    
    non_retryable_reasons = ['card_expired', 'card_lost_stolen', 'issuer_decline_risk']

    np.random.seed(42)  # For reproducible simulation outcomes
    
    for idx, row in test_txns.iterrows():
        txn_id = row['transaction_id']
        amount = row['amount_inr']
        reason = row['failure_reason']
        base_date = row['transaction_date']
        
        # --- NAIVE STRATEGY SIMULATION ---
        # Fixed schedule: 24h, 72h, 120h
        naive_success = False
        for attempt, hours_offset in enumerate([24, 72, 120], start=1):
            retry_date = base_date + timedelta(hours=hours_offset)
            prob = get_ground_truth_prob(reason, hours_offset, retry_date.day, attempt)
            if np.random.rand() < prob:
                naive_success = True
                naive_recovered_count += 1
                naive_recovered_revenue += amount
                break  # Stop retrying upon success
                
        # --- SMART STRATEGY SIMULATION ---
        if reason in non_retryable_reasons:
            smart_skipped_count += 1
            continue  # Smart strategy skips non-retryables
            
        boundary_hours = calculate_next_boundary_hours(base_date)
        candidate_hours = [2, 6, 24, 72, boundary_hours]
        
        # Build features for candidates to get model predictions
        candidates_data = []
        for ch in candidate_hours:
            c_date = base_date + timedelta(hours=ch)
            candidates_data.append({
                'hours_since_original_failure': ch,
                'retry_day_of_month': c_date.day,
                'is_near_month_boundary': int(c_date.day in [1, 2, 3, 28, 29, 30, 31]),
                'amount_inr': amount,
                'failure_reason': reason,
                'payment_method': row['payment_method'],
                'issuing_bank': row['issuing_bank'],
                'transaction_type': row['transaction_type']
            })
            
        cand_df = pd.DataFrame(candidates_data)
        cand_encoded = pd.get_dummies(cand_df, columns=cat_features)
        
        smart_success = False
        for attempt in range(1, 4):
            cand_encoded['attempt_number'] = attempt
            cand_encoded_aligned = cand_encoded.reindex(columns=feature_columns, fill_value=0)
            
            # Predict probabilities
            cand_probs = model.predict_proba(cand_encoded_aligned)[:, 1]
            best_idx = np.argmax(cand_probs)
            
            # Simulate outcome at chosen optimal time
            chosen_hours = candidate_hours[best_idx]
            chosen_date = base_date + timedelta(hours=int(chosen_hours))
            true_prob = get_ground_truth_prob(reason, chosen_hours, chosen_date.day, attempt)
            
            if np.random.rand() < true_prob:
                smart_success = True
                smart_recovered_count += 1
                smart_recovered_revenue += amount
                break
            else:
                # Remove the failed candidate time so we don't pick it again for attempt 2/3
                cand_probs[best_idx] = -1.0 
                candidate_hours.pop(best_idx)
                cand_encoded.drop(index=best_idx, inplace=True)
                cand_encoded.reset_index(drop=True, inplace=True)
                
                if len(candidate_hours) == 0:
                    break

    # Part 4: Comparison Output
    naive_rr = (naive_recovered_count / total_txns) * 100
    smart_rr = (smart_recovered_count / total_txns) * 100
    
    rr_diff = smart_rr - naive_rr
    rev_diff = smart_recovered_revenue - naive_recovered_revenue
    rev_lift = (rev_diff / naive_recovered_revenue) * 100 if naive_recovered_revenue > 0 else 0

    print("\n" + "="*40)
    print("PART 4: PERFORMANCE COMPARISON")
    print("="*40)
    print(f"Total Unique Failed Transactions: {total_txns}")
    print(f"Smart Strategy skipped {smart_skipped_count} non-retryable failures.")
    print("-" * 40)
    print(f"{'Metric':<20} | {'Naive Strategy':<15} | {'Smart Strategy':<15}")
    print("-" * 40)
    print(f"{'Recovery Rate':<20} | {naive_rr:>13.2f}% | {smart_rr:>13.2f}%")
    print(f"{'Revenue Recovered':<20} | ₹{naive_recovered_revenue:>12,.2f} | ₹{smart_recovered_revenue:>12,.2f}")
    print("-" * 40)
    print(f"Improvement:")
    print(f"  Recovery Rate: +{rr_diff:.2f} percentage points")
    print(f"  Revenue Lift:  +{rev_lift:.2f}% (₹{rev_diff:,.2f})")
    
    # Save results to JSON
    results = {
        "total_transactions": total_txns,
        "naive": {
            "recovery_rate_pct": round(naive_rr, 2),
            "revenue_recovered_inr": round(naive_recovered_revenue, 2)
        },
        "smart": {
            "recovery_rate_pct": round(smart_rr, 2),
            "revenue_recovered_inr": round(smart_recovered_revenue, 2),
            "skipped_non_retryable": smart_skipped_count
        },
        "improvement": {
            "recovery_rate_pp": round(rr_diff, 2),
            "revenue_lift_pct": round(rev_lift, 2),
            "revenue_diff_inr": round(rev_diff, 2)
        }
    }
    
    with open(OUTPUT_JSON_PATH, "w") as f:
        json.dump(results, f, indent=4)
        
    print(f"\nResults saved to {OUTPUT_JSON_PATH}")

if __name__ == "__main__":
    main()