import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.auth import hash_password
from backend.app.database import Base, get_db
from backend.app.main import app
from backend.app.models import UserRecord
from backend.app.seed import seed_demo_data

TEST_PASSWORD = "TestPassword123!"
TEST_PASSWORD_HASH = hash_password(TEST_PASSWORD)


def login_headers(client, email: str) -> dict[str, str]:
    response = client.post("/api/auth/login", data={"username": email, "password": TEST_PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestingSessionLocal() as db:
        seed_demo_data(db)
        db.add_all([
            UserRecord(email="admin@risklens.test", password_hash=TEST_PASSWORD_HASH, role="admin", is_active=True),
            UserRecord(email="analyst@risklens.test", password_hash=TEST_PASSWORD_HASH, role="analyst", is_active=True),
            UserRecord(email="viewer@risklens.test", password_hash=TEST_PASSWORD_HASH, role="viewer", is_active=True),
        ])
        db.commit()
    with TestClient(app) as test_client:
        test_client.headers.update(login_headers(test_client, "admin@risklens.test"))
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
        "decision": "confirmed_fraud", "note": "Test review", "reviewer": "spoofed-reviewer"
    }, headers=login_headers(client, "analyst@risklens.test"))
    assert response.status_code == 200
    assert response.json()["transaction"]["review_status"] == "confirmed_fraud"
    assert client.get("/api/transactions/txn_1001").json()["review_status"] == "confirmed_fraud"
    audit = client.get("/api/audit")
    assert audit.status_code == 200
    assert audit.json()["total"] == 1
    assert audit.json()["items"][0]["actor"] == "analyst@risklens.test"


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



def test_summary_requires_authentication(client):
    response = client.get("/api/summary", headers={"Authorization": ""})
    assert response.status_code == 401


def test_login_and_current_user(client):
    headers = login_headers(client, "analyst@risklens.test")
    response = client.get("/api/auth/me", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["email"] == "analyst@risklens.test"
    assert payload["role"] == "analyst"
    assert "password_hash" not in payload


def test_login_rejects_wrong_password(client):
    response = client.post(
        "/api/auth/login",
        data={"username": "admin@risklens.test", "password": "wrong-password"},
    )
    assert response.status_code == 401


def test_viewer_is_read_only(client):
    headers = login_headers(client, "viewer@risklens.test")
    assert client.get("/api/summary", headers=headers).status_code == 200
    assert client.post(
        "/api/reviews/txn_1001",
        json={"decision": "confirmed_fraud", "note": "not permitted"},
        headers=headers,
    ).status_code == 403
    assert client.put(
        "/api/policies",
        json={"low_max": 20, "review_max": 50},
        headers=headers,
    ).status_code == 403


def test_analyst_can_review_but_cannot_change_policy(client):
    headers = login_headers(client, "analyst@risklens.test")
    review = client.post(
        "/api/reviews/txn_1001",
        json={"decision": "needs_review", "note": "analyst review"},
        headers=headers,
    )
    assert review.status_code == 200
    assert review.json()["audit_event"]["actor"] == "analyst@risklens.test"
    policy = client.put(
        "/api/policies",
        json={"low_max": 20, "review_max": 50},
        headers=headers,
    )
    assert policy.status_code == 403


def test_admin_can_create_user(client):
    response = client.post(
        "/api/auth/users",
        json={"email": "new-viewer@risklens.test", "password": "NewUserPassword123!", "role": "viewer"},
    )
    assert response.status_code == 201
    assert response.json()["role"] == "viewer"
    assert response.json()["email"] == "new-viewer@risklens.test"
    assert "password_hash" not in response.json()
    assert client.post(
        "/api/auth/users",
        json={"email": "new-viewer@risklens.test", "password": "NewUserPassword123!", "role": "viewer"},
    ).status_code == 409


def test_only_admin_can_create_users(client):
    response = client.post(
        "/api/auth/users",
        json={"email": "unauthorized@risklens.test", "password": "NewUserPassword123!", "role": "viewer"},
        headers=login_headers(client, "analyst@risklens.test"),
    )
    assert response.status_code == 403
