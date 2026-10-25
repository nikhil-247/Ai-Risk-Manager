from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_summary_has_demo_mode():
    response = client.get("/api/summary")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_transactions"] >= 1
    assert payload["data_mode"] == "synthetic_demo"


def test_transaction_search_and_detail():
    listed = client.get("/api/transactions?search=txn_1001")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    detail = client.get("/api/transactions/txn_1001")
    assert detail.status_code == 200
    assert detail.json()["id"] == "txn_1001"


def test_missing_transaction_returns_404():
    assert client.get("/api/transactions/missing").status_code == 404


def test_scoring_returns_explanation_and_disclaimer():
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


def test_review_decision_records_audit():
    response = client.post("/api/reviews/txn_1001", json={
        "decision": "confirmed_fraud", "note": "Test review", "reviewer": "pytest"
    })
    assert response.status_code == 200
    assert response.json()["transaction"]["review_status"] == "confirmed_fraud"
    audit = client.get("/api/audit")
    assert audit.status_code == 200
    assert audit.json()["total"] >= 1


def test_invalid_policy_rejected():
    response = client.put("/api/policies", json={"low_max": 80, "review_max": 20})
    assert response.status_code == 422


def test_csv_batch_scoring():
    csv_data = b"amount,country,cross_border,transactions_last_hour,account_age_days,hour_of_day\n2500,GB,true,8,2,3\n"
    response = client.post(
        "/api/transactions/batch",
        files={"file": ("transactions.csv", csv_data, "text/csv")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["risk_category"] == "high"


def test_batch_rejects_non_csv():
    response = client.post(
        "/api/transactions/batch",
        files={"file": ("transactions.txt", b"amount\n10", "text/plain")},
    )
    assert response.status_code == 400
