# Smart Retry & Dunning Copilot

**Razorpay Buildathon — Track 3: AI Revenue Recovery**

An AI-driven revenue-recovery system for failed digital payments. Instead of retrying every failed payment on the same fixed schedule, this system predicts the optimal time to retry each payment based on its specific failure reason, orchestrates those retries asynchronously and reliably, and generates a personalized message to the customer — then proves it works by comparing recovered revenue against a naive fixed-schedule baseline.

> Full design rationale, architecture, and module-by-module breakdown: [`SYSTEM_DESIGN.md`](./SYSTEM_DESIGN.md)

## Problem

20-40% of subscription churn is attributable to failed payments, most of it recoverable. Most systems retry every failure identically regardless of *why* it failed — an insufficient-funds decline and an expired card have completely different recovery dynamics, and treating them the same wastes retry attempts and recoverable revenue.

## What this does

1. **Predicts** the best time to retry a failed payment (ML model, not a fixed rule)
2. **Orchestrates** retries asynchronously and reliably (FastAPI + Celery + Redis)
3. **Generates** a context-aware customer message per failure reason
4. **Proves** it: dashboard comparing smart-retry recovery vs. naive fixed-schedule baseline

## Status

🚧 In active development — build log below is updated daily through submission (Sep 5, 2026).

| Date | Module | Status |
|---|---|---|
| Aug 30 | Synthetic data generator | In progress |
| Aug 31 | ML model + naive baseline | Not started |
| Sep 1 | Orchestration pipeline | Not started |
| Sep 2 | Dashboard + dunning messages | Not started |
| Sep 3 | Docker Compose + polish | Not started |
| Sep 4 | Pitch video + submission | Not started |

## Run it

```bash
docker compose up
```

(Instructions will be finalized once the pipeline is complete — see `docs/demo-walkthrough.md`.)

## Repository structure

See [`SYSTEM_DESIGN.md`](./SYSTEM_DESIGN.md) §10 for the full structure rationale.

```
data/       synthetic data generation
ml/         model training, evaluation, retry decision policy
app/        FastAPI + Celery + Redis backend
dashboard/  frontend dashboard
docs/       architecture diagram, demo walkthrough
notebooks/  exploration scratchpad
```
