# RiskLens AI architecture

## Current application flow

1. React renders dashboard and operational views.
2. Browser calls the FastAPI JSON endpoints under `/api`.
3. API validates inputs using Pydantic models.
4. The current demonstration scorer applies deterministic, documented heuristic rules.
5. Review decisions and policy changes are recorded in process-memory audit events.
6. Batch scoring validates and scores a bounded CSV upload.

## Current limitations

- Transaction, policy and audit state live in process memory and reset after restart.
- No authentication, authorization or multi-tenant data separation exists.
- Risk points are not probabilities and have not been calibrated.
- Demo time-series values are hard-coded visual examples, not live processor events.
- This API is not connected to a processor and must not be used to accept or reject real payments.

## Next production-oriented increments

1. Database models and migrations for transactions, reviews, policies and audit events.
2. Benchmark loader and reproducible training/evaluation scripts.
3. Train-only resampling and feature processing to avoid leakage.
4. Versioned model artifacts with a test-time score distribution and model card.
5. Authentication, role-based permissions, rate limits and secure deployment configuration.
6. Observability, retention controls and privacy-safe logging.
