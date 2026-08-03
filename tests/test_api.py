from fastapi.testclient import TestClient

from service.app import config
from service.app import main
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

    # Moon Add: saving other settings with an empty secret preserves the key.
    payload["api_key"] = ""
    payload["translation_model"] = "translation-updated"
    assert client.put("/config", json=payload).status_code == 200
    saved = config.load_config()
    assert saved.api_key == "test-secret"
    assert saved.translation_model == "translation-updated"


def test_start_job_runs_on_event_loop(monkeypatch):
    # Moon Add: regress the missing event loop failure from a synchronous endpoint.
    captured = {}

    def fake_create_job(url):
        import asyncio

        captured["loop_was_running"] = asyncio.get_running_loop().is_running()
        return {
            "id": "job-test",
            "state": "queued",
            "stage": "等待处理",
            "progress": 0,
            "error": None,
            "result": None,
        }

    monkeypatch.setattr(main, "create_job", fake_create_job)
    response = TestClient(app).post(
        "/jobs", json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}
    )
    assert response.status_code == 200
    assert captured["loop_was_running"] is True
