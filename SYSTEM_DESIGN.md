# Smart Retry & Dunning Copilot — System Design
### Hand this document to a code-generation LLM module by module. Do not let it make architectural decisions — only implement what's specified here.

---

## What Is This Project

An AI-driven revenue-recovery system for recurring/one-time digital payments. When a payment fails (card decline, insufficient funds, UPI timeout, expired card, etc.), most systems either give up or retry on a fixed schedule regardless of *why* the payment failed. This project builds a system that:

1. **Predicts** the optimal time to retry each failed payment based on its specific failure reason and context, instead of using one fixed rule for every failure (ML model)
2. **Orchestrates** those retries reliably and asynchronously at scale, without blocking or losing any (Celery + Redis pipeline)
3. **Generates** a personalized, context-aware message to the customer explaining what happened and what to expect (dunning layer)
4. **Proves** the value with a dashboard that directly compares recovered revenue and recovery rate under the smart strategy vs. a naive fixed-schedule baseline

It's an agentic, full-stack AI system — not a single model in a notebook — that recovers money a business would otherwise lose to failed payments.

---

## Problem Statement

Built for **Razorpay's Track 3: AI Revenue Recovery**.

Failed recurring payments are one of the largest and most quietly compounding sources of lost revenue for subscription and e-commerce businesses — industry research puts 20-40% of subscription churn as directly attributable to failed payments, most of which is recoverable with better handling. The standard industry response — retry every failed payment on the same fixed schedule (e.g., 24h, then 72h, then give up) — ignores the fact that different failure reasons have wildly different recovery dynamics: an insufficient-funds decline retried near a customer's likely payday behaves nothing like an expired card that will never succeed no matter how many times it's retried. Businesses that don't differentiate between these cases waste retry attempts, annoy customers with badly-timed nudges, and leave recoverable revenue on the table.

**The problem this project solves**: given a failed payment and its failure context, decide — intelligently, not by fixed rule — whether, when, and how to retry it, and what to tell the customer, in a way that measurably recovers more revenue than a naive fixed-schedule approach.

---

## Why We're Building This

- **Directly maps to Track 3** — revenue recovery is one of the most quantifiable, highest-leverage problems in fintech; every percentage-point improvement in recovery rate is direct, measurable revenue, which makes for a clean and credible pitch.
- **Genuinely differentiated build** — fraud/risk-detection projects are common in ML portfolios and were considered (Track 2) and deliberately set aside; failed-payment recovery + dunning orchestration is a much rarer project shape, and no comparable open dataset or open-source model exists for this exact problem (checked against Hugging Face and Kaggle) — meaning the synthetic data and retry-decision logic built here are original engineering, not a reuse of existing work.
- **Demonstrates full-stack AI engineering, not just a model**: predictive ML, asynchronous distributed orchestration, generative messaging, and a measurable business outcome, all in one coherent pipeline — a much stronger signal for the judged criteria (problem taste, build quality, AI judgment, failure recovery) than a single-model demo.
- **A clean, visual, defensible story for the 5-minute pitch**: the smart-vs-naive recovery comparison is a single chart that proves the system works, which is exactly the kind of concrete signal the "no resume, we read the work" evaluation format rewards.

---

## 0. Quick concept primer (Celery + Redis, since this is new)

- **Redis** = an in-memory data store. Here it plays two roles: (1) the **broker** — a mailbox where tasks wait to be picked up, and (2) a **result/cache store**.
- **Celery** = a task runner. You call `some_task.delay(args)` or `some_task.apply_async(args, eta=<time>)` from your FastAPI code. Celery puts that task in Redis. A separate **worker process** (running `celery -A app worker`) picks it up and executes it — asynchronously, outside the request/response cycle.
- **Why we need this**: when a payment fails, we don't want to retry it *right now* inline — we want to say "retry this in 3 days at 9am" and walk away. Celery's `eta` parameter does exactly that: schedule a function call for a future timestamp. Redis just stores that scheduled job until it's due.
- You will run **3 processes** locally: FastAPI server, Celery worker, and Redis server (via Docker). Docker Compose will wire all three together so you run one command.

---

## 1. Business model being simulated

Mixed: a platform with (a) **recurring subscriptions** (monthly plans, e.g. SaaS/membership) and (b) **one-time payments** (single purchases). Both can fail and both are candidates for retry, but their retry logic differs:
- Subscriptions: failed renewal → retry, and if all retries fail, subscription lapses (churn event)
- One-time payments: failed checkout → retry, and if all retries fail, treated as abandoned/lost sale (no "churn" framing, just lost revenue)

Keep both in the same data model with a `transaction_type` field (`subscription_renewal` | `one_time`), so the ML model and dashboard can treat them uniformly but the dunning message copy differs.

---

## 2. Module 1 — Synthetic Data Generator

**Goal**: produce a transaction dataset with realistic failure and retry-outcome semantics that an ML model can learn real signal from.

### 2.1 Base transaction generation
Generate `N = 15,000` transactions with these fields:

| Field | Type | Generation rule |
|---|---|---|
| `transaction_id` | string (UUID) | random |
| `customer_id` | string | ~3,000 unique customers, transactions distributed with realistic repeat frequency (subscription customers appear monthly, one-time customers appear once or a few times) |
| `transaction_type` | enum | `subscription_renewal` (65%), `one_time` (35%) |
| `amount_inr` | float | subscription: sample from {199, 499, 999, 1999} (typical Indian SaaS/membership price points) with noise; one-time: log-normal distribution, mean ~₹1200 |
| `payment_method` | enum | `UPI` (55%), `card` (35%), `netbanking` (10%) — reflects Indian market share roughly |
| `issuing_bank` | categorical | pick from a list of ~10 major Indian banks (HDFC, ICICI, SBI, Axis, Kotak, etc.), uneven distribution (SBI/HDFC more common) |
| `timestamp` | datetime | spread over a simulated 6-month window; subscription renewals cluster on billing-cycle anchor dates (e.g., customer always bills on the 5th); one-time transactions spread naturally with slight weekend uplift |
| `initial_status` | enum | `success` (78%) / `failed` (22%) — this 22% failure rate is the population we care about; tune this to match cited industry range (20-40% of subscription revenue touched by failures per research) |

### 2.2 Failure reason assignment (only for `initial_status = failed` rows)
Assign `failure_reason` using **weighted rules conditioned on payment_method**, not uniform random:

| failure_reason | Applies to | Approx. share of failures | Retryable? |
|---|---|---|---|
| `insufficient_funds` | UPI, card | 50% | Yes — highly time-sensitive (see 2.3) |
| `bank_server_timeout` | UPI, netbanking | 15% | Yes — retry soon, not time-sensitive |
| `issuer_decline_risk` | card | 15% | Yes — but low success probability |
| `card_expired` | card only | 10% | No — will never succeed on retry without user updating card |
| `card_lost_stolen` | card only | 5% | No — never retry |
| `invalid_upi_pin` | UPI only | 5% | Yes — user-error, moderate success on retry |

This mirrors realistic decline-code distributions (soft declines ~50%, hard/risk declines ~25-30%, card-detail issues ~10-15%) that show up in real dunning research — this is the credibility layer, cite this reasoning in your README/pitch.

### 2.3 Retry simulation logic (this is the core of the "realistic, not random" requirement)

For each failed, retryable transaction, simulate up to 4 retry attempts. For each attempt, compute a **success probability** using this rule-based formula (not ML — this is the "ground truth" the ML model will later learn to approximate):

```
base_success_prob = {
    insufficient_funds: 0.35,
    bank_server_timeout: 0.70,
    issuer_decline_risk: 0.15,
    invalid_upi_pin: 0.45,
    card_expired: 0.0,
    card_lost_stolen: 0.0,
}[failure_reason]

# Time-of-retry adjustment
if failure_reason == insufficient_funds:
    if retry_day_of_month in [1, 2, 3, 28, 29, 30, 31]:  # near likely salary credit
        prob *= 1.6
    if hours_since_failure < 6:
        prob *= 0.5   # too soon, funds situation unchanged

if failure_reason == bank_server_timeout:
    if hours_since_failure < 2:
        prob *= 1.3   # timeouts often transient, quick retry works well
    if hours_since_failure > 48:
        prob *= 0.8   # stale, minor decay

# Retry count decay (diminishing returns / fatigue)
prob *= (0.85 ** (retry_attempt_number - 1))

# Small random noise for realism
prob = clip(prob + gaussian_noise(0, 0.05), 0, 1)

retry_outcome = success if random() < prob else failed
```

Store every retry attempt as its own row in a `retry_attempts` table (not overwriting the original), with:
`transaction_id, attempt_number, retry_timestamp, hours_since_original_failure, retry_outcome, retry_channel (same_method only for MVP)`

Stop simulating further retries once one succeeds, or after 4 attempts.

### 2.4 Output artifacts
- `transactions.csv` — one row per original transaction (with initial_status, failure_reason if applicable)
- `retry_attempts.csv` — one row per retry attempt, foreign-keyed to transaction_id
- A short `data_dictionary.md` documenting every column (you'll want this for the README/judges)

### 2.5 Seeding realism from a public dataset (optional enrichment)
Use the Kaggle "UPI Transactions 2024" dataset (`skullagos5246/upi-transactions-2024-dataset`) only to sanity-check/calibrate your amount distributions and merchant-category mix — don't try to merge it directly, your schema needs fields it doesn't have (failure_reason, retry semantics). Mention in the README that you cross-checked amount/category realism against it.

---

## 3. Module 2 — ML Model (Retry Success Predictor)

**Task framing**: binary classification. Given a failed transaction and a candidate retry time, predict P(retry succeeds).

### 3.1 Features
From `transactions` + engineered from `retry_attempts`:
- `failure_reason` (categorical, one-hot or target-encoded)
- `payment_method`
- `issuing_bank`
- `transaction_type`
- `amount_inr`
- `retry_attempt_number`
- `hours_since_original_failure`
- `day_of_month` (of the candidate retry time)
- `is_near_month_boundary` (derived: day_of_month in [1,3] or [28,31])
- `hour_of_day` (of candidate retry)

### 3.2 Model
- **XGBoost or LightGBM classifier**, binary:success target from `retry_attempts.retry_outcome`
- Train/val/test split: 70/15/15, split by `customer_id` (not row-level) to avoid leakage across a customer's retries
- Metrics to report: AUC-ROC, precision/recall, and — most important for the pitch — **calibration**, since you're using this as a probability, not just a classification

### 3.3 The "smart retry" decision policy (this is what actually gets used at inference/orchestration time)
Given a newly failed transaction:
1. If `failure_reason` is non-retryable (`card_expired`, `card_lost_stolen`) → **do not schedule a retry at all**, immediately route to a "needs new payment method" dunning message. (This alone is a meaningful efficiency win over naive fixed-schedule retry, worth calling out explicitly in the pitch.)
2. Otherwise, for retryable failures: evaluate the model's predicted success probability across a small candidate set of retry times (e.g., +2hrs, +6hrs, +24hrs, +72hrs, next-likely-salary-date) and pick the **argmax** time.
3. Schedule that as the next Celery task.

### 3.4 Naive baseline (for the comparison chart — build this too, it's simple)
Fixed schedule: retry at +24h, +72h, +120h regardless of failure reason, max 3 attempts. Run this against the *same* simulated retry-outcome logic (module 2.3) to get a fair, comparable recovery rate.

---

## 4. Module 3 — Orchestration Pipeline (FastAPI + Celery + Redis)

### 4.1 Components
- **FastAPI app** (`app/main.py`): exposes REST endpoints (see 4.3)
- **Celery app** (`app/celery_app.py`): configured with Redis as broker + result backend
- **Celery tasks** (`app/tasks.py`):
  - `process_failed_payment(transaction_id)` — called immediately when a failure event comes in. Loads the ML model, decides retry policy per §3.3, and either (a) schedules `execute_retry.apply_async(args=[transaction_id, attempt_number], eta=<chosen_time>)`, or (b) marks as non-retryable and triggers dunning message generation directly.
  - `execute_retry(transaction_id, attempt_number)` — simulates executing the retry (looks up the pre-computed ground-truth outcome from your synthetic dataset for demo purposes, OR re-runs the probability formula live for a "live demo" mode), writes outcome to DB, and if failed and attempts remain, calls `process_failed_payment` again for the next scheduling decision.
  - `generate_dunning_message(transaction_id, reason)` — Module 4.

### 4.2 Data storage
PostgreSQL (or SQLite for speed in a 6-day build — **recommend SQLite** unless you're already comfortable with Postgres, since it removes a whole service from Docker Compose and this isn't a scale demo) with tables: `transactions`, `retry_attempts`, `dunning_messages`.

### 4.3 API endpoints (FastAPI)
- `POST /simulate/failure` — inject a new failed payment event (for demo purposes, pulls a row from your synthetic dataset or accepts manual input) → triggers `process_failed_payment.delay(...)`
- `GET /dashboard/summary` — aggregate stats: total recovered $ (smart) vs. (naive baseline), recovery rate % comparison, count of transactions by status
- `GET /transactions/{id}` — full retry history + generated messages for one transaction (good for the "show one live example" part of the pitch)
- `GET /queue/live` — currently scheduled/pending retries (for the "live retry queue" dashboard panel)

### 4.4 Idempotency note (mention this in your build-challenges writeup — judges like seeing this awareness)
Ensure `execute_retry` checks the transaction's current status before acting — if it was already marked successful (e.g., customer paid manually elsewhere), skip the scheduled retry rather than double-processing. Simple guard clause, but worth having and worth mentioning you thought about it.

---

## 5. Module 4 — Dunning Message Generation

**Given the time crunch, default to Option A. Only attempt Option B if Days 1-3 finish ahead of schedule.**

### Option A (recommended default): Templated, context-aware messages
Pre-written templates per `failure_reason`, filled with transaction context (amount, next retry date if applicable). No LLM call — fast, reliable, zero risk of a bad demo moment. E.g.:
> "Hi {name}, your payment of ₹{amount} for {plan} couldn't go through due to a bank server issue. We'll automatically retry shortly — no action needed."

vs. for `card_expired`:
> "Hi {name}, your card ending in {last4} has expired. Please update your payment method to continue your {plan} subscription."

### Option B (stretch goal, only if ahead of schedule): Real LLM call
Use a free-tier LLM API (or Hugging Face Inference free tier) to generate the message from structured context, with tone varying by urgency (soft nudge for first failure, more urgent by 3rd attempt). If you do this, keep Option A as a fallback/cache in case the API is slow or down during the live demo — **never let the live demo depend on an external API call that could fail on stage**.

---

## 6. Module 5 — Dashboard

Simple FastAPI-served frontend (plain HTML/JS + Chart.js, or a small React page — plain HTML/JS is faster to build and perfectly fine for a judged demo). Three panels:
1. **Headline comparison**: recovery rate % and $ recovered — Smart Retry vs. Naive Baseline, side by side bars. This is the single most important visual in your whole project.
2. **Live retry queue**: table of currently-scheduled retries with predicted time and reason
3. **One transaction deep-dive**: pick a transaction_id, show its full timeline (failure → prediction → scheduled retry → outcome → message sent)

---

## 7. Finalized Tech Stack

| Layer | Choice |
|---|---|
| Backend API | FastAPI |
| Async orchestration | Celery |
| Broker/cache | Redis |
| Database | SQLite (simplicity for 6-day build) |
| ML | XGBoost (or LightGBM), scikit-learn for splits/metrics |
| Dunning messages | Templated (Option A default) |
| Dashboard | Plain HTML/JS + Chart.js, served via FastAPI static route |
| Containerization | Docker Compose (FastAPI app + Celery worker + Redis, 3 services) |
| Data generation | Python (pandas + numpy) |

---

## 8. Build order (maps to your 6-day plan)

| Day | Module | Deliverable |
|---|---|---|
| Aug 30 | §2 Synthetic Data Generator | `transactions.csv`, `retry_attempts.csv`, `data_dictionary.md` |
| Aug 31 | §3 ML Model | trained model file, evaluation metrics, naive baseline comparison numbers |
| Sep 1 | §4 Orchestration Pipeline | FastAPI + Celery + Redis wired end-to-end, one failure → scheduled → executed → outcome working live |
| Sep 2 | §5 Dashboard + §5 Dunning (Option A) | dashboard panels working, template messages generating |
| Sep 3 | Docker Compose + polish + bug fixes | one-command demo runs cleanly |
| Sep 4 | Pitch video + README + submission | done |

---

---

## 9. What to tell judges when asked "why these choices"
- Redis Streams/Kafka were considered but Redis+Celery was chosen to keep the system provably correct and demoable within the build window — explicitly frame this as a scoping decision, not a limitation you didn't think about.
- SQLite over Postgres: same reasoning — right-sized for the demo, trivial to swap for a production Postgres instance later (mention this as a known next step).
- Rule-based synthetic data generation over pure-random: because a model trained on random noise has nothing to learn — this was a deliberate design decision to make the ML model's predictions meaningfully better than the naive baseline, and the gap between smart vs. naive **is the deliverable**.

---

## 10. Repository Structure

Evaluators read the repo directly (no resume screening), so structure it so the design in this doc is visibly reflected in the code layout — a judge should be able to open the repo and immediately see the 5 modules as 5 clear folders, not a flat pile of scripts.

```
smart-retry-dunning-copilot/
│
├── README.md                      ← project overview, problem statement, architecture diagram, how to run
├── SYSTEM_DESIGN.md                ← this document (or a trimmed version) — shows judges the design thinking
├── docker-compose.yml              ← one-command run: app + celery worker + redis
├── .env.example                    ← config template (no real secrets committed)
├── requirements.txt
│
├── data/
│   ├── generate_synthetic_data.py  ← §2 generator script
│   ├── data_dictionary.md          ← column documentation
│   ├── transactions.csv            ← generated output (or .gitignore + a "run this first" note if too large)
│   └── retry_attempts.csv
│
├── ml/
│   ├── train_model.py              ← §3 training script (features, XGBoost, train/val/test split)
│   ├── evaluate_model.py           ← metrics + naive baseline comparison, outputs a report
│   ├── model.pkl                   ← trained model artifact (or regenerate-on-build if large)
│   └── retry_policy.py             ← §3.3 decision policy (candidate retry times → argmax choice)
│
├── app/
│   ├── main.py                     ← FastAPI app, mounts routers
│   ├── celery_app.py               ← §4.1 Celery config (Redis broker)
│   ├── tasks.py                    ← §4.1 process_failed_payment, execute_retry, generate_dunning_message
│   ├── models.py                   ← DB schema (SQLAlchemy models: transactions, retry_attempts, dunning_messages)
│   ├── db.py                       ← SQLite connection/session setup
│   ├── routers/
│   │   ├── simulate.py             ← POST /simulate/failure
│   │   ├── dashboard.py            ← GET /dashboard/summary, GET /queue/live
│   │   └── transactions.py         ← GET /transactions/{id}
│   └── dunning/
│       ├── templates.py            ← §5 Option A templated messages
│       └── llm_generator.py        ← §5 Option B stretch-goal LLM call (optional, keep isolated so it's easy to skip)
│
├── dashboard/
│   ├── index.html                  ← §6 dashboard page
│   ├── dashboard.js                ← fetch calls to API + Chart.js rendering
│   └── style.css
│
├── notebooks/
│   └── exploration.ipynb           ← optional: data exploration, model iteration scratchpad (nice to show judges the process)
│
└── docs/
    ├── architecture-diagram.png    ← exported version of the §4 architecture diagram
    └── demo-walkthrough.md         ← the "one transaction end-to-end" example used in the pitch video
```

### Notes on this structure
- **Top-level folders map 1:1 to the 5 modules** (`data/` = Module 1, `ml/` = Module 2, `app/` = Modules 3+4, `dashboard/` = Module 5) — this makes the repo self-explanatory even before reading code.
- **`app/routers/` split by resource**, not one giant `main.py` — signals real backend engineering practice, not a hackathon script dump.
- **`app/dunning/llm_generator.py` kept isolated** from `templates.py` — so if the LLM stretch goal doesn't get built, its absence doesn't leave a half-finished mess in the main task flow; `tasks.py` should call a single `generate_message()` function that internally decides templated-vs-LLM, so swapping is a one-line change.
- **Commit `data_dictionary.md` and `docs/architecture-diagram.png` early** — these cost little time but are exactly the kind of artifact that signals "build quality" and "problem taste" to a judge skimming quickly.
- **`.gitignore`**: exclude `model.pkl` if large, `.env`, `__pycache__`, and large CSVs if they push repo size up — but if the CSVs are under a few MB, commit them so judges can run the demo without regenerating data first.

### Suggested commit cadence (mirrors the 6-day build order in §8)
One meaningful commit per module-day, not one giant commit at the end — commit history itself is a small but real signal of how the build actually progressed, which maps to their "failure recovery" evaluation criterion (what broke, what you did about it) if your commit messages are honest about it (e.g., "fix: retry policy was double-scheduling on failed executions").

