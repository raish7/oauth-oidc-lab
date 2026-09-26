def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_cors_allows_the_frontend_origin_with_credentials(client):
    response = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_cors_rejects_other_origins(client):
    response = client.get("/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in response.headers


def test_unfinished_routes_are_stubbed(client):
    for method, path in [
        ("GET", "/auth/me"),
        ("POST", "/auth/logout"),
        ("GET", "/api/profile"),
    ]:
        response = client.request(method, path, follow_redirects=False)
        assert response.status_code == 501, (method, path, response.status_code)
