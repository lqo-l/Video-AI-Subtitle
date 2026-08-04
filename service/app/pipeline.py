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
CACHE_SCHEMA_VERSION = 2  # Moon Add: invalidate pre-normalization subtitle caches.


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


def _word_overlap(left: list[str], right: list[str]) -> int:
    """Return the longest suffix/prefix overlap used by YouTube rolling captions."""
    # Moon Add
    limit = min(len(left), len(right))
    for size in range(limit, 0, -1):
        if [x.casefold() for x in left[-size:]] == [x.casefold() for x in right[:size]]:
            return size
    return 0


def _normalize_rolling_captions(captions: list[Segment]) -> list[Segment]:
    """Collapse rolling VTT cues, then create readable sentence-sized timed segments."""
    # Moon Begin
    words: list[tuple[str, float, float]] = []
    for caption in captions:
        current = caption.en.split()
        if not current:
            continue
        previous = [item[0] for item in words]
        overlap = _word_overlap(previous, current)
        new_words = current[overlap:]
        if not new_words:
            continue
        duration = max(caption.end - caption.start, 0.1)
        # Timestamp only newly introduced words across the cue. Existing rolling words
        # keep their first timestamp so repeated VTT windows do not become duplicates.
        for index, word in enumerate(new_words):
            estimated_start = caption.start + duration * index / len(new_words)
            estimated_end = caption.start + duration * (index + 1) / len(new_words)
            start = max(estimated_start, words[-1][2] if words else caption.start)
            end = max(estimated_end, start + 0.01)
            words.append((word, start, end))

    result: list[Segment] = []
    chunk: list[tuple[str, float, float]] = []
    for index, word in enumerate(words):
        chunk.append(word)
        text = " ".join(item[0] for item in chunk)
        sentence_end = bool(re.search(r"[.!?][\"')\]]?$", word[0]))
        next_gap = words[index + 1][1] - word[2] if index + 1 < len(words) else 0
        should_flush = sentence_end or len(chunk) >= 18 or len(text) >= 110 or next_gap >= 1.1
        if should_flush:
            result.append(Segment(start=chunk[0][1], end=chunk[-1][2], en=text))
            chunk = []
    if chunk:
        result.append(Segment(start=chunk[0][1], end=chunk[-1][2], en=" ".join(x[0] for x in chunk)))
    return result
    # Moon End


def _read_vtt(path: Path) -> list[Segment]:
    raw: list[Segment] = []
    for caption in webvtt.read(str(path)):
        text = _clean_caption(caption.text)
        if not text or (raw and raw[-1].en == text):
            continue
        raw.append(Segment(start=_seconds(caption.start), end=_seconds(caption.end), en=text))
    # Moon Modified: YouTube auto captions are rolling windows, not final subtitle lines.
    return _normalize_rolling_captions(raw)


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
    cache_path = CACHE_DIR / f"{video_id}.v{CACHE_SCHEMA_VERSION}.json"
    if cache_path.exists():
        job.state, job.stage, job.progress = "completed", "已从缓存加载", 100
        job.result = ProcessedVideo.model_validate_json(cache_path.read_text(encoding="utf-8"))
        job.preview_segments = job.result.segments
        job.translated_segments = len(job.result.segments)
        job.total_segments = len(job.result.segments)
        job.summary_partial = job.result.summary
        job.summary_state = "completed"
        return

    partial_path = CACHE_DIR / f"{video_id}.partial.v{CACHE_SCHEMA_VERSION}.json"
    segments: list[Segment] = []
    title: str = video_id
    duration: float | None = None
    source: str = ""
    resume: bool = False

    # Try loading from partial cache for resume
    if partial_path.exists():
        try:
            data = json.loads(partial_path.read_text(encoding="utf-8"))
            segments = [Segment(**s) for s in data["segments"]]
            title = data.get("title", video_id)
            duration = data.get("duration")
            source = data.get("source", "resume")
            # Moon Modified: fully translated partial data is still useful when only
            # summarization failed; reuse it instead of downloading/transcribing again.
            resume = bool(segments)
        except Exception:
            segments = []

    if not resume:
        temp = WORK_DIR / job_id
        temp.mkdir(parents=True, exist_ok=True)
        try:
            job.state, job.stage, job.progress = "running", "读取视频信息与字幕", 8
            info, extracted, audio = await asyncio.to_thread(_download, url, temp)
            source = "youtube_subtitles"
            if not extracted:
                job.stage, job.progress = "使用本机 Whisper 转写音频", 25
                config = load_config()
                extracted = await asyncio.to_thread(_transcribe, audio, config.whisper_model, config.device)
                source = "whisper"
            if not extracted:
                raise RuntimeError("未识别到有效英文语音")
            segments = extracted
            title = info.get("title", video_id)
            duration = info.get("duration")
            # Save partial state for crash recovery
            partial = {"title": title, "duration": duration, "source": source,
                        "segments": [s.model_dump() for s in segments]}
            partial_path.write_text(json.dumps(partial, ensure_ascii=False, indent=2), encoding="utf-8")
        finally:
            shutil.rmtree(temp, ignore_errors=True)

    # Translation phase (shared between normal and resume flows)
    job.preview_segments = segments
    job.total_segments = len(segments)
    job.stage, job.progress = f"翻译中文字幕 0 / {len(segments)}", 55

    def publish_translation(completed: int, total: int) -> None:
        job.translated_segments = completed
        job.total_segments = total
        job.progress = min(88, 55 + int(completed / max(total, 1) * 33))
        job.stage = f"翻译中文字幕 {completed} / {total}"
        # Persist after each batch for crash recovery
        try:
            partial = json.loads(partial_path.read_text(encoding="utf-8"))
            partial["segments"] = [s.model_dump() for s in segments]
            partial_path.write_text(json.dumps(partial, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    config = load_config()
    client = LlmClient(config)
    try:
        # Moon Begin: both coroutines receive the extracted English transcript and
        # start before either is awaited. Their state and failures remain independent.
        job.stage = f"翻译中文字幕 0 / {len(segments)}"
        job.summary_state = "running"

        def on_summary_chunk(chunk: str) -> None:
            job.summary_partial = chunk

        async def run_summary() -> tuple[str, list[str]]:
            try:
                value = await client.summarize(title, segments, on_summary_chunk)
                job.summary_state = "completed"
                return value
            except Exception as exc:
                job.summary_state, job.summary_error = "failed", str(exc)
                raise

        translate_task = asyncio.create_task(client.translate(segments, publish_translation))
        summary_task = asyncio.create_task(run_summary())
        translate_result, summary_result = await asyncio.gather(
            translate_task, summary_task, return_exceptions=True
        )

        if isinstance(translate_result, BaseException):
            job.state, job.stage, job.error = "failed", "字幕翻译失败", str(translate_result)
            if isinstance(summary_result, BaseException):
                job.summary_state, job.summary_error = "failed", str(summary_result)
            return

        if isinstance(summary_result, BaseException):
            summary, key_points = "", []
        else:
            summary, key_points = summary_result
        # Moon End
    finally:
        await client.close()

    result = ProcessedVideo(
        video_id=video_id,
        title=title,
        url=url,
        duration=duration,
        source=source,
        segments=segments,
        summary=summary,
        key_points=key_points,
    )
    if job.summary_state == "completed":
        cache_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        partial_path.unlink(missing_ok=True)
    else:
        # Moon Add: keep translated partial data so the next run only retries summary.
        partial = {"title": title, "duration": duration, "source": source,
                   "segments": [s.model_dump() for s in segments]}
        partial_path.write_text(json.dumps(partial, ensure_ascii=False, indent=2), encoding="utf-8")
    job.result = result
    job.preview_segments = segments
    job.translated_segments = len(segments)
    job.total_segments = len(segments)
    final_stage = "字幕完成，摘要生成失败" if job.summary_state == "failed" else "处理完成，请手动播放"
    job.state, job.stage, job.progress = "completed", final_stage, 100

def create_job(url: str) -> JobView:
    job_id = uuid.uuid4().hex
    job = JobView(id=job_id, state="queued", stage="等待处理", progress=0)
    JOBS[job_id] = job
    asyncio.create_task(process_job(job_id, url))
    return job
