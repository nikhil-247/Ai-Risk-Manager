from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

app = FastAPI(
    title="RiskLens AI API",
    description="Explainable transaction-risk demo API. Scores are heuristic and not production fraud predictions.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["Content-Type"],
)


class ScoreRequest(BaseModel):
    amount: float = Field(ge=0, le=1_000_000_000)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    country: str = Field(default="US", min_length=2, max_length=2)
    cross_border: bool = False
    transactions_last_hour: int = Field(default=1, ge=0, le=100_000)
    account_age_days: int = Field(default=365, ge=0, le=100_000)
    hour_of_day: int = Field(default=12, ge=0, le=23)

    @field_validator("currency", "country")
    @classmethod
    def uppercase_codes(cls, value: str) -> str:
        return value.upper()


class ReviewRequest(BaseModel):
    decision: Literal["confirmed_fraud", "legitimate", "needs_review"]
    note: str = Field(default="", max_length=1000)
    reviewer: str = Field(default="demo-analyst", min_length=1, max_length=100)


class Policy(BaseModel):
    low_max: int = Field(ge=0, le=100)
    review_max: int = Field(ge=1, le=100)

    @field_validator("review_max")
    @classmethod
    def review_threshold_valid(cls, value: int, info):
        low = info.data.get("low_max")
        if low is not None and value <= low:
            raise ValueError("review_max must be greater than low_max")
        return value


POLICY = Policy(low_max=29, review_max=64)
AUDIT_LOG: list[dict] = []


def score_features(payload: ScoreRequest) -> dict:
    points = 0
    reasons: list[str] = []
    if payload.amount >= 2000:
        points += 25
        reasons.append("High transaction amount")
    elif payload.amount >= 750:
        points += 12
        reasons.append("Elevated transaction amount")
    if payload.transactions_last_hour >= 8:
        points += 28
        reasons.append("High transaction velocity")
    elif payload.transactions_last_hour >= 4:
        points += 14
        reasons.append("Elevated transaction velocity")
    if payload.account_age_days < 7:
        points += 22
        reasons.append("Very new account")
    elif payload.account_age_days < 30:
        points += 10
        reasons.append("Recently created account")
    if payload.hour_of_day <= 4:
        points += 10
        reasons.append("Unusual hour (demo rule)")
    if payload.cross_border:
        points += 15
        reasons.append("Cross-border transaction")
    score = min(points, 100)
    if score <= POLICY.low_max:
        category = "low"
        action = "allow_for_review_policy"
    elif score <= POLICY.review_max:
        category = "medium"
        action = "manual_review"
    else:
        category = "high"
        action = "priority_review"
    return {
        "risk_score": score,
        "risk_category": category,
        "recommended_action": action,
        "reasons": reasons or ["No configured demo risk rule was triggered"],
        "score_type": "heuristic_demo_score",
        "disclaimer": "This is a transparent demo heuristic, not a calibrated fraud probability.",
    }


def demo_transaction(identifier: str, amount: float, country: str, velocity: int,
                     age: int, hour: int, cross_border: bool, decision: str,
                     created_at: str | None = None) -> dict:
    payload = ScoreRequest(
        amount=amount,
        country=country,
        transactions_last_hour=velocity,
        account_age_days=age,
        hour_of_day=hour,
        cross_border=cross_border,
    )
    scored = score_features(payload)
    return {
        "id": identifier,
        "amount": amount,
        "currency": "USD",
        "country": country,
        "transactions_last_hour": velocity,
        "account_age_days": age,
        "hour_of_day": hour,
        "cross_border": cross_border,
        **scored,
        "review_status": decision,
        "review_note": "",
        "reviewer": None,
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "demo_label": 1 if decision == "confirmed_fraud" else 0,
    }


TRANSACTIONS: list[dict] = [
    demo_transaction("txn_1001", 42.50, "US", 1, 420, 14, False, "legitimate", "2026-10-25T10:05:00+00:00"),
    demo_transaction("txn_1002", 2490.00, "GB", 9, 3, 2, True, "confirmed_fraud", "2026-10-25T10:04:00+00:00"),
    demo_transaction("txn_1003", 810.25, "IN", 5, 22, 11, True, "needs_review", "2026-10-25T10:02:00+00:00"),
    demo_transaction("txn_1004", 128.99, "US", 2, 140, 9, False, "legitimate", "2026-10-25T09:59:00+00:00"),
    demo_transaction("txn_1005", 5400.00, "SG", 11, 1, 3, True, "confirmed_fraud", "2026-10-25T09:57:00+00:00"),
    demo_transaction("txn_1006", 975.00, "IN", 3, 300, 17, False, "legitimate", "2026-10-25T09:54:00+00:00"),
    demo_transaction("txn_1007", 68.20, "US", 8, 5, 1, False, "needs_review", "2026-10-25T09:50:00+00:00"),
    demo_transaction("txn_1008", 1870.00, "CA", 6, 15, 23, True, "confirmed_fraud", "2026-10-25T09:48:00+00:00"),
    demo_transaction("txn_1009", 24.99, "DE", 1, 800, 13, False, "legitimate", "2026-10-25T09:44:00+00:00"),
    demo_transaction("txn_1010", 1290.00, "AU", 4, 60, 4, True, "needs_review", "2026-10-25T09:40:00+00:00"),
    demo_transaction("txn_1011", 6100.00, "US", 10, 2, 0, False, "confirmed_fraud", "2026-10-25T09:38:00+00:00"),
    demo_transaction("txn_1012", 320.00, "IN", 2, 160, 19, False, "legitimate", "2026-10-25T09:35:00+00:00"),
]


def record_audit(event_type: str, transaction_id: str, actor: str, details: dict) -> None:
    AUDIT_LOG.append({
        "id": str(uuid4()),
        "event_type": event_type,
        "transaction_id": transaction_id,
        "actor": actor,
        "details": details,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "risklens-ai-api", "version": app.version}


@app.get("/api/summary")
def summary():
    total = len(TRANSACTIONS)
    high = sum(row["risk_category"] == "high" for row in TRANSACTIONS)
    review = sum(row["review_status"] == "needs_review" for row in TRANSACTIONS)
    amount = sum(row["amount"] for row in TRANSACTIONS)
    return {
        "total_transactions": total,
        "total_amount": round(amount, 2),
        "high_risk_count": high,
        "pending_reviews": review,
        "confirmed_fraud_count": sum(row["review_status"] == "confirmed_fraud" for row in TRANSACTIONS),
        "low_risk_count": sum(row["risk_category"] == "low" for row in TRANSACTIONS),
        "medium_risk_count": sum(row["risk_category"] == "medium" for row in TRANSACTIONS),
        "high_risk_amount": round(sum(row["amount"] for row in TRANSACTIONS if row["risk_category"] == "high"), 2),
        "data_mode": "synthetic_demo",
    }


@app.get("/api/transactions")
def transactions(
    search: str = Query(default="", max_length=100),
    risk: Literal["all", "low", "medium", "high"] = "all",
    status: Literal["all", "legitimate", "confirmed_fraud", "needs_review"] = "all",
    limit: int = Query(default=100, ge=1, le=500),
):
    rows = TRANSACTIONS
    if search:
        needle = search.casefold()
        rows = [r for r in rows if needle in r["id"].casefold() or needle in r["country"].casefold()]
    if risk != "all":
        rows = [r for r in rows if r["risk_category"] == risk]
    if status != "all":
        rows = [r for r in rows if r["review_status"] == status]
    return {"items": rows[:limit], "total": len(rows), "data_mode": "synthetic_demo"}


@app.get("/api/transactions/{transaction_id}")
def transaction_detail(transaction_id: str):
    row = next((r for r in TRANSACTIONS if r["id"] == transaction_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return row


@app.post("/api/transactions/score")
def score_one(payload: ScoreRequest):
    return score_features(payload)


@app.post("/api/transactions/batch")
async def score_batch(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Upload a .csv file")
    raw = await file.read()
    if len(raw) > 2_000_000:
        raise HTTPException(status_code=413, detail="CSV must be no larger than 2 MB")
    try:
        text = raw.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        required = {"amount"}
        columns = set(reader.fieldnames or [])
        if not required.issubset(columns):
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
            except (ValueError, TypeError) as exc:
                raise HTTPException(status_code=400, detail=f"Invalid data on CSV line {line_number}: {exc}") from exc
            rows.append({"row": line_number, **payload.model_dump(), **score_features(payload)})
            if len(rows) > 10_000:
                raise HTTPException(status_code=400, detail="CSV cannot contain more than 10,000 data rows")
        return {"items": rows, "total": len(rows), "data_mode": "heuristic_demo"}
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="CSV must use UTF-8 encoding") from exc


@app.post("/api/reviews/{transaction_id}")
def review_transaction(transaction_id: str, payload: ReviewRequest):
    row = next((r for r in TRANSACTIONS if r["id"] == transaction_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    old_status = row["review_status"]
    row["review_status"] = payload.decision
    row["review_note"] = payload.note
    row["reviewer"] = payload.reviewer
    record_audit(
        "review_decision",
        transaction_id,
        payload.reviewer,
        {"previous_status": old_status, "decision": payload.decision, "note": payload.note},
    )
    return {"transaction": row, "audit_event": AUDIT_LOG[-1]}


@app.get("/api/policies")
def get_policy():
    return {**POLICY.model_dump(), "note": "Demo thresholds; not calibrated for production decisions."}


@app.put("/api/policies")
def update_policy(payload: Policy):
    global POLICY
    POLICY = payload
    for row in TRANSACTIONS:
        rescore = score_features(ScoreRequest(
            amount=row["amount"], country=row["country"],
            transactions_last_hour=row["transactions_last_hour"],
            account_age_days=row["account_age_days"], hour_of_day=row["hour_of_day"],
            cross_border=row["cross_border"],
        ))
        row.update(rescore)
    record_audit("policy_updated", "*", "demo-analyst", payload.model_dump())
    return {**POLICY.model_dump(), "note": "Updated in memory; resets when the server restarts."}


@app.get("/api/audit")
def audit_log(limit: int = Query(default=100, ge=1, le=500)):
    return {"items": list(reversed(AUDIT_LOG[-limit:])), "total": len(AUDIT_LOG)}


@app.get("/api/evaluation")
def evaluation():
    # These demo labels were authored to populate the UI and are not a benchmark.
    y_true = [r["demo_label"] for r in TRANSACTIONS]
    y_pred = [1 if r["risk_category"] == "high" else 0 for r in TRANSACTIONS]
    tp = sum(a == 1 and b == 1 for a, b in zip(y_true, y_pred))
    fp = sum(a == 0 and b == 1 for a, b in zip(y_true, y_pred))
    fn = sum(a == 1 and b == 0 for a, b in zip(y_true, y_pred))
    tn = sum(a == 0 and b == 0 for a, b in zip(y_true, y_pred))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "status": "illustrative_only",
        "dataset": "12 hand-authored synthetic demo transactions",
        "threshold": POLICY.review_max,
        "confusion_matrix": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "accuracy": round((tp + tn) / len(y_true), 4) if y_true else 0,
        "warning": "Do not interpret these metrics as model performance. Use the ML benchmark pipeline before making performance claims.",
    }
