# Moon Begin
from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

from fastapi import HTTPException

from .config import default_model_install_dir, load_config, resolve_install_dir, save_config
from .models import DownloadCacheResult, StoragePathResult, StoragePathSelection, StoragePathUpdate


_FOLDER_PICKER_SCRIPT = r"""
Add-Type -AssemblyName System.Windows.Forms
$owner = New-Object System.Windows.Forms.Form
$owner.TopMost = $true
$owner.ShowInTaskbar = $false
$owner.WindowState = 'Minimized'
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = $env:YTBA_FOLDER_TITLE
$dialog.ShowNewFolderButton = $true
if (Test-Path -LiteralPath $env:YTBA_INITIAL_FOLDER) {
    $dialog.SelectedPath = $env:YTBA_INITIAL_FOLDER
}
$owner.Show()
$owner.Activate()
try {
    if ($dialog.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) {
        [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
        Write-Output $dialog.SelectedPath
    }
} finally {
    $dialog.Dispose()
    $owner.Close()
    $owner.Dispose()
}
"""


def _model_directory_valid(path: Path) -> bool:
    if not all((path / name).is_file() for name in ("config.json", "tokenizer.json", "model.bin")):
        return False
    size = (path / "model.bin").stat().st_size
    marker = path / ".ytba-model-size"
    try:
        return size > 0 and (not marker.is_file() or int(marker.read_text().strip()) == size)
    except (OSError, ValueError):
        return False


def _model_sources(root: Path) -> list[tuple[str, Path]]:
    sources = []
    if root.is_dir():
        for path in root.iterdir():
            if path.is_dir() and _model_directory_valid(path):
                sources.append((path.name, path))
    # Existing releases may have installed into Hugging Face's shared cache.
    try:
        from huggingface_hub.constants import HF_HUB_CACHE

        if root.resolve() != default_model_install_dir().resolve():
            return sources
        cache = Path(HF_HUB_CACHE)
        for model in ("tiny", "base", "small", "medium"):
            snapshots = cache / f"models--Systran--faster-whisper-{model}" / "snapshots"
            candidates = list(snapshots.glob("*")) if snapshots.is_dir() else []
            source = next((path for path in candidates if _model_directory_valid(path)), None)
            if source and not any(name == model for name, _ in sources):
                sources.append((model, source))
    except ImportError:
        pass
    return sources


def _cuda_items(root: Path) -> list[Path]:
    patterns = (
        "nvidia", "nvidia_cublas_cu12-*.dist-info", "nvidia_cudnn_cu12-*.dist-info",
        "nvidia_cuda_nvrtc_cu12-*.dist-info",
    )
    items: list[Path] = []
    for pattern in patterns:
        items.extend(root.glob(pattern))
    return list(dict.fromkeys(item for item in items if item.exists()))


def storage_has_existing(kind: str) -> bool:
    root = resolve_install_dir(kind)
    return bool(_model_sources(root) if kind == "model" else _cuda_items(root))


def select_install_directory(kind: str) -> StoragePathSelection:
    if kind not in ("model", "cuda"):
        raise HTTPException(400, "未知的存储类型")
    current = resolve_install_dir(kind)
    environment = os.environ.copy()
    environment["YTBA_INITIAL_FOLDER"] = str(current)
    environment["YTBA_FOLDER_TITLE"] = "选择模型安装位置" if kind == "model" else "选择 GPU 运行库安装位置"
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            [
                "powershell.exe", "-NoProfile", "-NonInteractive", "-STA",
                "-WindowStyle", "Hidden", "-Command", _FOLDER_PICKER_SCRIPT,
            ],
            env=environment, creationflags=creation_flags,
            capture_output=True, text=True, encoding="utf-8", timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(500, f"无法打开文件夹选择器：{exc}") from exc
    selected_text = result.stdout.strip().lstrip("\ufeff")
    if not selected_text:
        return StoragePathSelection(kind=kind, path=str(current), changed=False)
    selected = Path(selected_text).expanduser().resolve()
    return StoragePathSelection(
        kind=kind, path=str(selected), changed=selected != current,
        has_existing=storage_has_existing(kind),
    )


def _ensure_writable_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    marker = path / f".ytba-write-test-{uuid.uuid4().hex}"
    try:
        marker.write_bytes(b"")
    except OSError as exc:
        raise HTTPException(400, f"目标目录不可写：{exc}") from exc
    finally:
        marker.unlink(missing_ok=True)


def _copy_directory_safely(source: Path, destination: Path) -> None:
    if source.resolve() == destination.resolve():
        return
    temporary = destination.parent / f".ytba-migrate-{uuid.uuid4().hex}"
    if destination.exists():
        raise FileExistsError(f"目标已存在：{destination}")
    try:
        shutil.copytree(source, temporary)
        temporary.replace(destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _migrate_existing(kind: str, source_root: Path, target_root: Path) -> int:
    pairs: list[tuple[Path, Path]] = []
    if kind == "model":
        for model, source in _model_sources(source_root):
            pairs.append((source, target_root / model))
    else:
        for source in _cuda_items(source_root):
            pairs.append((source, target_root / source.name))
    conflict = next((destination for _, destination in pairs if destination.exists()), None)
    if conflict:
        raise FileExistsError(f"目标已存在：{conflict}")
    created: list[Path] = []
    try:
        for source, destination in pairs:
            if source.is_dir():
                _copy_directory_safely(source, destination)
            else:
                shutil.copy2(source, destination)
            created.append(destination)
    except Exception:
        for path in reversed(created):
            shutil.rmtree(path, ignore_errors=True) if path.is_dir() else path.unlink(missing_ok=True)
        raise
    return len(created)


def update_install_directory(update: StoragePathUpdate) -> StoragePathResult:
    target = Path(update.path).expanduser()
    if not target.is_absolute():
        raise HTTPException(400, "安装位置必须是绝对路径")
    target = target.resolve()
    if target.parent == target:
        raise HTTPException(400, "不能直接使用磁盘根目录作为安装位置")
    source = resolve_install_dir(update.kind)
    if source == target:
        return StoragePathResult(kind=update.kind, path=str(target))
    if source in target.parents or target in source.parents:
        raise HTTPException(400, "新旧安装目录不能互相嵌套")
    _ensure_writable_directory(target)
    try:
        migrated_items = _migrate_existing(update.kind, source, target) if update.migrate else 0
    except Exception as exc:
        raise HTTPException(500, f"迁移失败，旧文件已保留：{exc}") from exc

    config = load_config()
    if update.kind == "model":
        config.model_install_dir = str(target)
    else:
        config.cuda_install_dir = str(target)
    save_config(config)
    return StoragePathResult(
        kind=update.kind, path=str(target), migrated=bool(update.migrate and migrated_items),
        migrated_items=migrated_items,
    )


# Moon Begin: remove resumable transfer data without touching valid installations.
def _path_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    size = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                size += item.stat().st_size
        except OSError:
            continue
    return size


def _remove_path(path: Path) -> tuple[int, int]:
    if not path.exists():
        return 0, 0
    files = 1 if path.is_file() else sum(1 for item in path.rglob("*") if item.is_file())
    size = _path_size(path)
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    return files, size


def clear_download_cache(kind: str, model: str = "") -> DownloadCacheResult:
    if kind not in ("model", "cuda"):
        raise HTTPException(400, "未知的缓存类型")
    removed_files = 0
    freed_bytes = 0
    if kind == "cuda":
        targets = [default_model_install_dir().parent / "cuda-runtime-downloads"]
    else:
        if not model.strip():
            raise HTTPException(400, "缺少模型名称")
        model_dir = resolve_install_dir("model") / model.removesuffix(".en").replace("/", "--")
        if not model_dir.is_dir():
            targets = []
        elif _model_directory_valid(model_dir):
            # A complete model may retain Hugging Face metadata; only remove transfer artifacts.
            targets = [model_dir / ".cache"]
        else:
            # This managed directory contains only an incomplete download for the selected model.
            targets = [model_dir]
    for target in targets:
        files, size = _remove_path(target)
        removed_files += files
        freed_bytes += size
    return DownloadCacheResult(
        kind=kind, removed_files=removed_files, freed_bytes=freed_bytes,
    )
# Moon End
# Moon End
