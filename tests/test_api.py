from fastapi.testclient import TestClient

from service.app import config
from service.app.main import app


def test_health_and_config_redaction(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(config, "WORK_DIR", tmp_path / "work")
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["ok"] is True

    payload = {
        "base_url": "https://example.invalid/v1",
        "api_key": "test-secret",
        "translation_model": "translation-test",
        "summary_model": "summary-test",
        "whisper_model": "small.en",
        "device": "auto",
    }
    assert client.put("/config", json=payload).status_code == 200
    public = client.get("/config").json()
    assert "api_key" not in public
    assert public["api_key_configured"] is True
    assert "test-secret" not in client.get("/config").text
