import os
import joblib
import pandas as pd
import numpy as np
import shap
import matplotlib.pyplot as plt
from sklearn.model_selection import GroupShuffleSplit
import warnings

# Suppress warnings for cleaner output
warnings.filterwarnings('ignore')

# Set up paths
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(_THIS_DIR, "model.pkl")
FEATURES_PATH = os.path.join(_THIS_DIR, "feature_columns.pkl")
TX_DATA_PATH = os.path.join(os.path.dirname(_THIS_DIR), "data", "transactions.csv")
RETRIES_DATA_PATH = os.path.join(os.path.dirname(_THIS_DIR), "data", "retry_attempts.csv")

def get_test_data(feature_columns):
    """Recreates the exact same X_test used in model evaluation by merging and splitting identical to train_model.py"""
    
    # 1. Load both datasets
    tx_df = pd.read_csv(TX_DATA_PATH)
    retries_df = pd.read_csv(RETRIES_DATA_PATH)
    
    # 2. Merge retry_attempts with transactions on transaction_id
    df = pd.merge(retries_df, tx_df, on='transaction_id', how='left')
    
    # 3. Compute is_near_month_boundary
    if 'retry_day_of_month' in df.columns:
        df['is_near_month_boundary'] = df['retry_day_of_month'].isin([1, 2, 3, 28, 29, 30, 31]).astype(int)
    
    # 4. One-hot encode the categorical columns
    cat_features = ['failure_reason', 'payment_method', 'issuing_bank', 'transaction_type']
    df_encoded = pd.get_dummies(df, columns=[c for c in cat_features if c in df.columns])
    
    # 5. Align columns to match the trained model feature columns
    X_full = df_encoded.reindex(columns=feature_columns, fill_value=0)
    
    # 6. Recreate the exact same GroupShuffleSplit
    gss = GroupShuffleSplit(n_splits=1, test_size=0.15, random_state=42)
    
    # Split using the customer_id from the merged dataframe
    groups = df['customer_id'] if 'customer_id' in df.columns else df.index
    train_idx, test_idx = next(gss.split(X_full, groups=groups))
    
    return X_full.iloc[test_idx]

def explain_single_prediction(transaction_features_dict, feature_columns, explainer):
    """
    Computes SHAP values for a single transaction/retry-candidate 
    and returns the top 5 driving features.
    """
    # 1. Prepare data exactly as the model expects
    df_single = pd.DataFrame([transaction_features_dict])
    
    cat_features = ['failure_reason', 'payment_method', 'issuing_bank', 'transaction_type']
    present_cats = [c for c in cat_features if c in df_single.columns]
    
    df_encoded = pd.get_dummies(df_single, columns=present_cats)
    df_aligned = df_encoded.reindex(columns=feature_columns, fill_value=0)
    
    # 2. Compute SHAP values
    shap_values = explainer.shap_values(df_aligned)
    
    # Handle output format differences between XGBoost versions
    if isinstance(shap_values, list):
        shap_vals = shap_values[1][0]  # Class 1, first instance
    else:
        shap_vals = shap_values[0]     # First instance
        
    # 3. Pair feature names with their SHAP impact values
    feature_impacts = list(zip(feature_columns, shap_vals))
    
    # 4. Sort by absolute magnitude to find the most influential features (positive or negative)
    feature_impacts.sort(key=lambda x: abs(x[1]), reverse=True)
    
    return feature_impacts[:5]


if __name__ == "__main__":
    print("Loading model and feature columns...")
    model = joblib.load(MODEL_PATH)
    feature_columns = joblib.load(FEATURES_PATH)
    
    print("Loading and preparing test data...")
    X_test = get_test_data(feature_columns)
    
    print("Creating SHAP TreeExplainer...")
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_test)
    
    # Handle format differences for plotting
    shap_vals_for_plot = shap_values[1] if isinstance(shap_values, list) else shap_values

    print("Generating SHAP summary plot (beeswarm)...")
    plt.figure(figsize=(10, 8))
    shap.summary_plot(shap_vals_for_plot, X_test, show=False)
    plt.savefig(os.path.join(_THIS_DIR, "shap_summary.png"), bbox_inches='tight', dpi=300)
    plt.close()

    print("Generating SHAP feature importance plot (bar)...")
    plt.figure(figsize=(10, 8))
    shap.summary_plot(shap_vals_for_plot, X_test, plot_type="bar", show=False)
    plt.savefig(os.path.join(_THIS_DIR, "shap_feature_importance.png"), bbox_inches='tight', dpi=300)
    plt.close()
    
    print(f"Plots successfully saved to {os.path.basename(_THIS_DIR)}/ directory.\n")
    
    print("--- Explaining a Single Prediction ---")
    example_candidate = {
        'failure_reason': 'insufficient_funds',
        'payment_method': 'UPI',             # Fixed casing
        'issuing_bank': 'HDFC',              # Fixed casing
        'transaction_type': 'subscription_renewal',
        'amount_inr': 1499.0,
        'attempt_number': 1,
        'hours_since_original_failure': 72.0,
        'retry_day_of_month': 1,            # Month boundary
        'is_near_month_boundary': 1         # True
    }
    
    print("Candidate Feature Profile:")
    for k, v in example_candidate.items():
        print(f"  {k}: {v}")
        
    print("\nTop 5 Influential Features (SHAP Values):")
    top_features = explain_single_prediction(example_candidate, feature_columns, explainer)
    
    for feature_name, shap_val in top_features:
        # A positive SHAP value pushes the probability of success UP
        # A negative SHAP value pushes the probability of success DOWN
        direction = "Positive Impact (↑)" if shap_val > 0 else "Negative Impact (↓)"
        print(f"  {feature_name:<40} | {shap_val:>8.4f}  [{direction}]")