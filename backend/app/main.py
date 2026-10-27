from __future__ import annotations

import csv
import io
import json
import os
import hashlib
import logging
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import desc, func, select, update
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from backend.app.auth import (
    ACCESS_TOKEN_MINUTES, bootstrap_admin, create_access_token, get_current_session,
    get_current_user, hash_password, normalize_email, require_roles, verify_password,
)
from backend.app.database import get_db
from backend.app.models import (
    AuditEvent, PasswordResetTokenRecord, RiskPolicyRecord, TenantInvitationRecord,
    TenantRecord, TransactionRecord, UserRecord, UserSessionRecord,
)
from backend.app.risk_scoring import ScoreRequest, score_features
from backend.app.seed import seed_demo_data
from backend.app.messaging import create_action_url, send_security_email
from backend.app.security_controls import enforce_rate_limit


@asynccontextmanager
async def lifespan(_: FastAPI):
    from backend.app.database import SessionLocal
    with SessionLocal() as db:
        bootstrap_admin(db)
        seed_demo_data(db)
    yield


logger = logging.getLogger("risklens.auth")

app = FastAPI(
    title="RiskLens AI API",
    description="Explainable transaction-risk API. The demo rules are not production fraud predictions.",
    version="0.2.0",
    lifespan=lifespan,
)

CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "RISKLENS_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["Content-Type"],
)


class RegisterRequest(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=12, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_and_validate_email(cls, value: str) -> str:
        normalized = normalize_email(value)
        if normalized.count("@") != 1 or any(ch.isspace() for ch in normalized):
            raise ValueError("A valid email address is required")
        local, domain = normalized.rsplit("@", 1)
        if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
            raise ValueError("A valid email address is required")
        return normalized


class AdminUserCreate(RegisterRequest):
    role: Literal["admin", "analyst", "viewer"] = "viewer"


class EmailRequest(BaseModel):
    email: str = Field(min_length=5, max_length=320)

    @field_validator("email")
    @classmethod
    def normalize_and_validate_email(cls, value: str) -> str:
        normalized = normalize_email(value)
        if normalized.count("@") != 1 or any(ch.isspace() for ch in normalized):
            raise ValueError("A valid email address is required")
        local, domain = normalized.rsplit("@", 1)
        if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
            raise ValueError("A valid email address is required")
        return normalized


class PasswordResetConfirm(BaseModel):
    token: str = Field(min_length=32, max_length=256)
    new_password: str = Field(min_length=12, max_length=128)


class InvitationCreate(EmailRequest):
    role: Literal["admin", "analyst", "viewer"] = "viewer"


class InvitationAccept(BaseModel):
    token: str = Field(min_length=32, max_length=256)
    password: str = Field(min_length=12, max_length=128)


class ReviewRequest(BaseModel):
    decision: Literal["confirmed_fraud", "legitimate", "needs_review"]
    note: str = Field(default="", max_length=1000)


class PolicyUpdate(BaseModel):
    low_max: int = Field(ge=0, le=98)
    review_max: int = Field(ge=1, le=100)

    @field_validator("review_max")
    @classmethod
    def review_threshold_valid(cls, value: int, info):
        low = info.data.get("low_max")
        if low is not None and value <= low:
            raise ValueError("review_max must be greater than low_max")
        return value


def policy_for(db: Session, tenant_id: str) -> RiskPolicyRecord:
    policy = db.scalar(
        select(RiskPolicyRecord).where(RiskPolicyRecord.tenant_id == tenant_id)
    )
    if policy is None:
        policy = RiskPolicyRecord(tenant_id=tenant_id, low_max=29, review_max=64)
        db.add(policy)
        db.flush()
    return policy


def add_audit(
    db: Session,
    tenant_id: str,
    event_type: str,
    transaction_id: str,
    actor: str,
    details: dict,
) -> AuditEvent:
    event = AuditEvent(
        id=str(uuid4()),
        tenant_id=tenant_id,
        event_type=event_type,
        transaction_id=transaction_id,
        actor=actor,
        details=details,
        timestamp=datetime.now(timezone.utc),
    )
    db.add(event)
    return event


def transaction_count(db: Session) -> int:
    return int(db.scalar(select(func.count()).select_from(TransactionRecord)) or 0)


def _public_user(user: UserRecord, db: Session) -> dict:
    tenant = db.get(TenantRecord, user.tenant_id)
    return {
        "id": user.id,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "tenant_name": tenant.name if tenant else "Workspace",
        "created_at": user.created_at.isoformat(),
    }


def _create_user(
    db: Session,
    email: str,
    password: str,
    tenant_id: str,
    role: str = "viewer",
    created_by: str | None = None,
) -> UserRecord:
    user = UserRecord(
        id=str(uuid4()),
        tenant_id=tenant_id,
        email=normalize_email(email),
        password_hash=hash_password(password),
        role=role,
        is_active=True,
    )
    db.add(user)
    add_audit(
        db,
        user.tenant_id,
        "user_created",
        f"user:{user.id}",
        created_by or user.email,
        {
            "user_id": user.id,
            "email": user.email,
            "role": user.role,
            "provisioned_by": created_by or "self_registration",
        },
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists") from None
    db.refresh(user)
    return user


@app.post("/api/auth/register", status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    """Create a new isolated workspace whose first member is its administrator."""
    enforce_rate_limit(request, "register", 5, 3600, identities=[payload.email])
    local_part = payload.email.split("@", 1)[0][:100]
    tenant = TenantRecord(id=str(uuid4()), name=f"{local_part}'s workspace")
    db.add(tenant)
    db.flush()
    user = _create_user(
        db, payload.email, payload.password, tenant_id=tenant.id, role="admin"
    )
    return _public_user(user, db)


@app.post("/api/auth/login")
def login(
    request: Request,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    email = normalize_email(form_data.username)
    enforce_rate_limit(request, "login", 12, 900, identities=[email])
    user = db.scalar(select(UserRecord).where(UserRecord.email == email))
    if user is None or not user.is_active or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={
                "WWW-Authenticate": "Bearer",
                "Cache-Control": "no-store",
                "Pragma": "no-cache",
            },
        )
    token = create_access_token(
        user.id,
        db,
        user.tenant_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_MINUTES * 60,
        "user": _public_user(user, db),
    }


@app.post("/api/auth/logout")
def logout(
    current_session: UserSessionRecord = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    current_session.revoked_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "signed_out"}


@app.post("/api/auth/logout-all")
def logout_all(
    current_user: UserRecord = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    result = db.execute(
        update(UserSessionRecord)
        .where(
            UserSessionRecord.user_id == current_user.id,
            UserSessionRecord.revoked_at.is_(None),
            UserSessionRecord.expires_at > now,
        )
        .values(revoked_at=now)
    )
    db.commit()
    return {"status": "signed_out_all", "revoked_sessions": result.rowcount or 0}


@app.get("/api/auth/sessions")
def list_sessions(
    current_user: UserRecord = Depends(get_current_user),
    current_session: UserSessionRecord = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    rows = db.scalars(
        select(UserSessionRecord)
        .where(
            UserSessionRecord.user_id == current_user.id,
            UserSessionRecord.revoked_at.is_(None),
            UserSessionRecord.expires_at > now,
        )
        .order_by(UserSessionRecord.created_at.desc())
    ).all()
    return {"items": [
        {
            "id": row.id,
            "current": row.id == current_session.id,
            "created_at": row.created_at.isoformat(),
            "expires_at": row.expires_at.isoformat(),
            "ip_address": row.ip_address,
            "user_agent": row.user_agent,
        }
        for row in rows
    ]}


@app.post("/api/auth/sessions/{session_id}/revoke")
def revoke_session(
    session_id: str,
    current_user: UserRecord = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = db.scalar(select(UserSessionRecord).where(
        UserSessionRecord.id == session_id,
        UserSessionRecord.user_id == current_user.id,
        UserSessionRecord.tenant_id == current_user.tenant_id,
    ))
    if session is None or session.revoked_at is not None:
        raise HTTPException(status_code=404, detail="Session not found")
    session.revoked_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "session_revoked"}


@app.get("/api/auth/me")
def who_am_i(current_user: UserRecord = Depends(get_current_user), db: Session = Depends(get_db)):
    return _public_user(current_user, db)


@app.post("/api/auth/admin/users", status_code=status.HTTP_201_CREATED)
def create_user_as_admin(
    payload: AdminUserCreate,
    current_user: UserRecord = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    user = _create_user(
        db, payload.email, payload.password,
        tenant_id=current_user.tenant_id,
        role=payload.role,
        created_by=current_user.email,
    )
    return _public_user(user, db)


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    # A database roundtrip makes this useful as a container readiness probe.
    db.execute(select(1))
    return {"status": "ok", "service": "risklens-ai-api", "version": app.version, "database": "reachable"}


@app.get("/api/summary")
def summary(current_user: UserRecord = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = list(db.scalars(
        select(TransactionRecord).where(TransactionRecord.tenant_id == current_user.tenant_id)
    ).all())
    total = len(rows)
    return {
        "total_transactions": total,
        "total_amount": round(sum(row.amount for row in rows), 2),
        "high_risk_count": sum(row.risk_category == "high" for row in rows),
        "pending_reviews": sum(row.review_status == "needs_review" for row in rows),
        "confirmed_fraud_count": sum(row.review_status == "confirmed_fraud" for row in rows),
        "low_risk_count": sum(row.risk_category == "low" for row in rows),
        "medium_risk_count": sum(row.risk_category == "medium" for row in rows),
        "high_risk_amount": round(sum(row.amount for row in rows if row.risk_category == "high"), 2),
        "data_mode": "synthetic_demo" if any(row.id.startswith("txn_") for row in rows) else "database",
    }


@app.get("/api/transactions")
def transactions(
    search: str = Query(default="", max_length=100),
    risk: Literal["all", "low", "medium", "high"] = "all",
    status: Literal["all", "legitimate", "confirmed_fraud", "needs_review"] = "all",
    limit: int = Query(default=100, ge=1, le=500),
    current_user: UserRecord = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = select(TransactionRecord).where(TransactionRecord.tenant_id == current_user.tenant_id)
    if search:
        needle = f"%{search.strip()}%"
        from sqlalchemy import or_
        query = query.where(or_(TransactionRecord.id.ilike(needle), TransactionRecord.country.ilike(needle)))
    if risk != "all":
        query = query.where(TransactionRecord.risk_category == risk)
    if status != "all":
        query = query.where(TransactionRecord.review_status == status)
    total = int(db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    rows = db.scalars(query.order_by(desc(TransactionRecord.created_at)).limit(limit)).all()
    return {"items": [row.as_dict() for row in rows], "total": total, "data_mode": "database_backed"}


@app.get("/api/transactions/{transaction_id}")
def transaction_detail(transaction_id: str, current_user: UserRecord = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.scalar(select(TransactionRecord).where(
        TransactionRecord.id == transaction_id,
        TransactionRecord.tenant_id == current_user.tenant_id,
    ))
    if row is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return row.as_dict()


@app.post("/api/transactions/score")
def score_one(payload: ScoreRequest, current_user: UserRecord = Depends(get_current_user), db: Session = Depends(get_db)):
    policy = policy_for(db, current_user.tenant_id)
    return score_features(payload, policy.low_max, policy.review_max)


@app.post("/api/transactions/batch")
async def score_batch(file: UploadFile = File(...), current_user: UserRecord = Depends(get_current_user), db: Session = Depends(get_db)):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Upload a .csv file")
    raw = await file.read(2_000_001)
    if len(raw) > 2_000_000:
        raise HTTPException(status_code=413, detail="CSV must be no larger than 2 MB")
    try:
        text = raw.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        if "amount" not in set(reader.fieldnames or []):
            raise HTTPException(status_code=400, detail="CSV must include an amount column")
        policy = policy_for(db, current_user.tenant_id)
        rows = []
        for line_number, row in enumerate(reader, start=2):
            try:
                payload = ScoreRequest(
                    amount=float(row.get("amount") or 0),
                    currency=row.get("currency") or "USD",
                    country=row.get("country") or "US",
                    cross_border=(row.get("cross_border") or "false").strip().lower() in {"1", "true", "yes"},
                    transactions_last_hour=int(float(row.get("transactions_last_hour") or 1)),
                    account_age_days=int(float(row.get("account_age_days") or 365)),
                    hour_of_day=int(float(row.get("hour_of_day") or 12)),
                )
            except (ValueError, TypeError, ValidationError) as exc:
                raise HTTPException(status_code=400, detail=f"Invalid data on CSV line {line_number}: {exc}") from exc
            rows.append({"row": line_number, **payload.model_dump(), **score_features(payload, policy.low_max, policy.review_max)})
            if len(rows) > 10_000:
                raise HTTPException(status_code=400, detail="CSV cannot contain more than 10,000 data rows")
        return {"items": rows, "total": len(rows), "data_mode": "heuristic_demo"}
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="CSV must use UTF-8 encoding") from exc


@app.post("/api/reviews/{transaction_id}")
def review_transaction(
    transaction_id: str,
    payload: ReviewRequest,
    current_user: UserRecord = Depends(require_roles("admin", "analyst")),
    db: Session = Depends(get_db),
):
    row = db.scalar(select(TransactionRecord).where(
        TransactionRecord.id == transaction_id,
        TransactionRecord.tenant_id == current_user.tenant_id,
    ))
    if row is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    old_status = row.review_status
    row.review_status = payload.decision
    row.review_note = payload.note
    row.reviewer = current_user.email
    add_audit(
        db, current_user.tenant_id, "review_decision", transaction_id, current_user.email,
        {"previous_status": old_status, "decision": payload.decision, "note": payload.note},
    )
    db.commit()
    db.refresh(row)
    return {"transaction": row.as_dict(), "audit_event": {
        "event_type": "review_decision", "transaction_id": transaction_id,
        "actor": current_user.email, "details": {"decision": payload.decision, "note": payload.note},
    }}


@app.get("/api/policies")
def get_policy(current_user: UserRecord = Depends(get_current_user), db: Session = Depends(get_db)):
    policy = policy_for(db, current_user.tenant_id)
    db.commit()
    return {"low_max": policy.low_max, "review_max": policy.review_max,
            "note": "Demo thresholds; not calibrated for production decisions."}


@app.put("/api/policies")
def update_policy(
    payload: PolicyUpdate,
    current_user: UserRecord = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    policy = policy_for(db, current_user.tenant_id)
    policy.low_max = payload.low_max
    policy.review_max = payload.review_max
    for row in db.scalars(
        select(TransactionRecord).where(TransactionRecord.tenant_id == current_user.tenant_id)
    ).all():
        result = score_features(ScoreRequest(
            amount=row.amount, currency=row.currency, country=row.country,
            transactions_last_hour=row.transactions_last_hour,
            account_age_days=row.account_age_days, hour_of_day=row.hour_of_day,
            cross_border=row.cross_border,
        ), policy.low_max, policy.review_max)
        for key, value in result.items():
            setattr(row, key, value)
    add_audit(
        db, current_user.tenant_id, "policy_updated", "*",
        current_user.email, payload.model_dump(),
    )
    db.commit()
    return {"low_max": policy.low_max, "review_max": policy.review_max,
            "note": "Saved to the configured database. Existing analyst decisions are preserved."}


@app.get("/api/audit")
def audit_log(
    limit: int = Query(default=100, ge=1, le=500),
    current_user: UserRecord = Depends(require_roles("admin", "analyst")),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.tenant_id == current_user.tenant_id)
        .order_by(desc(AuditEvent.timestamp))
        .limit(limit)
    ).all()
    return {"items": [
        {"id": row.id, "event_type": row.event_type, "transaction_id": row.transaction_id,
         "actor": row.actor, "details": row.details, "timestamp": row.timestamp.isoformat()}
        for row in rows
    ], "total": int(db.scalar(
        select(func.count()).select_from(AuditEvent)
        .where(AuditEvent.tenant_id == current_user.tenant_id)
    ) or 0)}


def demo_evaluation() -> dict:
    return {
        "status": "illustrative_only",
        "source": "synthetic_demo",
        "dataset": "12 hand-authored synthetic demo transactions",
        "threshold": 64,
        "precision": 0.0, "recall": 0.0, "f1": 0.0, "accuracy": 0.0,
        "pr_auc": None, "roc_auc": None,
        "confusion_matrix": {"tp": 0, "fp": 0, "fn": 0, "tn": 0},
        "warning": "Synthetic demo data is only for exercising the UI. It is not evidence of real-world model performance.",
    }


@app.get("/api/evaluation")
def evaluation():
    default_report_path = Path(__file__).resolve().parents[2] / "artifacts" / "benchmark_report.json"
    report_path = Path(os.getenv("RISKLENS_EVALUATION_PATH", str(default_report_path)))
    if report_path.is_file():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            required = {"status", "precision", "recall", "confusion_matrix"}
            if required.issubset(report) and report.get("status") == "benchmark_evaluated":
                return report
        except (OSError, json.JSONDecodeError):
            pass
    return demo_evaluation()
