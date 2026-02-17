from fastapi.testclient import TestClient

from jarvis.main import app


def test_healthz_ok() -> None:
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_readyz_shape() -> None:
    client = TestClient(app)
    response = client.get("/readyz")
    assert response.status_code in {200, 503}
    data = response.json()
    assert "ok" in data
    assert "providers" in data


def test_readyz_returns_503_when_dependencies_unhealthy(monkeypatch) -> None:
    from jarvis.routes import health as health_route

    async def unhealthy(self):
        del self
        return {"primary": False, "fallback": False}

    monkeypatch.setattr(health_route.ProviderRouter, "health", unhealthy)

    client = TestClient(app)
    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["ok"] is False
