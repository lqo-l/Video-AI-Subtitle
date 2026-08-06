from __future__ import annotations

import re
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from .config import CACHE_DIR, ensure_dirs, load_config, save_config
from .models import CudaRuntimeStatus, JobView, ModelStatus, PublicConfig, ServiceConfig, VideoRequest
from .pipeline import (
    JOBS, cancel_job, cancel_model_download, create_job, get_cuda_runtime_status,
    get_model_status, pause_job, resume_job, start_cuda_runtime_install, start_model_download,
)


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


@app.delete("/cache")
def clear_cache():
    # Moon Add: remove generated video results without touching API settings.
    ensure_dirs()
    removed = 0
    for path in CACHE_DIR.glob("*.json"):
        if path.is_file():
            path.unlink()
            removed += 1
    return {"ok": True, "removed": removed}


@app.get("/config", response_model=PublicConfig)
def get_config():
    cfg = load_config()
    return PublicConfig(**cfg.model_dump(exclude={"api_key"}), api_key_configured=bool(cfg.api_key))


@app.put("/config", response_model=PublicConfig)
def put_config(config: ServiceConfig):
    if not re.match(r"^https?://", config.base_url):
        raise HTTPException(400, "Base URL 必须以 http:// 或 https:// 开头")
    # Moon Add: an empty value means keeping the existing secret.
    if not config.api_key:
        config.api_key = load_config().api_key
    save_config(config)
    return PublicConfig(**config.model_dump(exclude={"api_key"}), api_key_configured=bool(config.api_key))


@app.post("/jobs", response_model=JobView)
async def start_job(request: VideoRequest):  # Moon Modified: keep task creation on the server event loop.
    url = str(request.url)
    hostname = (urlparse(url).hostname or "").lower()
    if hostname not in ("youtu.be", "youtube.com", "www.youtube.com", "bilibili.com", "www.bilibili.com"):
        raise HTTPException(400, "仅支持 YouTube 或 Bilibili 视频链接")
    return create_job(str(request.url))


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
def model_status(model: str | None = None, model_path: str | None = None):
    # Moon Modified: inspect the current settings-page selection before it is saved.
    return get_model_status(model, model_path)


@app.post("/models/download", response_model=ModelStatus)
async def model_download(
    model: str | None = None, model_path: str | None = None,
    source: str | None = None,
):
    # Moon Modified: download the visible selection rather than stale saved config.
    return start_model_download(model, model_path, source)


@app.post("/models/download/cancel", response_model=ModelStatus)
def model_download_cancel():
    return cancel_model_download()


@app.get("/cuda/status", response_model=CudaRuntimeStatus)
def cuda_status():
    return get_cuda_runtime_status()


@app.post("/cuda/install", response_model=CudaRuntimeStatus)
async def cuda_install():
    return start_cuda_runtime_install()
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
