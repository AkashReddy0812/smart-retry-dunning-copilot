# Modules 3 & 4: Orchestration Pipeline + Dunning Messages

See SYSTEM_DESIGN.md §4 and §5 for full spec.

- `main.py` — FastAPI app
- `celery_app.py` — Celery config (Redis broker)
- `tasks.py` — process_failed_payment, execute_retry, generate_dunning_message
- `models.py` / `db.py` — DB schema + session setup
- `routers/` — API endpoints split by resource
- `dunning/` — templated (default) and LLM (stretch goal) message generation
