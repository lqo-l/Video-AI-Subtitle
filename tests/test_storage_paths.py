# Moon Begin
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from service.app import main, storage
from service.app.main import app
from service.app.models import ServiceConfig, StoragePathUpdate


def _write_model(directory: Path, content: bytes = b"model") -> None:
    directory.mkdir(parents=True)
    for name in ("config.json", "tokenizer.json", "model.bin"):
        (directory / name).write_bytes(content)


def test_model_storage_migration_copies_valid_models_and_updates_config(tmp_path, monkeypatch):
    source = tmp_path / "old-models"
    target = tmp_path / "new-models"
    _write_model(source / "small")
    saved = []
    monkeypatch.setattr(storage, "resolve_install_dir", lambda kind: source)
    monkeypatch.setattr(storage, "_model_sources", lambda root: [("small", source / "small")])
    monkeypatch.setattr(storage, "load_config", lambda: ServiceConfig())
    monkeypatch.setattr(storage, "save_config", saved.append)

    result = storage.update_install_directory(
        StoragePathUpdate(kind="model", path=str(target), migrate=True)
    )

    assert result.migrated is True
    assert result.migrated_items == 1
    assert (target / "small" / "model.bin").read_bytes() == b"model"
    assert (source / "small" / "model.bin").exists()
    assert saved[0].model_install_dir == str(target.resolve())


def test_storage_path_change_without_migration_keeps_existing_files(tmp_path, monkeypatch):
    source = tmp_path / "old-cuda"
    target = tmp_path / "new-cuda"
    (source / "nvidia").mkdir(parents=True)
    (source / "nvidia" / "keep.dll").write_bytes(b"dll")
    saved = []
    monkeypatch.setattr(storage, "resolve_install_dir", lambda kind: source)
    monkeypatch.setattr(storage, "load_config", lambda: ServiceConfig())
    monkeypatch.setattr(storage, "save_config", saved.append)

    result = storage.update_install_directory(
        StoragePathUpdate(kind="cuda", path=str(target), migrate=False)
    )

    assert result.migrated is False
    assert (source / "nvidia" / "keep.dll").exists()
    assert saved[0].cuda_install_dir == str(target.resolve())


def test_folder_picker_reports_changed_path_and_existing_content(tmp_path, monkeypatch):
    current = tmp_path / "current"
    selected = tmp_path / "selected"
    current.mkdir()
    monkeypatch.setattr(storage, "resolve_install_dir", lambda kind: current)
    monkeypatch.setattr(storage, "storage_has_existing", lambda kind: True)
    monkeypatch.setattr(storage.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        stdout=str(selected), returncode=0,
    ))

    result = storage.select_install_directory("model")

    assert result.changed is True
    assert result.has_existing is True
    assert result.path == str(selected.resolve())


def test_storage_api_uses_semantic_kind_and_update_body(monkeypatch, tmp_path):
    from service.app.models import ModelStatus

    monkeypatch.setattr(main, "get_model_status", lambda: ModelStatus(model="small", state="idle"))
    monkeypatch.setattr(main, "select_install_directory", lambda kind: {
        "kind": kind, "path": str(tmp_path), "changed": True, "has_existing": False,
    })
    monkeypatch.setattr(main, "update_install_directory", lambda update: {
        "kind": update.kind, "path": update.path, "migrated": update.migrate,
        "migrated_items": 1 if update.migrate else 0,
    })
    client = TestClient(app)

    assert client.post("/storage/select", params={"kind": "model"}).json()["changed"] is True
    response = client.put("/storage/path", json={
        "kind": "model", "path": str(tmp_path), "migrate": True,
    })
    assert response.status_code == 200
    assert response.json()["migrated_items"] == 1
# Moon End
