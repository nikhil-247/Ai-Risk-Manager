from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.database import Base


class UserRecord(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'analyst', 'viewer')", name="ck_users_role"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="viewer")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class TransactionRecord(Base):
    __tablename__ = "transactions"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    country: Mapped[str] = mapped_column(String(2), default="US", nullable=False)
    risk_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    risk_category: Mapped[str] = mapped_column(String(12), default="low", nullable=False)
    recommended_action: Mapped[str] = mapped_column(String(40), default="manual_review", nullable=False)
    reasons: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    score_type: Mapped[str] = mapped_column(String(40), default="heuristic_demo_score", nullable=False)
    disclaimer: Mapped[str] = mapped_column(Text, default="", nullable=False)
    review_status: Mapped[str] = mapped_column(String(24), default="needs_review", nullable=False)
    review_note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    reviewer: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cross_border: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    transactions_last_hour: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    account_age_days: Mapped[int] = mapped_column(Integer, default=365, nullable=False)
    hour_of_day: Mapped[int] = mapped_column(Integer, default=12, nullable=False)
    demo_label: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    def as_dict(self) -> dict[str, Any]:
        created = self.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=__import__("datetime").timezone.utc)
        return {
            "id": self.id,
            "amount": self.amount,
            "currency": self.currency,
            "country": self.country,
            "risk_score": self.risk_score,
            "risk_category": self.risk_category,
            "recommended_action": self.recommended_action,
            "reasons": self.reasons or [],
            "score_type": self.score_type,
            "disclaimer": self.disclaimer,
            "review_status": self.review_status,
            "review_note": self.review_note,
            "reviewer": self.reviewer,
            "created_at": created.isoformat(),
            "cross_border": self.cross_border,
            "transactions_last_hour": self.transactions_last_hour,
            "account_age_days": self.account_age_days,
            "hour_of_day": self.hour_of_day,
            "demo_label": self.demo_label,
        }


class RiskPolicyRecord(Base):
    __tablename__ = "risk_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    low_max: Mapped[int] = mapped_column(Integer, nullable=False, default=29)
    review_max: Mapped[int] = mapped_column(Integer, nullable=False, default=64)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    transaction_id: Mapped[str] = mapped_column(String(80), nullable=False)
    actor: Mapped[str] = mapped_column(String(100), nullable=False)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
