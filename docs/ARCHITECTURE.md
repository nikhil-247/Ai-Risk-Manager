# RiskLens AI architecture

## Current application flow

1. React + TypeScript renders the risk dashboard and operational views.
2. Browser calls the FastAPI JSON API under `/api`, attaching a short-lived bearer token.
3. FastAPI validates requests with Pydantic and resolves the active user from the signed token.
4. Role guards authorize admin-only policy changes and admin/analyst review/audit operations.
5. Each user belongs to one workspace (tenant). API reads and writes scope transactions, policies and audit events using the tenant ID loaded from the authenticated user record; clients cannot supply a tenant ID to select their data scope.
6. SQLAlchemy persists data to SQLite locally or PostgreSQL in Docker Compose. Alembic migrations maintain the schema.
7. The interactive transaction scorer remains a deterministic demo heuristic, not a calibrated fraud model.
8. An optional offline scikit-learn benchmark pipeline trains on a public CSV and writes a held-out evaluation JSON report. When present, the API serves that report to the evaluation page.

## Storage models

- `tenants`: workspace identity and creation timestamp.
- `users`: email, Argon2 password hash, role, active status and tenant foreign key.
- `transactions`: transaction attributes, score metadata, review outcome and tenant foreign key.
- `risk_policies`: one threshold policy per tenant.
- `audit_events`: reviewer actions, policy updates and user creation with a tenant foreign key.
- `alembic_version`: applied schema migration revision.

Migration `0003_tenant_isolation` creates the default demo tenant and backfills existing users, transactions, policies and audit events to it. New public registrations create a separate workspace and make the first member its admin. Admin-created users stay inside their creator's workspace.

## Security boundaries and limitations

- Passwords are stored as Argon2 hashes, never returned through the API. JWT access tokens expire; production startup refuses a missing or built-in development signing secret.
- API endpoints enforce roles server-side. The frontend role-aware controls are usability features, not the security boundary.
- Tenant identifiers are taken from the authenticated user record and applied directly to transaction, policy and audit queries. Transaction detail and review routes return not found for IDs outside the caller's workspace.
- Session tokens are stored in browser local storage; this is convenient for the MVP but remains exposed to successful same-origin script injection. Production deployment should add a reviewed CSP, HTTPS-only ingress, upstream rate limits, email verification and account recovery.
- Audit rows are durable, but are not cryptographically tamper-evident against a database administrator.
- The demo heuristic is not calibrated and does not connect to a payment processor.
- The public benchmark model uses an anonymized feature schema and is not directly wired to the UI's merchant-style input features.
- The app still needs deployment-specific security review before handling real customer data.

## Next production-oriented increments

1. Add tenant invitations, admin user listing/deactivation, password reset and optional email verification.
2. Add distributed login/registration rate limits, monitoring, structured security logging and session revocation.
3. Design a merchant-specific feature adapter before using any trained model for live inference.
4. Add model registry/version rollout, drift monitoring and threshold approval workflows.
5. Add retention controls, privacy-safe logs and a deployment runbook.
