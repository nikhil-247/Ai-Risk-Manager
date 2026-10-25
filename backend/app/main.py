from __future__ import annotations

import csv
import io
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from backend.app.database import get_db, init_db
from backend.app.models import AuditEvent, RiskPolicyRecord, TransactionRecord
from backend.app.risk_scoring import ScoreRequest, score_features
from backend.app.seed import seed_demo_data


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    from backend.app.database import SessionLocal
    with SessionLocal() as db:
        seed_demo_data(db)
    yield


app = FastAPI(
    title="RiskLens AI API",
    description="Explainable transaction-risk API. The demo rules are not production fraud predictions.",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["Content-Type"],
)


class ReviewRequest(BaseModel):
    decision: Literal["confirmed_fraud", "legitimate", "needs_review"]
    note: str = Field(default="", max_length=1000)
    reviewer: str = Field(default="demo-analyst", min_length=1, max_length=100)


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


def policy_for(db: Session) -> RiskPolicyRecord:
    policy = db.get(RiskPolicyRecord, 1)
    if policy is None:
        policy = RiskPolicyRecord(id=1, low_max=29, review_max=64)
        db.add(policy)
        db.flush()
    return policy


def add_audit(db: Session, event_type: str, transaction_id: str, actor: str, details: dict) -> AuditEvent:
    event = AuditEvent(
        id=str(uuid4()),
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


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    # A database roundtrip makes this useful as a container readiness probe.
    db.execute(select(1))
    return {"status": "ok", "service": "risklens-ai-api", "version": app.version, "database": "reachable"}


@app.get("/api/summary")
def summary(db: Session = Depends(get_db)):
    rows = list(db.scalars(select(TransactionRecord)).all())
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
    db: Session = Depends(get_db),
):
    query = select(TransactionRecord)
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
def transaction_detail(transaction_id: str, db: Session = Depends(get_db)):
    row = db.get(TransactionRecord, transaction_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return row.as_dict()


@app.post("/api/transactions/score")
def score_one(payload: ScoreRequest, db: Session = Depends(get_db)):
    policy = policy_for(db)
    return score_features(payload, policy.low_max, policy.review_max)


@app.post("/api/transactions/batch")
async def score_batch(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Upload a .csv file")
    raw = await file.read()
    if len(raw) > 2_000_000:
        raise HTTPException(status_code=413, detail="CSV must be no larger than 2 MB")
    try:
        text = raw.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        if "amount" not in set(reader.fieldnames or []):
            raise HTTPException(status_code=400, detail="CSV must include an amount column")
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
            policy = policy_for(db)
            rows.append({"row": line_number, **payload.model_dump(), **score_features(payload, policy.low_max, policy.review_max)})
            if len(rows) > 10_000:
                raise HTTPException(status_code=400, detail="CSV cannot contain more than 10,000 data rows")
        return {"items": rows, "total": len(rows), "data_mode": "heuristic_demo"}
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="CSV must use UTF-8 encoding") from exc


@app.post("/api/reviews/{transaction_id}")
def review_transaction(transaction_id: str, payload: ReviewRequest, db: Session = Depends(get_db)):
    row = db.get(TransactionRecord, transaction_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    old_status = row.review_status
    row.review_status = payload.decision
    row.review_note = payload.note
    row.reviewer = payload.reviewer
    add_audit(
        db, "review_decision", transaction_id, payload.reviewer,
        {"previous_status": old_status, "decision": payload.decision, "note": payload.note},
    )
    db.commit()
    db.refresh(row)
    return {"transaction": row.as_dict(), "audit_event": {
        "event_type": "review_decision", "transaction_id": transaction_id,
        "actor": payload.reviewer, "details": {"decision": payload.decision, "note": payload.note},
    }}


@app.get("/api/policies")
def get_policy(db: Session = Depends(get_db)):
    policy = policy_for(db)
    db.commit()
    return {"low_max": policy.low_max, "review_max": policy.review_max,
            "note": "Demo thresholds; not calibrated for production decisions."}


@app.put("/api/policies")
def update_policy(payload: PolicyUpdate, db: Session = Depends(get_db)):
    policy = policy_for(db)
    policy.low_max = payload.low_max
    policy.review_max = payload.review_max
    for row in db.scalars(select(TransactionRecord)).all():
        result = score_features(ScoreRequest(
            amount=row.amount, currency=row.currency, country=row.country,
            transactions_last_hour=row.transactions_last_hour,
            account_age_days=row.account_age_days, hour_of_day=row.hour_of_day,
            cross_border=row.cross_border,
        ), policy.low_max, policy.review_max)
        for key, value in result.items():
            setattr(row, key, value)
    add_audit(db, "policy_updated", "*", "demo-analyst", payload.model_dump())
    db.commit()
    return {"low_max": policy.low_max, "review_max": policy.review_max,
            "note": "Saved to the configured database. Existing analyst decisions are preserved."}


@app.get("/api/audit")
def audit_log(limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db)):
    rows = db.scalars(select(AuditEvent).order_by(desc(AuditEvent.timestamp)).limit(limit)).all()
    return {"items": [
        {"id": row.id, "event_type": row.event_type, "transaction_id": row.transaction_id,
         "actor": row.actor, "details": row.details, "timestamp": row.timestamp.isoformat()}
        for row in rows
    ], "total": int(db.scalar(select(func.count()).select_from(AuditEvent)) or 0)}


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
