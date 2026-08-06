from fastapi.testclient import TestClient

from service.app import config
from service.app import main
from service.app.main import app
from service.app.models import JobView


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


def test_start_job_accepts_bilibili(monkeypatch):
    # Moon Add
    monkeypatch.setattr(main, "create_job", lambda url: JobView(
        id="bilibili-job", state="queued", stage="等待处理", progress=0,
        platform="bilibili",
    ))
    response = TestClient(app).post(
        "/jobs", json={"url": "https://www.bilibili.com/video/BV1GJ411x7h7"}
    )
    assert response.status_code == 200
    assert response.json()["platform"] == "bilibili"


def test_clear_cache_preserves_config(tmp_path, monkeypatch):
    # Moon Add: cache cleanup must never remove the API configuration.
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "video-a.v2.json").write_text("{}", encoding="utf-8")
    (cache_dir / "video-b.v2.json").write_text("{}", encoding="utf-8")
    config_path = tmp_path / "config.json"
    config_path.write_text('{"api_key":"keep-me"}', encoding="utf-8")
    monkeypatch.setattr(main, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(main, "ensure_dirs", lambda: None)

    response = TestClient(app).delete("/cache")

    assert response.status_code == 200
    assert response.json()["removed"] == 2
    assert list(cache_dir.glob("*.json")) == []
    assert config_path.exists()
