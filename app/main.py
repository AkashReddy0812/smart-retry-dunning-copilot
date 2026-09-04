from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

from app.db import init_db
from app.routers import simulate, dashboard, transactions, debug
from app.tracing import setup_tracing
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

# Set up tracing for the API service before initializing the app
setup_tracing("smart-retry-api")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup event: Initialize DB schema
    init_db()
    yield
    # Shutdown event: (nothing required for now)

app = FastAPI(
    title="Smart Retry API",
    description="API for simulating failed payments and tracking retry outcomes",
    lifespan=lifespan
)

# Instrument the FastAPI app for automatic request tracing
FastAPIInstrumentor.instrument_app(app)

# Include Routers (must come before the static mount to avoid conflicts)
app.include_router(simulate.router)
app.include_router(dashboard.router)
app.include_router(transactions.router)
app.include_router(debug.router)

# Mount the frontend dashboard
app.mount("/dashboard", StaticFiles(directory="dashboard", html=True), name="dashboard")

@app.get("/")
def health_check():
    return {"status": "ok"}