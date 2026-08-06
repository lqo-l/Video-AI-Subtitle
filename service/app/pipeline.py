from __future__ import annotations

import asyncio
import html
import json
import re
import shutil
import uuid
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlparse

import webvtt
import yt_dlp
from faster_whisper import WhisperModel

from .config import CACHE_DIR, WORK_DIR, load_config
from .llm import LlmClient
from .models import JobView, ProcessedVideo, Segment


JOBS: dict[str, JobView] = {}
CACHE_SCHEMA_VERSION = 2  # Moon Add: invalidate pre-normalization subtitle caches.
SUPPORTED_LANGUAGES = ("en", "ja", "zh")


def _write_json_atomic(path: Path, data: dict) -> None:
    """Write checkpoint JSON without exposing a half-written file after interruption."""
    # Moon Add
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def video_id_from_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.hostname and parsed.hostname.endswith("bilibili.com"):
        match = re.search(r"/(BV[0-9A-Za-z]+|av\d+|(?:ep|ss)\d+)", parsed.path, re.IGNORECASE)
        return match.group(1) if match else ""
    if parsed.hostname == "youtu.be":
        return parsed.path.strip("/")
    return parse_qs(parsed.query).get("v", [""])[0]


def platform_from_url(url: str) -> str:
    hostname = (urlparse(url).hostname or "").lower()
    return "bilibili" if hostname.endswith("bilibili.com") else "youtube"


def cache_key_from_url(url: str) -> str:
    """Namespace cache IDs by site and Bilibili part number."""
    # Moon Add
    platform = platform_from_url(url)
    video_id = video_id_from_url(url)
    if platform == "bilibili":
        page = parse_qs(urlparse(url).query).get("p", ["1"])[0]
        return f"bilibili_{video_id}_p{page}"
    return video_id  # Moon Modified: preserve existing YouTube cache filenames.


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
    language = captions[0].source_language if captions else "en"
    cjk = language in ("ja", "zh")
    for caption in captions:
        current = [char for char in caption.en if not char.isspace()] if cjk else caption.en.split()
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
        separator = "" if cjk else " "
        text = separator.join(item[0] for item in chunk)
        sentence_end = bool(re.search(
            r"[。！？!?][」』）】\"')\]]?$" if cjk else r"[.!?][\"')\]]?$",
            word[0],
        ))
        next_gap = words[index + 1][1] - word[2] if index + 1 < len(words) else 0
        max_units = 36 if cjk else 18
        max_chars = 54 if cjk else 110
        should_flush = sentence_end or len(chunk) >= max_units or len(text) >= max_chars or next_gap >= 1.1
        if should_flush:
            result.append(Segment(
                start=chunk[0][1], end=chunk[-1][2], en=text,
                source_language=language,
            ))
            chunk = []
    if chunk:
        result.append(Segment(
            start=chunk[0][1], end=chunk[-1][2],
            en=("" if cjk else " ").join(x[0] for x in chunk), source_language=language,
        ))
    return result
    # Moon End


def _read_subtitle(path: Path, language: str, rolling: bool = False) -> list[Segment]:
    """Read VTT/SRT captions while preserving their declared source language."""
    # Moon Begin
    raw: list[Segment] = []
    captions = webvtt.from_srt(str(path)) if path.suffix.lower() == ".srt" else webvtt.read(str(path))
    for caption in captions:
        text = _clean_caption(caption.text)
        if not text or (raw and raw[-1].en == text):
            continue
        raw.append(Segment(
            start=_seconds(caption.start), end=_seconds(caption.end), en=text,
            source_language=language,
        ))
    return _normalize_rolling_captions(raw) if rolling else raw
    # Moon End


def _caption_language(key: str) -> str | None:
    normalized = key.lower().replace("_", "-")
    if normalized == "danmaku":
        return None
    if normalized.startswith(("en", "ai-en")):
        return "en"
    if normalized.startswith(("ja", "jp", "ai-ja", "ai-jp")):
        return "ja"
    if normalized.startswith(("zh", "cn", "ai-zh", "ai-cn")):
        return "zh"
    return None


def _select_caption(captions: dict) -> tuple[str, str] | None:
    """Prefer translatable English/Japanese captions, then native Chinese."""
    # Moon Add
    candidates = []
    for key in captions:
        language = _caption_language(key)
        if language:
            candidates.append((SUPPORTED_LANGUAGES.index(language), key, language))
    if not candidates:
        return None
    _, key, language = min(candidates)
    return key, language


def _download(url: str, directory: Path) -> tuple[dict, list[Segment], Path | None]:
    common = {"quiet": True, "no_warnings": True, "noplaylist": True, "paths": {"home": str(directory)}}
    with yt_dlp.YoutubeDL(common) as ydl:
        info = ydl.extract_info(url, download=False)
    captions = {**(info.get("automatic_captions", {}) or {}), **(info.get("subtitles", {}) or {})}
    selected = _select_caption(captions)
    if selected:
        subtitle_key, language = selected
        options = common | {
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": [subtitle_key],
            "subtitlesformat": "vtt/srt/best",
            "outtmpl": str(directory / "%(id)s.%(ext)s"),
        }
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([url])
        subtitle = next((path for path in directory.iterdir() if path.suffix.lower() in (".vtt", ".srt")), None)
        if subtitle:
            platform = platform_from_url(url)
            info["_ytba_language"] = language
            info["_ytba_source"] = f"{platform}_subtitles"
            rolling = platform == "youtube" and language in ("en", "ja")
            return info, _read_subtitle(subtitle, language, rolling=rolling), None

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


def _prepare_whisper_model(
    model_name: str, progress_callback: Callable[[int], None] | None = None
) -> str:
    """Download selected model once and report byte-based first-run progress."""
    # Moon Begin
    from huggingface_hub import snapshot_download
    from huggingface_hub.errors import LocalEntryNotFoundError
    from faster_whisper.utils import download_model
    from tqdm.auto import tqdm

    model_name = model_name.removesuffix(".en")
    repo_id = model_name if "/" in model_name else f"Systran/faster-whisper-{model_name}"
    # A complete standard cache must never perform a network metadata request.
    try:
        cached_path = download_model(model_name, local_files_only=True)
        if progress_callback:
            progress_callback(100)
        return str(cached_path)
    except (LocalEntryNotFoundError, OSError):
        pass

    legacy_model_dir = CACHE_DIR.parent / "models" / model_name.replace("/", "--")
    expected = ("config.json", "model.bin", "tokenizer.json")
    if all((legacy_model_dir / name).exists() for name in expected):
        if progress_callback:
            progress_callback(100)
        return str(legacy_model_dir)

    allow_patterns = [
        "config.json", "preprocessor_config.json", "model.bin",
        "tokenizer.json", "vocabulary.*",
    ]
    reported_percent = 0

    class DownloadProgress(tqdm):
        """Forward Hugging Face's aggregate byte progress to the job view."""
        def __init__(self, *args, **kwargs):
            kwargs["disable"] = True
            super().__init__(*args, **kwargs)

        def update(self, amount=1):
            nonlocal reported_percent
            result = super().update(amount)
            if progress_callback and self.total:
                percent = min(99, int(self.n * 100 / self.total))
                if percent > reported_percent:
                    reported_percent = percent
                    progress_callback(percent)
            return result

    # Moon Modified: new downloads use faster-whisper's standard cache. If the
    # previous release already wrote a partial legacy copy, resume that copy so
    # the user does not lose hundreds of megabytes of download progress.
    if progress_callback:
        progress_callback(0)
    download_options = {
        "allow_patterns": allow_patterns,
        "tqdm_class": DownloadProgress,
    }
    if legacy_model_dir.exists() and any(legacy_model_dir.iterdir()):
        download_options["local_dir"] = legacy_model_dir
    model_path = snapshot_download(repo_id, **download_options)
    if progress_callback:
        progress_callback(100)
    return str(model_path)
    # Moon End


def _transcribe(
    audio: Path,
    model_name: str,
    device_setting: str,
    download_progress: Callable[[int], None] | None = None,
) -> tuple[list[Segment], str]:
    import ctranslate2

    model_name = model_name.removesuffix(".en")  # Moon Add: require multilingual weights.
    model_path = _prepare_whisper_model(model_name, download_progress)  # Moon Add
    device = device_setting
    if device == "auto":
        device = "cuda" if ctranslate2.get_cuda_device_count() else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"
    try:
        model = WhisperModel(model_path, device=device, compute_type=compute_type)
    except Exception:
        if device_setting != "auto" or device == "cpu":
            raise
        model = WhisperModel(model_path, device="cpu", compute_type="int8")
    items, info = model.transcribe(str(audio), language=None, vad_filter=True, beam_size=5)
    language = info.language if info.language in SUPPORTED_LANGUAGES else ""
    if not language:
        raise RuntimeError(f"仅支持英文、日文或中文语音，检测到：{info.language or '未知'}")
    return [
        Segment(start=x.start, end=x.end, en=x.text.strip(), source_language=language)
        for x in items if x.text.strip()
    ], language


async def process_job(job_id: str, url: str) -> None:
    job = JOBS[job_id]
    video_id = video_id_from_url(url)
    platform = platform_from_url(url)
    job.platform = platform
    cache_key = cache_key_from_url(url)
    cache_path = CACHE_DIR / f"{cache_key}.v{CACHE_SCHEMA_VERSION}.json"
    if cache_path.exists():
        job.state, job.stage, job.progress = "completed", "已从缓存加载", 100
        job.result = ProcessedVideo.model_validate_json(cache_path.read_text(encoding="utf-8"))
        job.preview_segments = job.result.segments
        job.platform = job.result.platform
        job.source_language = job.result.source_language
        job.translated_segments = len(job.result.segments)
        job.total_segments = len(job.result.segments)
        job.summary_partial = job.result.summary
        job.summary_state = "completed"
        return

    partial_path = CACHE_DIR / f"{cache_key}.partial.v{CACHE_SCHEMA_VERSION}.json"
    segments: list[Segment] = []
    title: str = video_id
    duration: float | None = None
    source: str = ""
    source_language: str = "en"
    resume: bool = False
    saved_summary_partial: str = ""
    saved_summary: str = ""
    saved_key_points: list[str] = []
    current_summary: str = ""
    current_key_points: list[str] = []
    summary_already_completed = False

    # Try loading from partial cache for resume
    if partial_path.exists():
        try:
            data = json.loads(partial_path.read_text(encoding="utf-8"))
            segments = [Segment(**s) for s in data["segments"]]
            title = data.get("title", video_id)
            duration = data.get("duration")
            source = data.get("source", "resume")
            platform = data.get("platform", platform)
            source_language = data.get(
                "source_language", segments[0].source_language if segments else "en"
            )
            saved_summary_partial = data.get("summary_partial", "")
            saved_summary = data.get("summary", "")
            saved_key_points = [str(x) for x in data.get("key_points", [])]
            current_summary = saved_summary
            current_key_points = saved_key_points
            summary_already_completed = data.get("summary_state") == "completed"
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
            source = info.get("_ytba_source", f"{platform}_subtitles")
            source_language = info.get("_ytba_language", "en")
            if not extracted:
                config = load_config()
                # Moon Begin: distinguish first-run model download from transcription.
                def report_model_download(percent: int) -> None:
                    if percent >= 100:
                        job.stage, job.progress = "正在识别语音", 45
                    else:
                        suffix = "（正在连接模型仓库）" if percent == 0 else ""
                        job.stage = f"正在下载语音模型 {percent}%{suffix}"
                        job.progress = 25 + round(percent * 0.2)

                job.stage, job.progress = "正在下载语音模型 0%（正在连接模型仓库）", 25
                extracted, source_language = await asyncio.to_thread(
                    _transcribe, audio, config.whisper_model, config.device,
                    report_model_download,
                )
                # Moon End
                source = "whisper"
            if not extracted:
                raise RuntimeError("未识别到有效字幕或语音")
            if source_language == "zh":
                for segment in extracted:
                    segment.zh = segment.en
            segments = extracted
            title = info.get("title", video_id)
            duration = info.get("duration")
            # Save partial state for crash recovery
            _write_json_atomic(partial_path, {
                "title": title, "duration": duration, "source": source,
                "platform": platform, "source_language": source_language,
                "segments": [s.model_dump() for s in segments],
                "summary_partial": "", "summary_state": "idle",
                "summary": "", "key_points": [],
            })
        finally:
            shutil.rmtree(temp, ignore_errors=True)

    # Translation phase (shared between normal and resume flows)
    # Moon Add: resumed jobs bypass extraction, so explicitly leave the queued state.
    job.state = "running"
    job.preview_segments = segments
    job.platform = platform
    job.source_language = source_language
    job.total_segments = len(segments)
    job.stage, job.progress = f"翻译中文字幕 0 / {len(segments)}", 55
    job.translated_segments = sum(1 for segment in segments if segment.zh)
    job.summary_partial = saved_summary_partial
    if summary_already_completed:
        job.summary_state = "completed"

    def persist_checkpoint(
        summary_state: str | None = None,
        summary: str | None = None,
        key_points: list[str] | None = None,
    ) -> None:
        # Moon Add: extraction, translation and summary share one atomic checkpoint.
        _write_json_atomic(partial_path, {
            "title": title,
            "duration": duration,
            "source": source,
            "platform": platform,
            "source_language": source_language,
            "segments": [segment.model_dump() for segment in segments],
            "summary_partial": job.summary_partial,
            "summary_state": summary_state or job.summary_state,
            "summary": current_summary if summary is None else summary,
            "key_points": current_key_points if key_points is None else key_points,
        })

    def publish_translation(completed: int, total: int) -> None:
        job.translated_segments = completed
        job.total_segments = total
        job.progress = min(88, 55 + int(completed / max(total, 1) * 33))
        job.stage = f"翻译中文字幕 {completed} / {total}"
        try:
            persist_checkpoint()
        except Exception:
            pass

    config = load_config()
    client = LlmClient(config)
    try:
        # Moon Begin: both coroutines receive the extracted original transcript and
        # start before either is awaited. Their state and failures remain independent.
        job.stage = f"翻译中文字幕 0 / {len(segments)}"
        if not summary_already_completed:
            job.summary_state = "running"

        def on_summary_chunk(chunk: str) -> None:
            job.summary_partial = chunk
            try:
                persist_checkpoint(summary_state="running")
            except Exception:
                pass

        async def run_summary() -> tuple[str, list[str]]:
            nonlocal current_summary, current_key_points
            if summary_already_completed:
                return saved_summary, saved_key_points
            try:
                value = await client.summarize(
                    title, segments, on_summary_chunk, resume_from=saved_summary_partial
                )
                job.summary_state = "completed"
                current_summary, current_key_points = value
                persist_checkpoint(
                    summary_state="completed", summary=value[0], key_points=value[1]
                )
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
        platform=platform,
        source_language=source_language,
        segments=segments,
        summary=summary,
        key_points=key_points,
    )
    if job.summary_state == "completed":
        cache_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        partial_path.unlink(missing_ok=True)
    else:
        # Moon Add: keep translated partial data so the next run only retries summary.
        persist_checkpoint(summary_state="failed")
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
