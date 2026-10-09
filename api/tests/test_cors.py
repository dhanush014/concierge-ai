from fastapi.testclient import TestClient

PREFLIGHT = {
    "Access-Control-Request-Method": "POST",
    "Access-Control-Request-Headers": "authorization,content-type",
}


def test_web_app_origin_is_allowed(client: TestClient) -> None:
    resp = client.options("/appointments", headers={"Origin": "http://localhost:3000", **PREFLIGHT})

    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "authorization" in resp.headers["access-control-allow-headers"].lower()


def test_other_origins_are_not_allowed(client: TestClient) -> None:
    for origin in ("https://evil.example", "http://127.0.0.1:3000", "http://localhost:3001"):
        preflight = client.options("/appointments", headers={"Origin": origin, **PREFLIGHT})
        simple = client.get("/doctors", headers={"Origin": origin})

        assert "access-control-allow-origin" not in preflight.headers, origin
        assert "access-control-allow-origin" not in simple.headers, origin
