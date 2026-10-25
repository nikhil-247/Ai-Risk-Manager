import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.auth import bootstrap_admin, create_access_token, hash_password
from backend.app.database import Base, get_db
from backend.app.models import TenantRecord, UserRecord
from backend.app.tenancy import DEFAULT_TENANT_ID, DEFAULT_TENANT_NAME
from backend.app.main import app
from backend.app.seed import seed_demo_data


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)
    with sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)() as db:
        db.add(TenantRecord(id=DEFAULT_TENANT_ID, name=DEFAULT_TENANT_NAME))
        db.flush()
        db.add_all([
            UserRecord(
                tenant_id=DEFAULT_TENANT_ID,
                id="test-admin-id", email="admin@example.com",
                password_hash=hash_password("test-admin-password-123!"), role="admin", is_active=True,
            ),
            UserRecord(
                tenant_id=DEFAULT_TENANT_ID,
                id="test-analyst-id", email="analyst@example.com",
                password_hash=hash_password("test-analyst-password-123!"), role="analyst", is_active=True,
            ),
            UserRecord(
                tenant_id=DEFAULT_TENANT_ID,
                id="test-viewer-id", email="viewer@example.com",
                password_hash=hash_password("test-viewer-password-123!"), role="viewer", is_active=True,
            ),
            UserRecord(
                tenant_id=DEFAULT_TENANT_ID,
                id="test-disabled-id", email="disabled@example.com",
                password_hash=hash_password("disabled-user-password-123!"), role="analyst", is_active=False,
            ),
        ])
        db.commit()

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestingSessionLocal() as db:
        seed_demo_data(db)
    with TestClient(app) as test_client:
        test_client.headers.update({"Authorization": f"Bearer {create_access_token('test-admin-id')}"})
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["database"] == "reachable"


def test_summary_has_demo_mode(client):
    response = client.get("/api/summary")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_transactions"] == 12
    assert payload["data_mode"] == "synthetic_demo"


def test_transaction_search_and_detail(client):
    listed = client.get("/api/transactions?search=txn_1001")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    detail = client.get("/api/transactions/txn_1001")
    assert detail.status_code == 200
    assert detail.json()["id"] == "txn_1001"


def test_missing_transaction_returns_404(client):
    assert client.get("/api/transactions/missing").status_code == 404


def test_scoring_returns_explanation_and_disclaimer(client):
    response = client.post("/api/transactions/score", json={
        "amount": 5000, "country": "GB", "cross_border": True,
        "transactions_last_hour": 10, "account_age_days": 1, "hour_of_day": 2,
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["risk_score"] == 100
    assert payload["risk_category"] == "high"
    assert payload["reasons"]
    assert "not a calibrated" in payload["disclaimer"]


def test_review_decision_is_persisted_and_audited(client):
    response = client.post("/api/reviews/txn_1001", json={
        "decision": "confirmed_fraud", "note": "Test review", "reviewer": "pytest"
    })
    assert response.status_code == 200
    assert response.json()["transaction"]["review_status"] == "confirmed_fraud"
    assert client.get("/api/transactions/txn_1001").json()["review_status"] == "confirmed_fraud"
    audit = client.get("/api/audit")
    assert audit.status_code == 200
    assert audit.json()["total"] == 1
    assert audit.json()["items"][0]["actor"] == "admin@example.com"


def test_invalid_policy_rejected(client):
    response = client.put("/api/policies", json={"low_max": 80, "review_max": 20})
    assert response.status_code == 422


def test_policy_update_is_persisted(client):
    response = client.put("/api/policies", json={"low_max": 20, "review_max": 50})
    assert response.status_code == 200
    assert client.get("/api/policies").json()["low_max"] == 20
    assert client.get("/api/audit").json()["total"] == 1


def test_csv_batch_scoring(client):
    csv_data = b"amount,country,cross_border,transactions_last_hour,account_age_days,hour_of_day\n2500,GB,true,8,2,3\n"
    response = client.post(
        "/api/transactions/batch",
        files={"file": ("transactions.csv", csv_data, "text/csv")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["risk_category"] == "high"


def test_batch_rejects_non_csv(client):
    response = client.post(
        "/api/transactions/batch",
        files={"file": ("transactions.txt", b"amount\n10", "text/plain")},
    )
    assert response.status_code == 400


def test_batch_rejects_invalid_amount(client):
    response = client.post(
        "/api/transactions/batch",
        files={"file": ("transactions.csv", b"amount\n-12", "text/csv")},
    )
    assert response.status_code == 400


def test_evaluation_marks_demo_data_honestly(client):
    response = client.get("/api/evaluation")
    assert response.status_code == 200
    assert response.json()["status"] == "illustrative_only"
    assert response.json()["source"] == "synthetic_demo"


def test_auth_login_and_me(client):
    client.headers.pop("Authorization", None)
    response = client.post(
        "/api/auth/login",
        data={"username": "admin@example.com", "password": "test-admin-password-123!"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["token_type"] == "bearer"
    assert response.headers["cache-control"] == "no-store"
    assert payload["user"]["role"] == "admin"
    client.headers.update({"Authorization": f"Bearer {payload['access_token']}"})
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "admin@example.com"


def test_protected_endpoint_rejects_anonymous_client(client):
    client.headers.pop("Authorization", None)
    response = client.get("/api/summary")
    assert response.status_code == 401


def test_registration_only_creates_viewers(client):
    response = client.post(
        "/api/auth/register",
        json={"email": "new.viewer@example.com", "password": "new-viewer-password-123!"},
    )
    assert response.status_code == 201
    assert response.json()["role"] == "viewer"
    assert "password_hash" not in response.json()
    duplicate = client.post(
        "/api/auth/register",
        json={"email": "NEW.VIEWER@example.com", "password": "new-viewer-password-123!"},
    )
    assert duplicate.status_code == 409


def test_viewer_cannot_change_policy_or_submit_reviews(client):
    viewer = client.post(
        "/api/auth/login",
        data={"username": "viewer@example.com", "password": "test-viewer-password-123!"},
    ).json()
    admin_headers = dict(client.headers)
    client.headers.update({"Authorization": f"Bearer {viewer['access_token']}"})
    policy = client.put("/api/policies", json={"low_max": 20, "review_max": 50})
    review = client.post(
        "/api/reviews/txn_1001",
        json={"decision": "confirmed_fraud", "note": "viewer attempt"},
    )
    assert policy.status_code == 403
    assert review.status_code == 403
    client.headers.clear()
    client.headers.update(admin_headers)


def test_analyst_can_review_but_cannot_change_policy(client):
    analyst = client.post(
        "/api/auth/login",
        data={"username": "analyst@example.com", "password": "test-analyst-password-123!"},
    ).json()
    admin_headers = dict(client.headers)
    client.headers.update({"Authorization": f"Bearer {analyst['access_token']}"})
    policy = client.put("/api/policies", json={"low_max": 20, "review_max": 50})
    review = client.post(
        "/api/reviews/txn_1001",
        json={"decision": "legitimate", "note": "analyst review", "reviewer": "spoofed-user"},
    )
    assert policy.status_code == 403
    assert review.status_code == 200
    assert review.json()["transaction"]["reviewer"] == "analyst@example.com"
    assert review.json()["audit_event"]["actor"] == "analyst@example.com"
    client.headers.clear()
    client.headers.update(admin_headers)


def test_admin_can_create_role_scoped_user(client):
    response = client.post(
        "/api/auth/admin/users",
        json={
            "email": "new.analyst@example.com",
            "password": "new-analyst-password-123!",
            "role": "analyst",
        },
    )
    assert response.status_code == 201
    assert response.json()["role"] == "analyst"
    assert "password_hash" not in response.json()
    audit = client.get("/api/audit").json()
    assert audit["total"] == 1
    assert audit["items"][0]["event_type"] == "user_created"
    assert audit["items"][0]["actor"] == "admin@example.com"
    assert audit["items"][0]["details"]["email"] == "new.analyst@example.com"


def test_login_rejects_wrong_password(client):
    client.headers.pop("Authorization", None)
    response = client.post(
        "/api/auth/login",
        data={"username": "admin@example.com", "password": "wrong-password-value"},
    )
    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"


def test_invalid_and_inactive_tokens_are_rejected(client):
    client.headers.update({"Authorization": "Bearer definitely.not-a-valid-token"})
    invalid = client.get("/api/summary")
    assert invalid.status_code == 401

    disabled_token = create_access_token("test-disabled-id")
    client.headers.update({"Authorization": f"Bearer {disabled_token}"})
    disabled = client.get("/api/summary")
    assert disabled.status_code == 401


def test_batch_upload_enforces_size_limit(client):
    oversized = b"amount\\n1\\n" + (b" " * 2_000_001)
    response = client.post(
        "/api/transactions/batch",
        files={"file": ("large.csv", oversized, "text/csv")},
    )
    assert response.status_code == 413


def test_bootstrap_admin_does_not_promote_existing_viewer(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setenv("RISKLENS_BOOTSTRAP_ADMIN_EMAIL", "existing@example.com")
    monkeypatch.setenv("RISKLENS_BOOTSTRAP_ADMIN_PASSWORD", "bootstrap-password-123!")
    with TestingSessionLocal() as db:
        db.add(UserRecord(
            id="existing-viewer", email="existing@example.com",
            password_hash=hash_password("viewer-password-123!"),
            role="viewer", is_active=True,
        ))
        db.commit()
        with pytest.raises(RuntimeError, match="roles are never auto-promoted"):
            bootstrap_admin(db)
        assert db.get(UserRecord, "existing-viewer").role == "viewer"
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_production_requires_explicit_non_development_jwt_secret():
    env = os.environ.copy()
    env["RISKLENS_ENV"] = "production"
    env.pop("RISKLENS_JWT_SECRET", None)
    root = Path(__file__).resolve().parents[2]
    missing_secret = subprocess.run(
        [sys.executable, "-c", "import backend.app.auth"],
        cwd=root, env=env, capture_output=True, text=True, check=False,
    )
    assert missing_secret.returncode != 0
    assert "RISKLENS_JWT_SECRET is required when RISKLENS_ENV=production" in missing_secret.stderr

    env["RISKLENS_JWT_SECRET"] = "local-development-secret-change-this-before-deploy-2026"
    unsafe_secret = subprocess.run(
        [sys.executable, "-c", "import backend.app.auth"],
        cwd=root, env=env, capture_output=True, text=True, check=False,
    )
    assert unsafe_secret.returncode != 0
    assert "cannot be used in production" in unsafe_secret.stderr
