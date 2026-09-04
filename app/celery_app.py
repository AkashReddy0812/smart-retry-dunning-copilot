import os
from celery import Celery
from dotenv import load_dotenv
from app.tracing import setup_tracing
from opentelemetry.instrumentation.celery import CeleryInstrumentor

# Load environment variables from a .env file if present
load_dotenv()

# Read Redis URL from environment, defaulting to local Redis
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Initialize Celery app
celery_app = Celery(
    "smart_retry",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["app.tasks"]
)

# Configure Celery settings
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    timezone="Asia/Kolkata"
)

# Set up tracing for the Celery worker and instrument it
setup_tracing("smart-retry-worker")
CeleryInstrumentor().instrument()

# Simple test task to verify the worker is alive
@celery_app.task
def ping():
    return "pong"