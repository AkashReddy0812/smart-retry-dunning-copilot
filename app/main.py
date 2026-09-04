from fastapi import FastAPI
from contextlib import asynccontextmanager

from app.db import init_db
from app.routers import simulate, dashboard, transactions

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

# Include Routers
app.include_router(simulate.router)
app.include_router(dashboard.router)
app.include_router(transactions.router)

@app.get("/")
def health_check():
    return {"status": "ok"}