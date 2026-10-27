# RiskLens AI architecture

## Current application flow

1. React + TypeScript renders the risk dashboard and operational views.
2. Browser calls the FastAPI JSON API under `/api`, attaching a short-lived bearer token.
3. FastAPI validates requests with Pydantic and resolves the active user and persisted session from the signed token.
4. Role guards authorize admin-only policy changes and admin/analyst review/audit operations.
5. Each user belongs to one workspace (tenant). API reads and writes scope transactions, policies and audit events using the tenant ID loaded from the authenticated user record.
6. Login, registration, password reset and invitation acceptance pass through rate-limit checks. Redis is used for cross-process counters in Compose/production; local development can use a process-local limiter.
7. Password reset and workspace invitation links contain random one-time tokens. Only SHA-256 token digests are stored in the database; reset tokens expire after 30 minutes and invitations after 72 hours.
8. SMTP delivers account recovery and invitation messages. Local development can log links to the API console when SMTP is not configured; production requires SMTP and an HTTPS app URL configuration.
9. SQLAlchemy persists data to SQLite locally or PostgreSQL in Docker Compose. Alembic migrations maintain the schema.
10. The interactive transaction scorer remains a deterministic demo heuristic, not a calibrated fraud model.

## Storage models

- `tenants`: workspace identity and creation timestamp.
- `users`: email, Argon2 password hash, role, active status and tenant foreign key.
- `user_sessions`: server-side session records keyed by JWT ID, expiration, revocation time and limited client metadata.
- `password_reset_tokens`: digest, user/workspace, expiry and one-time-use timestamp.
- `tenant_invitations`: digest, target email, role, inviter, expiry and acceptance timestamp.
- `transactions`: transaction attributes, score metadata, review outcome and tenant foreign key.
- `risk_policies`: one threshold policy per tenant.
- `audit_events`: reviewer actions, account creation, password reset, invitations and policy updates.
- `alembic_version`: applied schema migration revision.

Migration `0003_tenant_isolation` creates the default demo tenant and backfills pre-existing users, transactions, policies and audit events. Migration `0004_auth_lifecycle` creates session, reset-token and invitation tables. New public registrations create a separate workspace and make the first member its admin. Admin-created users and invitation recipients remain in their inviter's tenant.

## Security boundaries and limitations

- Passwords are stored as Argon2 hashes, never returned through the API. JWTs require issuer, audience, issue/expiry claims and a matching persisted session. Revoked/expired sessions fail authorization even if a signed token has not reached its original expiration.
- Password reset responses do not reveal whether an email exists. Tokens are single-use, hashed at rest, short-lived and invalidated after use. Password resets revoke the account's active sessions.
- Login, registration, recovery and invitation endpoints are rate-limited. Production requires shared TLS-protected Redis (`rediss://`); if Redis becomes unavailable, protected rate-limited operations fail closed with 503 rather than silently bypassing the limit.
- API endpoints enforce roles server-side. The frontend role-aware controls are usability features, not the security boundary.
- Tenant identifiers are taken from the authenticated user record and applied directly to transaction, policy and audit queries. Transaction detail and review routes return not found for IDs outside the caller's workspace.
- Access tokens are held in browser local storage for this MVP, which remains exposed to successful same-origin script injection. Production deployment needs a reviewed CSP, HTTPS-only ingress, dependency review and appropriate browser-security controls.
- Local-process rate limiting is for development only and is not shared among multiple workers. Production requires a shared Redis URL using `rediss://`.
- SMTP credentials and Redis connections must be secured; production must use a verified HTTPS public app URL for recovery/invitation links.
- Audit rows are durable, but are not cryptographically tamper-evident against a database administrator.
- The demo heuristic is not calibrated and does not connect to a payment processor.
- The public benchmark model uses an anonymized feature schema and is not directly wired to the UI's merchant-style input features.
- The app still needs deployment-specific security review before handling real customer data.

## Next production-oriented increments

1. Add email verification, password reset abuse monitoring, configurable session expiration policy and session cleanup.
2. Add tenant member listings, invitation cancellation/resend and account deactivation.
3. Add email delivery health checks, metrics, tracing and audit retention controls.
4. Design a merchant-specific feature adapter before using any trained model for live inference.
5. Add model registry/version rollout, drift monitoring and threshold approval workflows.
