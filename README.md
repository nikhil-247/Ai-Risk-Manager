# RiskLens AI

**Explainable Fraud Intelligence & Risk Management Platform**

RiskLens AI is a full-stack decision-support platform for transaction risk analysis. It combines a React dashboard, a FastAPI service, auditable review workflows, configurable risk policies, batch CSV scoring, and reproducible ML evaluation utilities.

> **Project status:** early-stage MVP foundation. Demo transaction records and heuristic scoring are for product demonstrations only. They are not a trained fraud model and must not be presented as benchmark performance or used to make real payment decisions.

## Why RiskLens AI?

Fraud operations have to balance two costly errors: missing fraudulent transactions and flagging legitimate customers. RiskLens is designed to make that trade-off visible and reviewable rather than hiding it behind a single accuracy number.

### Current MVP capabilities

- Dashboard with transaction, amount, risk and review metrics.
- Transaction list with text search and risk/status filtering.
- Transaction detail view with an explainable rule-based demo score.
- Human review actions: mark a case as confirmed fraud, legitimate, or still under review.
- Configurable risk thresholds through the API.
- CSV batch scoring with input validation and downloadable results from the UI.
- Evaluation metrics endpoint using clearly labelled synthetic demonstration labels.
- FastAPI OpenAPI documentation and backend tests.
- Docker Compose setup for local development.
- GitHub Actions workflow for automated backend checks.

### Planned next milestones

- Train and evaluate models using a real public benchmark with a leakage-safe split.
- Persist transactions, decisions and audit events in PostgreSQL.
- Add model versioning, calibrated probability estimates and richer feature attribution.
- Add authentication, role-based access and production deployment hardening.
- Add optional LLM-generated investigation summaries with grounded evidence.

Features are moved from planned to implemented only after the corresponding code and tests exist.

## Architecture

```text
React + TypeScript + Vite
        │ HTTP / JSON
        ▼
FastAPI application
  ├── Transaction API
  ├── Rule-based demo risk scoring
  ├── Review / decision workflow
  ├── Policy thresholds
  └── Evaluation and CSV batch scoring
        │
        └── In-memory demo store (resets on restart)
```

The current foundation intentionally uses a lightweight in-memory store so it can run without paid services or API keys. It is a development/demo setup, not a multi-user production database.

## Quick start

### Requirements

- Python 3.11 or newer
- Node.js 20 or newer and npm
- Git
- Optional: Docker Desktop with Docker Compose

### 1. Clone the repository

```bash
git clone https://github.com/nikhil-247/Ai-Risk-Manager.git
cd Ai-Risk-Manager
```

### 2. Start the API

Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r backend/requirements.txt
uvicorn backend.app.main:app --reload --port 8000
```

macOS / Linux:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r backend/requirements.txt
uvicorn backend.app.main:app --reload --port 8000
```

The API will be available at http://localhost:8000 and interactive API docs at http://localhost:8000/docs.

### 3. Start the frontend

Open a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open the Vite URL shown in the terminal (usually http://localhost:5173). The frontend proxies `/api` requests to the backend.

### Run with Docker

```bash
docker compose up --build
```

- Frontend: http://localhost:5173
- API: http://localhost:8000
- API docs: http://localhost:8000/docs

## API overview

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/health` | Service health |
| GET | `/api/summary` | Dashboard summary |
| GET | `/api/transactions` | Searchable/filterable transactions |
| GET | `/api/transactions/{id}` | Transaction details |
| POST | `/api/transactions/score` | Score one transaction |
| POST | `/api/transactions/batch` | Validate and score CSV-uploaded rows |
| POST | `/api/reviews/{id}` | Record a review decision |
| GET | `/api/policies` | Read risk policy |
| PUT | `/api/policies` | Update demo risk thresholds |
| GET | `/api/evaluation` | Demonstration evaluation metrics |

See the generated OpenAPI schema at `/openapi.json` or use Swagger UI at `/docs`.

## Risk scoring and interpretation

The initial scoring engine is a transparent **demonstration heuristic**, not a trained classifier. It assigns risk points based on amount, transaction velocity proxy, unusual hour and cross-border flag where such input fields are provided. Reasons are returned alongside the score. The rules and thresholds are examples and are not calibrated to any specific merchant.

The UI and API deliberately call these values a *risk score*, not a validated probability of fraud. Do not connect the current demo rules to a payment processor or automatically decline real transactions.

## Evaluation integrity

Synthetic demo records allow a reviewer to explore the interface offline. Metrics computed from these records are examples for exercising the evaluation screen only. They do not establish real-world model quality.

For credible model reporting, use a documented public benchmark, maintain a separate held-out test set, prevent leakage, report class prevalence and confusion-matrix counts, and prioritize precision, recall and PR-AUC over accuracy alone. Quantify false-positive cost only when the underlying cost assumptions are stated.

## Configuration

The initial MVP requires no API key. Optional integrations should use environment variables and a local `.env` file. Never commit credentials, access tokens, customer data or raw financial records. The repository's `.gitignore` excludes common environment and Python artifact files.

## Development checks

Backend tests:

```bash
pip install -r backend/requirements.txt
pytest -q
```

Frontend production build:

```bash
cd frontend
npm ci
npm run build
```

## Security and privacy notes

- Use only synthetic or appropriately anonymized data for development.
- The current MVP has no authentication and stores state in process memory; do not expose it as a production service.
- Treat uploaded CSV content as untrusted input. The API validates expected columns and limits upload size.
- Risk decisions should remain auditable and subject to human review.
- Never use generated explanations as proof of fraud; they summarize the scoring rules that fired.

## Contributing

1. Create a feature branch.
2. Make a focused change and add or update tests.
3. Run backend tests and the frontend production build.
4. Document limitations and any new environment variables.
5. Open a pull request describing the change and its verification.

## License

No license has been added yet. Until a license is chosen, default copyright rules apply and reuse is not automatically granted.

---

Built as a fintech risk-management engineering project, with a focus on explainability, evaluation integrity and reviewable decisions.
