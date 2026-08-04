from __future__ import annotations

import re

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from .config import CACHE_DIR, ensure_dirs, load_config, save_config
from .models import JobView, PublicConfig, ServiceConfig, VideoRequest
from .pipeline import JOBS, create_job


app = FastAPI(title="YouTube Bilingual Assistant", version="0.1.0")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://www.youtube.com", "https://youtube.com"],
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
    if "youtube.com" not in str(request.url) and "youtu.be" not in str(request.url):
        raise HTTPException(400, "仅支持 YouTube 视频链接")
    return create_job(str(request.url))


@app.get("/jobs/{job_id}", response_model=JobView)
def get_job(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(404, "任务不存在")
    return JOBS[job_id]


@app.get("/jobs/{job_id}/markdown", response_class=PlainTextResponse)
def export_markdown(job_id: str):
    job = JOBS.get(job_id)
    if not job or not job.result:
        raise HTTPException(404, "结果尚未生成")
    result = job.result
    lines = [f"# {result.title}", "", f"来源：{result.url}", "", "## 摘要", "", result.summary, "", "## 关键点", ""]
    lines.extend(f"- {point}" for point in result.key_points)
    lines.extend(["", "## 中英字幕", ""])
    for item in result.segments:
        minutes, seconds = divmod(int(item.start), 60)
        lines.extend([f"### {minutes:02d}:{seconds:02d}", "", item.en, "", item.zh, ""])
    return "\n".join(lines)
