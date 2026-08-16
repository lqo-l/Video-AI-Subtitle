from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from .config import CACHE_DIR, ensure_dirs, load_config, resolve_install_dir, save_config
from .models import (
    CudaRuntimeStatus, DownloadCacheResult, JobView, ModelStatus, PublicConfig, ServiceConfig,
    StoragePathResult, StoragePathSelection, StoragePathUpdate, VideoRequest,
)
from .pipeline import (
    JOBS, cancel_cuda_runtime_install, cancel_job, cancel_model_download, create_job,
    cuda_install_worker_active, get_cuda_runtime_status, get_model_status,
    model_download_worker_active, pause_job, resume_job,
    start_cuda_runtime_install, start_model_download,
)
from .storage import (
    clear_download_cache, default_install_directory, select_install_directory,
    update_install_directory,
)
from .prompts import ensure_prompt_file, prompt_path, restore_default_prompt
from .diagnostics import LOG_DIR, log_event


app = FastAPI(title="Video Bilingual Assistant", version="0.2.0")


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://www.youtube.com", "https://youtube.com",
        "https://www.bilibili.com", "https://bilibili.com",
    ],
    allow_origin_regex=r"chrome-extension://.*",
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"ok": True, "version": app.version}


@app.get("/prompts")
def get_prompt_paths():
    return {kind: str(ensure_prompt_file(kind)) for kind in ("translation", "summary")}


@app.post("/prompts/{kind}/restore")
def restore_prompt(kind: str):
    return {"path": str(restore_default_prompt(kind))}


@app.post("/prompts/open")
def open_prompts_folder():
    path = ensure_prompt_file("summary").parent
    try:
        os.startfile(str(path))
    except OSError as exc:
        raise HTTPException(500, f"无法打开提示词文件夹：{exc}") from exc
    return {"ok": True}


@app.delete("/cache")
def clear_cache():
    # Moon Add: remove generated video results without touching API settings.
    ensure_dirs()
    removed = 0
    for path in CACHE_DIR.glob("*.json"):
        if path.is_file():
            path.unlink()
            removed += 1
    log_event("subtitle_cache_cleared", removed=removed)
    return {"ok": True, "removed": removed}


@app.get("/config", response_model=PublicConfig)
def get_config():
    cfg = load_config()
    public = cfg.model_dump(exclude={"api_key"})
    public["model_install_dir"] = str(resolve_install_dir("model", cfg))
    public["cuda_install_dir"] = str(resolve_install_dir("cuda", cfg))
    return PublicConfig(**public, api_key_configured=bool(cfg.api_key))


@app.put("/config", response_model=PublicConfig)
def put_config(config: ServiceConfig):
    if not re.match(r"^https?://", config.base_url):
        raise HTTPException(400, "Base URL 必须以 http:// 或 https:// 开头")
    # Moon Add: an empty value means keeping the existing secret.
    if not config.api_key:
        config.api_key = load_config().api_key
    for value in (config.model_install_dir, config.cuda_install_dir):
        if value and not Path(value).expanduser().is_absolute():
            raise HTTPException(400, "安装位置必须是绝对路径")
    save_config(config)
    log_event("settings_saved", device=config.device, whisper_model=config.whisper_model)
    return PublicConfig(**config.model_dump(exclude={"api_key"}), api_key_configured=bool(config.api_key))


@app.post("/jobs", response_model=JobView)
async def start_job(request: VideoRequest):  # Moon Modified: keep task creation on the server event loop.
    url = str(request.url)
    hostname = (urlparse(url).hostname or "").lower()
    if hostname not in ("youtu.be", "youtube.com", "www.youtube.com", "bilibili.com", "www.bilibili.com"):
        raise HTTPException(400, "仅支持 YouTube 或 Bilibili 视频链接")
    job = create_job(
        str(request.url), request.page_subtitles, request.page_subtitle_language,
    )
    job_id = job.id if hasattr(job, "id") else job.get("id", "")
    log_event("job_requested", job_id=job_id, hostname=hostname, has_page_subtitles=bool(request.page_subtitles))
    return job


@app.get("/jobs/{job_id}", response_model=JobView)
def get_job(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(404, "任务不存在")
    return JOBS[job_id]


# Moon Begin: explicit task lifecycle controls.
def _require_job(job_id: str) -> None:
    if job_id not in JOBS:
        raise HTTPException(404, "任务不存在")


@app.post("/jobs/{job_id}/pause", response_model=JobView)
def pause(job_id: str):
    _require_job(job_id)
    return pause_job(job_id)


@app.post("/jobs/{job_id}/resume", response_model=JobView)
def resume(job_id: str):
    _require_job(job_id)
    return resume_job(job_id)


@app.post("/jobs/{job_id}/cancel", response_model=JobView)
def cancel(job_id: str):
    _require_job(job_id)
    return cancel_job(job_id)


@app.get("/models/status", response_model=ModelStatus)
def model_status(
    model: str | None = None, model_path: str | None = None,
    install_dir: str | None = None,
):
    # Moon Modified: inspect the current settings-page selection before it is saved.
    return get_model_status(model, model_path, install_dir)


@app.post("/models/download", response_model=ModelStatus)
async def model_download(
    model: str | None = None, model_path: str | None = None,
    source: str | None = None, install_dir: str | None = None,
):
    # Moon Modified: download the visible selection rather than stale saved config.
    return start_model_download(model, model_path, source, install_dir)


@app.post("/models/download/cancel", response_model=ModelStatus)
def model_download_cancel():
    log_event("model_download_cancel_requested")
    return cancel_model_download()


def _open_local_directory(path_value: str, label: str) -> dict[str, bool]:
    # Moon Add: the UI chooses a semantic resource; it cannot pass an arbitrary path.
    path = Path(path_value).resolve() if path_value else None
    if not path or not path.is_dir():
        raise HTTPException(404, f"{label}目录不存在")
    if not hasattr(os, "startfile"):
        raise HTTPException(501, "当前系统不支持打开文件夹")
    # Moon Modified: use the native shell action only; no background activation helper.
    os.startfile(str(path))
    return {"ok": True}


@app.post("/models/open")
def model_open(
    model: str | None = None, model_path: str | None = None,
    install_dir: str | None = None,
):
    status = get_model_status(model, model_path, install_dir)
    if not status.valid:
        raise HTTPException(409, "当前模型尚不可用")
    return _open_local_directory(status.resolved_path, "模型")


@app.get("/cuda/status", response_model=CudaRuntimeStatus)
def cuda_status():
    return get_cuda_runtime_status()


@app.post("/cuda/install", response_model=CudaRuntimeStatus)
async def cuda_install():
    log_event("cuda_install_requested")
    return start_cuda_runtime_install()


@app.post("/cuda/install/cancel", response_model=CudaRuntimeStatus)
def cuda_install_cancel():
    # Moon Add: cancellation preserves completed wheel bytes for a later resume.
    log_event("cuda_install_cancel_requested")
    return cancel_cuda_runtime_install()


@app.post("/diagnostics/open")
def diagnostics_open():
    # Moon Add: troubleshooting should be reachable without exposing arbitrary paths.
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.startfile(str(LOG_DIR))
    except OSError as exc:
        raise HTTPException(500, f"无法打开诊断日志文件夹：{exc}") from exc
    log_event("diagnostics_folder_opened")
    return {"ok": True, "path": str(LOG_DIR)}


# Moon Begin: native folder selection and confirmed storage migration.
@app.post("/storage/select", response_model=StoragePathSelection)
def storage_select(kind: str):
    return select_install_directory(kind)


@app.get("/storage/default", response_model=StoragePathSelection)
def storage_default(kind: str):
    return default_install_directory(kind)


@app.put("/storage/path", response_model=StoragePathResult)
def storage_update(update: StoragePathUpdate):
    if update.kind == "model" and get_model_status().state == "running":
        raise HTTPException(409, "模型正在下载，暂时不能更改安装位置")
    if update.kind == "cuda" and get_cuda_runtime_status().state == "running":
        raise HTTPException(409, "GPU 运行库正在配置，暂时不能更改安装位置")
    return update_install_directory(update)


@app.delete("/storage/download-cache", response_model=DownloadCacheResult)
def storage_cache_clear(kind: str, model: str = ""):
    if kind == "model" and model_download_worker_active():
        raise HTTPException(409, "模型下载仍在停止，请稍后再清理")
    if kind == "cuda" and cuda_install_worker_active():
        raise HTTPException(409, "GPU 下载仍在停止，请稍后再清理")
    return clear_download_cache(kind, model)
# Moon End


@app.post("/cuda/open")
def cuda_open():
    status = get_cuda_runtime_status()
    if not status.valid:
        raise HTTPException(409, "GPU 运行库尚未配置")
    return _open_local_directory(status.path, "GPU 运行库")
# Moon End


@app.get("/jobs/{job_id}/markdown", response_class=PlainTextResponse)
def export_markdown(job_id: str):
    job = JOBS.get(job_id)
    if not job or not job.result:
        raise HTTPException(404, "结果尚未生成")
    result = job.result
    lines = [f"# {result.title}", "", f"来源：{result.url}", "", "## 摘要", "", result.summary, "", "## 关键点", ""]
    lines.extend(f"- {point}" for point in result.key_points)
    lines.extend(["", "## 原文与中文字幕", ""])
    for item in result.segments:
        minutes, seconds = divmod(int(item.start), 60)
        lines.extend([f"### {minutes:02d}:{seconds:02d}", "", item.en, ""])
        if result.source_language != "zh":
            lines.extend([item.zh, ""])
    return "\n".join(lines)
