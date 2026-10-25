# RiskLens AI architecture

## Current application flow

1. React + TypeScript renders the risk dashboard and operational views.
2. Browser calls the FastAPI JSON API under `/api`.
3. FastAPI validates requests with Pydantic models.
4. Transaction records, risk thresholds, analyst decisions and audit events are stored through SQLAlchemy.
5. Local development defaults to persistent SQLite (`risklens.db`); Docker Compose uses PostgreSQL with a named volume.
6. The interactive transaction scorer remains a deterministic demo heuristic.
7. An optional offline scikit-learn benchmark pipeline trains on a public CSV and writes a held-out evaluation JSON report. When present, the API serves that report to the evaluation page.

## Storage models

- `transactions`: transaction attributes, score metadata and review outcome.
- `risk_policies`: persisted low-risk and review thresholds.
- `audit_events`: reviewer actions and policy updates with JSON details and timestamps.

The current MVP creates missing tables on application startup. It does not yet use versioned Alembic migrations; schema migration management is a production-hardening item.

## Boundaries and limitations

- No authentication, authorization or multi-tenant separation exists.
- API audit rows are durable, but not tamper-evident against a database administrator.
- The demo heuristic is not calibrated and does not connect to a payment processor.
- The public benchmark model uses an anonymized feature schema and is not directly wired to the UI's merchant-style input features.
- Hard-coded sample time-series values are visual examples, not actual processor traffic.

## Next production-oriented increments

1. Add Alembic migrations and schema compatibility checks.
2. Add authentication, role-based permissions, rate limits and deployment secrets.
3. Design a merchant-specific feature adapter before using any trained model for live inference.
4. Add model registry/version rollout, drift monitoring and threshold approvals.
5. Add observability, retention controls, privacy-safe logs and a deployment runbook.
