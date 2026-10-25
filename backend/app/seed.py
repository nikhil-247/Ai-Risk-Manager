from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import RiskPolicyRecord, TransactionRecord
from backend.app.risk_scoring import ScoreRequest, score_features


DEMO_ROWS = [
    ("txn_1001", 42.50, "US", 1, 420, 14, False, "legitimate", "2026-10-25T10:05:00+00:00"),
    ("txn_1002", 2490.00, "GB", 9, 3, 2, True, "confirmed_fraud", "2026-10-25T10:04:00+00:00"),
    ("txn_1003", 810.25, "IN", 5, 22, 11, True, "needs_review", "2026-10-25T10:02:00+00:00"),
    ("txn_1004", 128.99, "US", 2, 140, 9, False, "legitimate", "2026-10-25T09:59:00+00:00"),
    ("txn_1005", 5400.00, "SG", 11, 1, 3, True, "confirmed_fraud", "2026-10-25T09:57:00+00:00"),
    ("txn_1006", 975.00, "IN", 3, 300, 17, False, "legitimate", "2026-10-25T09:54:00+00:00"),
    ("txn_1007", 68.20, "US", 8, 5, 1, False, "needs_review", "2026-10-25T09:50:00+00:00"),
    ("txn_1008", 1870.00, "CA", 6, 15, 23, True, "confirmed_fraud", "2026-10-25T09:48:00+00:00"),
    ("txn_1009", 24.99, "DE", 1, 800, 13, False, "legitimate", "2026-10-25T09:44:00+00:00"),
    ("txn_1010", 1290.00, "AU", 4, 60, 4, True, "needs_review", "2026-10-25T09:40:00+00:00"),
    ("txn_1011", 6100.00, "US", 10, 2, 0, False, "confirmed_fraud", "2026-10-25T09:38:00+00:00"),
    ("txn_1012", 320.00, "IN", 2, 160, 19, False, "legitimate", "2026-10-25T09:35:00+00:00"),
]


def seed_demo_data(db: Session) -> None:
    if db.scalar(select(RiskPolicyRecord).where(RiskPolicyRecord.id == 1)) is None:
        db.add(RiskPolicyRecord(id=1, low_max=29, review_max=64))
    if db.scalar(select(TransactionRecord.id).limit(1)) is not None:
        db.commit()
        return

    policy = db.get(RiskPolicyRecord, 1)
    low_max, review_max = (policy.low_max, policy.review_max) if policy else (29, 64)
    for identifier, amount, country, velocity, age, hour, cross_border, decision, created in DEMO_ROWS:
        payload = ScoreRequest(
            amount=amount,
            country=country,
            transactions_last_hour=velocity,
            account_age_days=age,
            hour_of_day=hour,
            cross_border=cross_border,
        )
        scored = score_features(payload, low_max, review_max)
        db.add(TransactionRecord(
            id=identifier,
            amount=amount,
            currency="USD",
            country=country,
            **scored,
            review_status=decision,
            review_note="",
            reviewer=None,
            created_at=datetime.fromisoformat(created).astimezone(timezone.utc),
            cross_border=cross_border,
            transactions_last_hour=velocity,
            account_age_days=age,
            hour_of_day=hour,
            demo_label=1 if decision == "confirmed_fraud" else 0,
        ))
    db.commit()
