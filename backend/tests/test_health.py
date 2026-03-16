def test_health_endpoint_returns_200(client):
    response = client.get("/health")
    assert response.status_code == 200


def test_health_endpoint_returns_status(client):
    response = client.get("/health")
    data = response.json()
    assert "status" in data
    assert data["status"] == "ok"
