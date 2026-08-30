# Module 2: ML Model (Retry Success Predictor)

See SYSTEM_DESIGN.md §3 for full spec.

- `train_model.py` — trains the XGBoost retry-success classifier
- `evaluate_model.py` — metrics + naive baseline comparison
- `retry_policy.py` — §3.3 decision policy (candidate retry times → argmax choice)
