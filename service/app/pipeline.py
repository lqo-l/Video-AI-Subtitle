from __future__ import annotations

import asyncio
import html
import json
import re
import shutil
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import webvtt
import yt_dlp
from faster_whisper import WhisperModel

from .config import CACHE_DIR, WORK_DIR, load_config
from .llm import LlmClient
from .models import JobView, ProcessedVideo, Segment


JOBS: dict[str, JobView] = {}


def video_id_from_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.hostname == "youtu.be":
        return parsed.path.strip("/")
    return parse_qs(parsed.query).get("v", [""])[0]


def _clean_caption(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", html.unescape(text))
    return " ".join(text.replace("\n", " ").split())


def _seconds(value: str) -> float:
    parts = value.replace(",", ".").split(":")
    return float(parts[-1]) + int(parts[-2]) * 60 + int(parts[-3]) * 3600


def _read_vtt(path: Path) -> list[Segment]:
    result: list[Segment] = []
    for caption in webvtt.read(str(path)):
        text = _clean_caption(caption.text)
        if not text or (result and result[-1].en == text):
            continue
        result.append(Segment(start=_seconds(caption.start), end=_seconds(caption.end), en=text))
    return result


def _download(url: str, directory: Path) -> tuple[dict, list[Segment], Path | None]:
    common = {"quiet": True, "no_warnings": True, "noplaylist": True, "paths": {"home": str(directory)}}
    with yt_dlp.YoutubeDL(common) as ydl:
        info = ydl.extract_info(url, download=False)
    captions = {**(info.get("automatic_captions", {}) or {}), **(info.get("subtitles", {}) or {})}
    english = next((key for key in ("en", "en-US", "en-GB") if key in captions), None)
    if english:
        options = common | {
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": [english],
            "subtitlesformat": "vtt",
            "outtmpl": str(directory / "%(id)s.%(ext)s"),
        }
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([url])
        vtt = next(directory.glob("*.vtt"), None)
        if vtt:
            return info, _read_vtt(vtt), None

    options = common | {
        "format": "bestaudio/best",
        "outtmpl": str(directory / "audio.%(ext)s"),
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "wav", "preferredquality": "160"}],
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        ydl.download([url])
    audio = directory / "audio.wav"
    if not audio.exists():
        raise RuntimeError("音频下载或 FFmpeg 转换失败")
    return info, [], audio


def _transcribe(audio: Path, model_name: str, device_setting: str) -> list[Segment]:
    import ctranslate2

    device = device_setting
    if device == "auto":
        device = "cuda" if ctranslate2.get_cuda_device_count() else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"
    try:
        model = WhisperModel(model_name, device=device, compute_type=compute_type)
    except Exception:
        if device_setting != "auto" or device == "cpu":
            raise
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
    items, _ = model.transcribe(str(audio), language="en", vad_filter=True, beam_size=5)
    return [Segment(start=x.start, end=x.end, en=x.text.strip()) for x in items if x.text.strip()]


async def process_job(job_id: str, url: str) -> None:
    job = JOBS[job_id]
    video_id = video_id_from_url(url)
    cache_path = CACHE_DIR / f"{video_id}.json"
    if cache_path.exists():
        job.state, job.stage, job.progress = "completed", "已从缓存加载", 100
        job.result = ProcessedVideo.model_validate_json(cache_path.read_text(encoding="utf-8"))
        # Moon Add: cached jobs expose the same completed incremental state.
        job.preview_segments = job.result.segments
        job.translated_segments = len(job.result.segments)
        job.total_segments = len(job.result.segments)
        return
    temp = WORK_DIR / job_id
    temp.mkdir(parents=True, exist_ok=True)
    try:
        job.state, job.stage, job.progress = "running", "读取视频信息与字幕", 8
        info, segments, audio = await asyncio.to_thread(_download, url, temp)
        source = "youtube_subtitles"
        if not segments:
            job.stage, job.progress = "使用本机 Whisper 转写音频", 25
            config = load_config()
            segments = await asyncio.to_thread(_transcribe, audio, config.whisper_model, config.device)
            source = "whisper"
        if not segments:
            raise RuntimeError("未识别到有效英文语音")
        # Moon Begin: make translated batches visible before the full job completes.
        job.preview_segments = segments
        job.total_segments = len(segments)
        job.stage, job.progress = f"翻译中文字幕 0 / {len(segments)}", 55

        def publish_translation(completed: int, total: int) -> None:
            job.translated_segments = completed
            job.total_segments = total
            job.progress = min(88, 55 + int(completed / max(total, 1) * 33))
            job.stage = f"翻译中文字幕 {completed} / {total}"
        # Moon End

        config = load_config()
        client = LlmClient(config)
        try:
            await client.translate(segments, publish_translation)
            job.stage, job.progress = "生成摘要与关键点", 92
            summary, key_points = await client.summarize(info.get("title", video_id), segments)
        finally:
            await client.close()
        result = ProcessedVideo(
            video_id=video_id,
            title=info.get("title", video_id),
            url=url,
            duration=info.get("duration"),
            source=source,
            segments=segments,
            summary=summary,
            key_points=key_points,
        )
        cache_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        job.result = result
        job.preview_segments = segments
        job.translated_segments = len(segments)
        job.total_segments = len(segments)
        job.state, job.stage, job.progress = "completed", "处理完成，请手动播放", 100
    except Exception as exc:
        job.state, job.stage, job.error = "failed", "处理失败", str(exc)
    finally:
        shutil.rmtree(temp, ignore_errors=True)


def create_job(url: str) -> JobView:
    job_id = uuid.uuid4().hex
    job = JobView(id=job_id, state="queued", stage="等待处理", progress=0)
    JOBS[job_id] = job
    asyncio.create_task(process_job(job_id, url))
    return job
