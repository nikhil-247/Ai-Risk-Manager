# RiskLens AI

**Explainable Fraud Intelligence & Risk Management Platform**

RiskLens AI is a full-stack transaction-risk decision-support application with a React dashboard, FastAPI endpoints, SQLAlchemy persistence, human review workflows, configurable risk policies, CSV batch scoring, audit events and an offline ML benchmark pipeline.

> **Status:** active MVP. The dashboard's interactive custom scorer is a transparent demo heuristic, not a trained classifier. A separate public-benchmark training script is provided and generates a report only after you supply and evaluate the dataset. Do not use this project to approve or decline real payments.

## Capabilities

### Working application foundation
- Risk dashboard with transaction counts, risk buckets, flagged amount and review status.
- Search and filter transaction records.
- Transaction detail drawer with score reasons and signal attributes.
- Record fraud, legitimate or review-pending decisions, with reviewer notes.
- Risk threshold configuration persisted to the configured database.
- CSV batch scoring with validation and downloadable output.
- Audit trail for review actions and policy updates.
- FastAPI OpenAPI / Swagger documentation.
- Argon2 password hashing, expiring JWT access tokens, and server-enforced admin/analyst/viewer roles.
- Workspace (tenant) isolation for transactions, risk policies, and audit events, with a tenant ID derived from the authenticated user.
- SQLite for local development; PostgreSQL in Docker Compose.
- GitHub Actions jobs for backend/ML tests and frontend production compilation.

### Benchmark ML pipeline
- Validates the public credit-card fraud CSV schema and numeric features.
- Defaults to chronological train/validation/test partitions (60/20/20).
- Fits preprocessing on training data only and uses class-weighted Random Forest.
- Selects a decision threshold on validation data using explicit false-positive / false-negative cost assumptions.
- Reports held-out precision, recall, F1, accuracy, PR-AUC (average precision), ROC-AUC, confusion matrix, baseline metrics, data hash and split counts.
- Saves a model artifact and JSON report locally; generated files are intentionally not committed.

The online transaction form continues to use the labelled heuristic demo scorer because the public benchmark's anonymized features are not equivalent to the dashboard's merchant-style fields. Do not represent the offline benchmark as live inference.

## Stack

| Layer | Technology |
|---|---|
| Frontend | React, TypeScript, Vite, Recharts, Lucide |
| API | FastAPI, Pydantic |
| Persistence | SQLAlchemy, SQLite locally, PostgreSQL via Docker |
| ML evaluation | Python, pandas, NumPy, scikit-learn, joblib |
| Quality | Pytest, GitHub Actions |
| Local deployment | Docker Compose |

## Architecture

```text
React + TypeScript
        │ /api JSON
        ▼
FastAPI ────────────── SQLAlchemy ───────── SQLite (local)
  ├─ Transactions                         PostgreSQL (Compose)
  ├─ Reviews / audit
  ├─ Risk policy
  ├─ CSV batch scorer
  └─ Evaluation report ◄──── artifacts/benchmark_report.json
                                      ▲
CSV benchmark ── train_benchmark.py ──┴── fraud_pipeline.joblib
```

## Quick start: local development

Requirements: Python 3.11+, Node.js 20+, npm and Git.

### 1. Clone

```bash
git clone https://github.com/nikhil-247/Ai-Risk-Manager.git
cd Ai-Risk-Manager
```

### 2. Run the API (Windows PowerShell)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r backend/requirements.txt
$env:RISKLENS_JWT_SECRET = [Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(48))
$env:RISKLENS_BOOTSTRAP_ADMIN_EMAIL = "admin@example.com"
$env:RISKLENS_BOOTSTRAP_ADMIN_PASSWORD = "replace-with-a-strong-password"
alembic -c backend/alembic.ini upgrade head
uvicorn backend.app.main:app --reload --port 8000
```

macOS/Linux:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r backend/requirements.txt
export RISKLENS_JWT_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export RISKLENS_BOOTSTRAP_ADMIN_EMAIL="admin@example.com"
export RISKLENS_BOOTSTRAP_ADMIN_PASSWORD="replace-with-a-strong-password"
alembic -c backend/alembic.ini upgrade head
uvicorn backend.app.main:app --reload --port 8000
```

The local default is SQLite. Transactions, policies and audit events persist in `risklens.db` across restarts.

### 3. Run the frontend

Open a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The Vite dev server proxies `/api` calls to the local API on port 8000.

### 4. Run all backend and ML checks

```bash
pip install -r backend/requirements.txt -r ml/requirements.txt
pytest -q
```

Frontend production compile:

```bash
cd frontend
npm install
npm run build
```

## Docker Compose (PostgreSQL + API + frontend)

```bash
docker compose up --build
```

- Dashboard: http://localhost:5173
- API: http://localhost:8000
- Swagger docs: http://localhost:8000/docs
- Health check: http://localhost:8000/api/health

Compose now refuses to start unless explicit database and JWT secrets are set.

1. Copy `.env.example` to `.env`.
2. Fill `POSTGRES_PASSWORD` and `RISKLENS_JWT_SECRET` with different, long URL-safe random values. You can generate one with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
3. Set `RISKLENS_BOOTSTRAP_ADMIN_EMAIL` and a unique `RISKLENS_BOOTSTRAP_ADMIN_PASSWORD` of at least 12 characters.
4. Run `docker compose up --build`.

The bootstrap admin is placed in the default `Northstar Payments` demo workspace, which contains the seeded sample transactions. The bootstrap email must not already belong to a different workspace or a non-admin/disabled account; the application never silently promotes an existing user. Public registration creates a new isolated workspace and makes its first member that workspace's admin. Admins can provision analyst/admin/viewer accounts inside their own workspace through `POST /api/auth/admin/users`. For deployment, set `RISKLENS_ENV=production`, use HTTPS, and set `RISKLENS_CORS_ORIGINS` to the exact comma-separated frontend origins. This MVP still needs a deployment-specific security review before handling real customer data.

## Public benchmark setup

The raw benchmark is not stored in Git. Obtain the public ULB/Kaggle Credit Card Fraud Detection dataset from its publisher/host after reviewing applicable terms. Place the CSV at:

```text
data/raw/creditcard.csv
```

Then install the ML requirements and run:

```bash
pip install -r ml/requirements.txt
python -m ml.train_benchmark --data data/raw/creditcard.csv
```

Optional arguments:

```bash
python -m ml.train_benchmark --data data/raw/creditcard.csv --trees 30
python -m ml.train_benchmark --data data/raw/creditcard.csv --split stratified
python -m ml.train_benchmark --data data/raw/creditcard.csv --false-positive-cost 5 --false-negative-cost 100
```

Outputs:
- `artifacts/fraud_pipeline.joblib`: trained pipeline, features and selected threshold.
- `artifacts/benchmark_report.json`: held-out metrics consumed by `GET /api/evaluation` when present.

For Docker, keep `artifacts/` available next to `docker-compose.yml`; Compose mounts this directory read-only into the API. Generated artifacts and raw rows are excluded from Git by design.

### Split and metric choices

The default temporal split sorts by `Time`: first 60% for training, next 20% for threshold selection, final 20% as a held-out test. Use `--split stratified` for a conventional stratified comparison; temporal partitioning can fail if a partition lacks one class. Preprocessing is fit only on training data. The final threshold is chosen from validation data using explicit cost assumptions, and final test labels are not used for threshold selection.

Cost values are illustrative user-provided units until a merchant supplies approved assumptions. Read [docs/EVALUATION.md](docs/EVALUATION.md) before making metric claims.

## API reference

| Method | Endpoint | Function |
|---|---|---|
| GET | `/api/health` | API and database readiness |
| POST | `/api/auth/register` | Create a new isolated workspace and its first admin |
| POST | `/api/auth/login` | Get an expiring bearer access token (OAuth2 form: username=email) |
| GET | `/api/auth/me` | Current user and role |
| POST | `/api/auth/admin/users` | Admin-only account provisioning with explicit role |
| GET | `/api/summary` | Authenticated dashboard summary |
| GET | `/api/transactions` | Search/filter transactions |
| GET | `/api/transactions/{id}` | Transaction detail |
| POST | `/api/transactions/score` | Transparent demo score |
| POST | `/api/transactions/batch` | Validate and score CSV rows |
| POST | `/api/reviews/{id}` | Analyst/admin only: save a human review decision |
| GET / PUT | `/api/policies` | Read authenticated; admin-only updates |
| GET | `/api/audit` | View persisted audit events |
| GET | `/api/evaluation` | Benchmark report if generated, otherwise demo disclaimer |

## Security and data honesty

- API authentication uses Argon2 password hashes and expiring HS256 bearer tokens. `RISKLENS_ENV=production` refuses missing or built-in development JWT secrets. Docker Compose also requires explicit PostgreSQL and JWT secrets.
- Public registration creates a new isolated workspace with the registering user as its admin. The configured bootstrap admin belongs to the default demo workspace. Admins can provision analyst/viewer/admin accounts within their own workspace through the protected admin endpoint.
- Dashboard data endpoints require authentication. Analysts and admins can submit review decisions and read audit logs; only admins can change policies or provision users. Account creation is written to the audit trail, and reviewer identity comes from the authenticated account. These are API-enforced permissions, not just hidden UI controls.
- CSV batch uploads are read with a 2 MB bound before parsing, and exported cell values are neutralized against spreadsheet-formula injection.
- Login responses are marked `Cache-Control: no-store`; the frontend clears local session state when an API request returns an unauthorized response.
- Set `RISKLENS_CORS_ORIGINS` to exact trusted origins when hosting the frontend outside localhost. CORS is not a replacement for authentication or network-level controls.
- Tenant IDs are attached to users, transactions, risk policies, and audit events. The API derives the tenant scope from the signed-in user, and the migration assigns pre-existing rows to the default demo workspace. Regression tests cover attempts to access another tenant's transaction and policy data.
- Use synthetic or approved anonymized data only.
- Local Docker default credentials are not production secrets.
- Audit events persist, but are not cryptographically tamper-evident.
- Heuristic points are not calibrated probabilities and never trigger real payment actions.
- The public benchmark's anonymized features do not support the merchant-style online form without a separate, validated feature adapter.
- Raw dataset, SQLite database, model artifacts and `.env` are ignored by Git.

## Roadmap

1. Alembic migrations now manage schema changes; keep migrations versioned and reviewed.
2. Tenant isolation and cross-tenant regression tests are implemented; add invitations, tenant administration, and account lifecycle controls next.
3. Validate a merchant-like model feature schema and integrate inference only after testing.
4. Add model versioning, threshold approvals, drift detection and alerting.
5. Deploy with secrets management, observability, rate limits and security review.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/EVALUATION.md](docs/EVALUATION.md).

## License

No license has been added yet, so default copyright rules apply and reuse is not automatically granted.
