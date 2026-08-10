from fastapi.testclient import TestClient

from service.app import config
from service.app import main
from service.app.main import app
from service.app.models import CudaRuntimeStatus, JobView, ServiceConfig


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


# Moon Begin: advanced config and lifecycle endpoints retain a stable API contract.
def test_advanced_config_fields_round_trip(monkeypatch):
    payload = {
        "base_url": "https://example.com/v1", "api_key": "secret",
        "translation_model": "translator", "summary_model": "summary",
        "whisper_model": "small", "whisper_model_path": "D:/models/whisper-small",
        "whisper_download_source": "mirror", "device": "auto",
    }
    monkeypatch.setattr(main, "save_config", lambda config: None)
    response = TestClient(app).put("/config", json=payload)
    assert response.status_code == 200
    assert response.json()["whisper_model_path"] == "D:/models/whisper-small"
    assert response.json()["whisper_download_source"] == "mirror"


def test_job_control_endpoints(monkeypatch):
    job = JobView(id="control", state="running", stage="翻译", progress=60)
    main.JOBS["control"] = job
    monkeypatch.setattr(main, "pause_job", lambda _: job.model_copy(update={"state":"paused"}))
    monkeypatch.setattr(main, "resume_job", lambda _: job)
    monkeypatch.setattr(main, "cancel_job", lambda _: job.model_copy(update={"state":"cancelled"}))
    test_client = TestClient(app)
    assert test_client.post("/jobs/control/pause").json()["state"] == "paused"
    assert test_client.post("/jobs/control/resume").json()["state"] == "running"
    assert test_client.post("/jobs/control/cancel").json()["state"] == "cancelled"


def test_cuda_runtime_endpoints(monkeypatch):
    status = CudaRuntimeStatus(state="idle", stage="尚未配置")
    installed = CudaRuntimeStatus(
        installed=True, valid=True, state="completed", stage="GPU 运行库已配置", progress=100
    )
    monkeypatch.setattr(main, "get_cuda_runtime_status", lambda: status)
    monkeypatch.setattr(main, "start_cuda_runtime_install", lambda: installed)
    monkeypatch.setattr(main, "cancel_cuda_runtime_install", lambda: status.model_copy(
        update={"state": "cancelled", "stage": "下载已取消，可稍后继续"}
    ))
    test_client = TestClient(app)
    assert test_client.get("/cuda/status").json()["valid"] is False
    assert test_client.post("/cuda/install").json()["valid"] is True
    assert test_client.post("/cuda/install/cancel").json()["state"] == "cancelled"


def test_open_resource_folders_use_resolved_status_paths(monkeypatch, tmp_path):
    # Moon Add: folder actions resolve semantic resources server-side.
    from service.app.models import ModelStatus

    opened = []
    monkeypatch.setattr(main, "_open_directory_in_foreground", lambda path: opened.append(str(path)))
    monkeypatch.setattr(main, "get_model_status", lambda model, path, install_dir=None: ModelStatus(
        model=model or "small", valid=True, resolved_path=str(tmp_path), stage="模型可用",
    ))
    monkeypatch.setattr(main, "get_cuda_runtime_status", lambda: CudaRuntimeStatus(
        installed=True, valid=True, path=str(tmp_path), stage="GPU 运行库已配置",
    ))
    client = TestClient(app)

    assert client.post("/models/open", params={"model": "small"}).json() == {"ok": True}
    assert client.post("/cuda/open").json() == {"ok": True}
    assert opened == [str(tmp_path.resolve()), str(tmp_path.resolve())]


def test_open_directory_starts_hidden_foreground_activator(monkeypatch, tmp_path):
    # Moon Add: opening remains immediate while a hidden helper activates reused Explorer windows.
    opened = []
    launched = []
    monkeypatch.setattr(main.os, "startfile", lambda path: opened.append(path), raising=False)
    monkeypatch.setattr(main.subprocess, "Popen", lambda command, **kwargs: launched.append((command, kwargs)))

    main._open_directory_in_foreground(tmp_path)

    assert opened == [str(tmp_path)]
    assert launched[0][0][0] == "powershell.exe"
    assert launched[0][1]["env"]["YTBA_OPEN_DIRECTORY"] == str(tmp_path)
    assert launched[0][1]["stdout"] is main.subprocess.DEVNULL


def test_whisper_defaults_to_cpu():
    assert ServiceConfig().device == "cpu"


def test_model_status_uses_unsaved_query_selection(monkeypatch):
    # Moon Add: changing the settings-page dropdown must not inspect stale saved config.
    observed = {}

    def fake_status(model, model_path, install_dir=None):
        observed.update(model=model, model_path=model_path, install_dir=install_dir)
        from service.app.models import ModelStatus
        return ModelStatus(model=model, configured_path=model_path, stage="模型可用")

    monkeypatch.setattr(main, "get_model_status", fake_status)
    response = TestClient(app).get(
        "/models/status", params={"model": "small", "model_path": "D:/models/small"}
    )
    assert response.status_code == 200
    assert observed == {"model": "small", "model_path": "D:/models/small", "install_dir": None}


def test_model_download_uses_unsaved_query_selection(monkeypatch):
    # Moon Add
    observed = {}

    def fake_download(model, model_path, source, install_dir=None):
        observed.update(model=model, model_path=model_path, source=source, install_dir=install_dir)
        from service.app.models import ModelStatus
        return ModelStatus(model=model, state="running", stage="正在连接模型仓库")

    monkeypatch.setattr(main, "start_model_download", fake_download)
    response = TestClient(app).post(
        "/models/download",
        params={"model": "medium", "model_path": "", "source": "mirror"},
    )
    assert response.status_code == 200
    assert observed == {"model": "medium", "model_path": "", "source": "mirror", "install_dir": None}
# Moon End
