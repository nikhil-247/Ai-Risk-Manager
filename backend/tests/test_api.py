import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database import Base, get_db
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
    assert audit.json()["items"][0]["actor"] == "pytest"


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
