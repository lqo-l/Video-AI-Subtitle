from __future__ import annotations

import asyncio
import ctypes
import html
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlparse

import webvtt
import yt_dlp
from faster_whisper import WhisperModel

from .config import CACHE_DIR, WORK_DIR, load_config, resolve_install_dir
from .llm import LlmClient
from .models import CudaRuntimeStatus, JobView, LocalModelInfo, ModelStatus, ProcessedVideo, Segment


JOBS: dict[str, JobView] = {}
JOB_TASKS: dict[str, asyncio.Task] = {}  # Moon Add
JOB_CONTROLS: dict[str, "JobControl"] = {}  # Moon Add
MODEL_DOWNLOAD: ModelStatus | None = None  # Moon Add
MODEL_DOWNLOAD_TASK: asyncio.Task | None = None  # Moon Add
MODEL_DOWNLOAD_CANCEL = threading.Event()  # Moon Add
CUDA_INSTALL: CudaRuntimeStatus | None = None  # Moon Add
CUDA_INSTALL_TASK: asyncio.Task | None = None  # Moon Add
CUDA_INSTALL_CANCEL = threading.Event()  # Moon Add
CUDA_DLL_HANDLES: list = []  # Moon Add: keep Windows DLL directory cookies alive.
CUDA_DLL_PATHS: set[str] = set()  # Moon Add
CUDA_PRELOADED: list = []  # Moon Add: keep explicit WinDLL module handles alive.
CUDA_PRELOADED_PATHS: set[str] = set()  # Moon Add
CUDA_PACKAGES = (
    ("nvidia-cublas-cu12", "cuBLAS 12"),
    ("nvidia-cudnn-cu12", "cuDNN 9"),
    ("nvidia-cuda-nvrtc-cu12", "CUDA NVRTC 12"),
)  # Moon Add
CACHE_SCHEMA_VERSION = 2  # Moon Add: invalidate pre-normalization subtitle caches.
SUPPORTED_LANGUAGES = ("en", "ja", "zh")
WHISPER_MODEL_ENDPOINTS = (
    ("HF 镜像", "https://hf-mirror.com"),
    ("Hugging Face 官方源", "https://huggingface.co"),
)  # Moon Add: prefer the mainland-friendly mirror and fall back automatically.


class DownloadCancelled(Exception):
    """Moon Add: cooperative stop signal raised inside blocking download workers."""


def _raise_if_cancelled(cancel_event: threading.Event | None) -> None:
    if cancel_event and cancel_event.is_set():
        raise DownloadCancelled()


def _model_install_root(install_dir: str = "") -> Path:
    # Moon Add: keep the legacy cache-relative default testable while allowing an override.
    return (
        Path(install_dir).expanduser().resolve()
        if install_dir.strip() else (CACHE_DIR.parent / "models").resolve()
    )


def _uses_default_model_root(install_dir: str = "") -> bool:
    return _model_install_root(install_dir) == (CACHE_DIR.parent / "models").resolve()


def _configure_private_cuda_runtime() -> list[str]:
    """Expose optional NVIDIA wheels installed inside this project's venv."""
    # Moon Begin
    if sys.platform != "win32" or not hasattr(os, "add_dll_directory"):
        return []
    registered: list[str] = []
    config = load_config()
    configured_root = resolve_install_dir("cuda", config)
    search_roots = (
        [configured_root] if config.cuda_install_dir.strip()
        else list(dict.fromkeys([configured_root, *map(Path, sys.path)]))
    )
    for search_root in search_roots:
        nvidia_root = search_root / "nvidia"
        for component in ("cublas", "cudnn", "cuda_nvrtc"):
            dll_dir = nvidia_root / component / "bin"
            if not dll_dir.is_dir() or str(dll_dir) in CUDA_DLL_PATHS:
                continue
            handle = os.add_dll_directory(str(dll_dir))
            CUDA_DLL_HANDLES.append(handle)
            CUDA_DLL_PATHS.add(str(dll_dir))
            registered.append(str(dll_dir))
    # CTranslate2 resolves these libraries lazily during the first segment
    # iteration. Explicit loading makes custom-target wheels discoverable.
    dll_names = ("cublas64_12.dll", "cublasLt64_12.dll", "cudnn64_9.dll")
    ordered_dirs = [
        configured_root / "nvidia" / component / "bin"
        for component in ("cublas", "cudnn", "cuda_nvrtc")
    ] + [Path(directory) for directory in CUDA_DLL_PATHS]
    for name in dll_names:
        dll_path = next((directory / name for directory in ordered_dirs if (directory / name).is_file()), None)
        if dll_path and str(dll_path) not in CUDA_PRELOADED_PATHS:
            CUDA_PRELOADED.append(ctypes.WinDLL(str(dll_path)))
            CUDA_PRELOADED_PATHS.add(str(dll_path))
    return registered
    # Moon End


# Moon Begin: cooperative controls preserve checkpoints at translation/summary boundaries.
class JobControl:
    def __init__(self) -> None:
        self.resume_event = asyncio.Event()
        self.resume_event.set()
        self.cancelled = False
        self.previous_stage = ""

    async def checkpoint(self) -> None:
        if self.cancelled:
            raise asyncio.CancelledError
        await self.resume_event.wait()
        if self.cancelled:
            raise asyncio.CancelledError
# Moon End


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
    model_name: str,
    progress_callback: Callable[[int, int, int, float, str], None] | None = None,
    model_path: str = "",
    download_source: str = "auto",
    cancel_event: threading.Event | None = None,
    install_dir: str = "",
) -> str:
    """Download selected model once and report byte-based first-run progress."""
    # Moon Begin
    from huggingface_hub import HfApi, snapshot_download
    from huggingface_hub.constants import HF_HUB_CACHE
    from tqdm.auto import tqdm

    _raise_if_cancelled(cancel_event)
    model_name = model_name.removesuffix(".en")
    repo_id = model_name if "/" in model_name else f"Systran/faster-whisper-{model_name}"
    # Moon Add: an explicitly configured local model always wins and never contacts HF.
    configured_model = Path(model_path).expanduser() if model_path.strip() else None
    if configured_model:
        missing = [name for name in ("config.json", "model.bin", "tokenizer.json") if not (configured_model / name).is_file()]
        if missing:
            raise RuntimeError(f"自定义模型路径不可用，缺少：{', '.join(missing)}")
        size = (configured_model / "model.bin").stat().st_size
        if progress_callback:
            progress_callback(100, size, size, 0, "自定义本机路径")
        return str(configured_model.resolve())

    # Moon Add: respect the optional source preference while retaining fallback in auto mode.
    endpoint_map = {"mirror": WHISPER_MODEL_ENDPOINTS[0], "official": WHISPER_MODEL_ENDPOINTS[1]}
    model_endpoints = WHISPER_MODEL_ENDPOINTS if download_source == "auto" else (endpoint_map.get(download_source, WHISPER_MODEL_ENDPOINTS[0]),)
    # A complete standard cache must never perform a network request or wait
    # for a stale Hugging Face lock left by an interrupted download.
    if _uses_default_model_root(install_dir):
        standard_repo = Path(HF_HUB_CACHE) / f"models--{repo_id.replace('/', '--')}"
        standard_snapshots = standard_repo / "snapshots"
        for cached_path in standard_snapshots.glob("*") if standard_snapshots.exists() else []:
            if all((cached_path / name).exists() for name in ("config.json", "model.bin", "tokenizer.json")):
                if progress_callback:
                    size = (cached_path / "model.bin").stat().st_size
                    progress_callback(100, size, size, 0, "本机缓存")
                return str(cached_path)

    install_root = _model_install_root(install_dir)
    legacy_model_dir = install_root / model_name.replace("/", "--")
    expected = ("config.json", "model.bin", "tokenizer.json")
    completion_marker = legacy_model_dir / ".ytba-model-size"
    model_file = legacy_model_dir / "model.bin"
    marked_size = int(completion_marker.read_text().strip()) if completion_marker.exists() else 0
    if (
        all((legacy_model_dir / name).exists() for name in expected)
        and marked_size > 0
        and model_file.stat().st_size == marked_size
    ):
        if progress_callback:
            progress_callback(100, marked_size, marked_size, 0, "本机缓存")
        return str(legacy_model_dir)

    # Moon Begin: releases 0.11.2/0.11.3 may leave a valid partial model.bin in
    # Hugging Face's local-dir cache. Resume it with plain HTTP Range requests;
    # this avoids Xet's long 0% reconstruction phase and preserves downloaded MB.
    download_cache = legacy_model_dir / ".cache" / "huggingface" / "download"
    partial_candidates = sorted(
        download_cache.glob("*.incomplete"),
        key=lambda path: path.stat().st_size,
        reverse=True,
    ) if download_cache.exists() else []
    partial_model = next((path for path in partial_candidates if path.stat().st_size), None)
    if partial_model and (legacy_model_dir / "config.json").exists():
        import httpx

        model_url = ""
        downloaded = partial_model.stat().st_size
        probe = None
        source_name = ""
        for candidate_source, endpoint in model_endpoints:
            _raise_if_cancelled(cancel_event)
            candidate_url = f"{endpoint}/{repo_id}/resolve/main/model.bin"
            for _ in range(2):
                try:
                    probe = httpx.get(
                        candidate_url, headers={"Range":"bytes=0-0"},
                        follow_redirects=True, timeout=15,
                    )
                    probe.raise_for_status()
                    model_url = candidate_url
                    source_name = candidate_source
                    break
                except httpx.HTTPError:
                    probe = None
            if probe is not None:
                break
        if probe is None:
            raise RuntimeError("连接 HF 镜像和官方模型仓库均超时，请检查网络后重试")
        match = re.search(r"/(\d+)$", probe.headers.get("content-range", ""))
        total_bytes = int(match.group(1)) if match else 0
        if probe.status_code != 206 or total_bytes <= downloaded:
            raise RuntimeError("无法获取语音模型断点信息，请检查网络后重试")
        if progress_callback:
            progress_callback(
                min(99, int(downloaded * 100 / total_bytes)),
                downloaded, total_bytes, 0, source_name,
            )
        curl = shutil.which("curl.exe") or shutil.which("curl")
        if not curl:
            raise RuntimeError("系统缺少 curl，无法可靠续传语音模型")
        process = subprocess.Popen(
            [curl, "-L", "--retry", "5", "--retry-all-errors",
             "--connect-timeout", "15", "--max-time", "900", "-C", "-",
             "-o", str(partial_model), model_url],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        previous_bytes = downloaded
        previous_time = time.monotonic()
        smoothed_speed = 0.0
        while process.poll() is None:
            if cancel_event and cancel_event.is_set():
                process.terminate()
                process.wait(timeout=5)
                raise DownloadCancelled()
            downloaded = partial_model.stat().st_size
            now = time.monotonic()
            elapsed = max(0.001, now - previous_time)
            current_speed = max(0, downloaded - previous_bytes) / elapsed
            if current_speed:
                smoothed_speed = current_speed if not smoothed_speed else smoothed_speed * 0.7 + current_speed * 0.3
            previous_bytes, previous_time = downloaded, now
            if progress_callback:
                progress_callback(
                    min(99, int(downloaded * 100 / total_bytes)),
                    downloaded, total_bytes, smoothed_speed, source_name,
                )
            time.sleep(0.5)
        if process.returncode:
            raise RuntimeError(f"语音模型下载中断（curl {process.returncode}），请重试")
        downloaded = partial_model.stat().st_size
        if downloaded != total_bytes:
            raise RuntimeError(f"语音模型大小不正确：{downloaded} / {total_bytes}")
        partial_model.replace(legacy_model_dir / "model.bin")
        completion_marker.write_text(str(total_bytes), encoding="ascii")
        if progress_callback:
            progress_callback(100, total_bytes, total_bytes, 0, "本机缓存")
        return str(legacy_model_dir)
    # Moon End

    allow_patterns = [
        "config.json", "preprocessor_config.json", "model.bin",
        "tokenizer.json", "vocabulary.*",
    ]
    reported_percent = 0
    selected_endpoint = model_endpoints[0]
    active_source = selected_endpoint[0]
    progress_started = time.monotonic()
    aggregate_positions: dict[int, int] = {}
    aggregate_lock = __import__("threading").Lock()
    previous_report_bytes = 0
    previous_report_time = progress_started
    smoothed_speed = 0.0

    def fetch_download_total(endpoint: str) -> int:
        """Resolve selected file sizes before transfer so total bytes are visible immediately."""
        # Moon Add
        import fnmatch
        _raise_if_cancelled(cancel_event)
        info = HfApi(endpoint=endpoint).model_info(repo_id, files_metadata=True, timeout=20)
        return sum(
            int(item.size or 0) for item in info.siblings
            if any(fnmatch.fnmatch(item.rfilename, pattern) for pattern in allow_patterns)
        )

    try:
        total_expected = fetch_download_total(selected_endpoint[1])
    except Exception:
        if len(model_endpoints) < 2:
            raise
        selected_endpoint = model_endpoints[1]
        active_source = selected_endpoint[0]
        total_expected = fetch_download_total(selected_endpoint[1])
    if progress_callback:
        progress_callback(0, 0, total_expected, 0, active_source)

    class DownloadProgress(tqdm):
        """Forward Hugging Face's aggregate byte progress to the job view."""
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            with aggregate_lock:
                aggregate_positions[id(self)] = int(self.n)

        def display(self, *args, **kwargs):
            # Moon Add: retain tqdm counters without drawing into the native-service log.
            return None

        def update(self, amount=1):
            nonlocal reported_percent, previous_report_bytes, previous_report_time, smoothed_speed
            _raise_if_cancelled(cancel_event)
            result = super().update(amount)
            if progress_callback:
                with aggregate_lock:
                    aggregate_positions[id(self)] = int(self.n)
                    # Hugging Face/Xet exposes both network-transfer and file-rebuild
                    # bars for the same bytes. The largest global counter is the real
                    # user-facing download position; summing would double-count it.
                    downloaded = max(aggregate_positions.values(), default=0)
                now = time.monotonic()
                elapsed = max(0.001, now - previous_report_time)
                current_speed = max(0, downloaded - previous_report_bytes) / elapsed
                if current_speed:
                    smoothed_speed = current_speed if not smoothed_speed else smoothed_speed * .7 + current_speed * .3
                percent = min(99, int(downloaded * 100 / total_expected)) if total_expected else 0
                # Moon Modified: byte/speed updates must not wait for the next whole percent.
                if now - previous_report_time >= .2 or percent > reported_percent:
                    reported_percent = max(reported_percent, percent)
                    previous_report_bytes, previous_report_time = downloaded, now
                    progress_callback(percent, downloaded, total_expected, smoothed_speed, active_source)
            return result

    # Moon Modified: new downloads use faster-whisper's standard cache. If the
    # previous release already wrote a partial legacy copy, resume that copy so
    # the user does not lose hundreds of megabytes of download progress.
    download_options = {
        "allow_patterns": allow_patterns,
        "tqdm_class": DownloadProgress,
    }
    download_options["local_dir"] = legacy_model_dir
    try:
        _raise_if_cancelled(cancel_event)
        model_path = snapshot_download(
            repo_id, endpoint=selected_endpoint[1], **download_options
        )
    except Exception:
        _raise_if_cancelled(cancel_event)
        # Moon Add: mirror outages must not make first-time setup impossible.
        if len(model_endpoints) < 2 or selected_endpoint == model_endpoints[1]:
            raise
        selected_endpoint = model_endpoints[1]
        active_source = selected_endpoint[0]
        total_expected = fetch_download_total(selected_endpoint[1])
        aggregate_positions.clear()
        reported_percent = 0
        previous_report_bytes = 0
        previous_report_time = time.monotonic()
        smoothed_speed = 0.0
        if progress_callback:
            progress_callback(0, 0, total_expected, 0, active_source)
        model_path = snapshot_download(
            repo_id, endpoint=selected_endpoint[1], **download_options
        )
    if progress_callback:
        model_file = Path(model_path) / "model.bin"
        size = model_file.stat().st_size if model_file.exists() else 0
        progress_callback(100, size, size, 0, "本机缓存")
    return str(model_path)
    # Moon End


def _transcribe(
    audio: Path,
    model_name: str,
    device_setting: str,
    download_progress: Callable[[int, int, int, float, str], None] | None = None,
    model_path: str = "",
    download_source: str = "auto",
    install_dir: str = "",
    transcription_progress: Callable[[float, float], None] | None = None,
    expected_duration: float | None = None,
    transcription_preview: Callable[[list[Segment], str], None] | None = None,
) -> tuple[list[Segment], str]:
    _configure_private_cuda_runtime()  # Moon Add: load optional one-click runtime wheels.
    import ctranslate2

    model_name = model_name.removesuffix(".en")  # Moon Add: require multilingual weights.
    # Moon Modified: keep the legacy two-argument call for default discovery and tests.
    prepared_model = (
        _prepare_whisper_model(
            model_name, download_progress, model_path, download_source,
            install_dir=install_dir,
        )
        if model_path or download_source != "auto" or install_dir
        else _prepare_whisper_model(model_name, download_progress)
    )
    device = device_setting
    if device == "auto":
        device = "cuda" if ctranslate2.get_cuda_device_count() else "cpu"
    def run(active_device: str) -> tuple[list[Segment], str]:
        """Consume the lazy segment iterator while the device fallback is active."""
        # Moon Begin: CTranslate2 loads cuBLAS on the first generator iteration,
        # not necessarily while constructing WhisperModel or calling transcribe.
        compute_type = "float16" if active_device == "cuda" else "int8"
        model = WhisperModel(prepared_model, device=active_device, compute_type=compute_type)
        items, info = model.transcribe(
            str(audio), language=None, vad_filter=True, beam_size=5
        )
        language = info.language if info.language in SUPPORTED_LANGUAGES else ""
        if not language:
            raise RuntimeError(
                f"仅支持英文、日文或中文语音，检测到：{info.language or '未知'}"
            )
        total_duration = float(expected_duration or getattr(info, "duration", 0) or 0)
        if transcription_progress:
            transcription_progress(0, total_duration)
        preview_segments: list[Segment] = []
        if transcription_preview:
            transcription_preview([], language)
        for item in items:
            text = item.text.strip()
            if text:
                preview_segments.append(Segment(
                    start=item.start, end=item.end, en=text,
                    source_language=language,
                ))
                if transcription_preview:
                    transcription_preview(list(preview_segments), language)
            if transcription_progress:
                transcription_progress(float(item.end), total_duration)
        return preview_segments, language
        # Moon End

    try:
        return run(device)
    except Exception as exc:
        if device_setting != "auto" or device == "cpu":
            message = str(exc)
            if device == "cuda" and ("cublas" in message.lower() or "cudnn" in message.lower()):
                raise RuntimeError(
                    f"CUDA 语音运行库不可用：{message}。请安装 CUDA 12 的 cuBLAS/cuDNN，"
                    "或在更多设置中选择“自动”/“仅 CPU”。"
                ) from exc
            raise
        if download_progress:
            download_progress(100, 0, 0, 0, "GPU 运行库不可用，已降级 CPU")
        return run("cpu")


async def process_job(job_id: str, url: str) -> None:
    job = JOBS[job_id]
    control = JOB_CONTROLS.setdefault(job_id, JobControl())  # Moon Add
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
            await control.checkpoint()
            source = info.get("_ytba_source", f"{platform}_subtitles")
            source_language = info.get("_ytba_language", "en")
            if not extracted:
                config = load_config()
                # Moon Begin: distinguish first-run model download from transcription.
                def human_size(value: float) -> str:
                    return f"{value / 1024 / 1024:.1f} MB"

                def report_model_download(
                    percent: int, downloaded: int, total: int,
                    speed: float, source_name: str,
                ) -> None:
                    if percent >= 100:
                        job.stage = (
                            "GPU 运行库不可用，已自动切换 CPU 识别"
                            if "降级 CPU" in source_name else "正在识别语音"
                        )
                        job.progress = 45
                    else:
                        if total:
                            size_text = f"{human_size(downloaded)} / {human_size(total)}"
                            speed_text = f" · {human_size(speed)}/s" if speed else ""
                            detail = f"{size_text}{speed_text} · {percent}%"
                        else:
                            detail = "正在连接…"
                        job.stage = f"正在下载语音模型 · {source_name} · {detail}"
                        job.progress = 25 + round(percent * 0.2)

                def report_transcription(processed: float, total: float) -> None:
                    # Moon Add: report media time, not a synthetic wall-clock estimate.
                    job.stage = "正在识别语音"
                    job.transcription_seconds = max(job.transcription_seconds, processed)
                    job.transcription_total_seconds = total
                    if total > 0:
                        job.progress = min(54, 45 + int(processed / total * 9))

                def report_transcription_preview(
                    recognized: list[Segment], language: str,
                ) -> None:
                    # Moon Add: atomically expose each recognized source segment.
                    job.preview_segments = recognized
                    job.recognized_segments = len(recognized)
                    job.source_language = language

                job.stage, job.progress = "正在通过 HF 镜像下载语音模型 0%", 25
                extracted, source_language = await asyncio.to_thread(
                    _transcribe, audio, config.whisper_model, config.device,
                    report_model_download,
                    config.whisper_model_path, config.whisper_download_source,
                    config.model_install_dir,
                    report_transcription, info.get("duration"),
                    report_transcription_preview,
                )
                await control.checkpoint()
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
                import inspect
                summary_options = {"resume_from": saved_summary_partial}
                if "control" in inspect.signature(client.summarize).parameters:
                    summary_options["control"] = control.checkpoint
                value = await client.summarize(
                    title, segments, on_summary_chunk, **summary_options,
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

        import inspect
        translate_options = {}
        if "control" in inspect.signature(client.translate).parameters:
            translate_options["control"] = control.checkpoint
        translate_task = asyncio.create_task(client.translate(
            segments, publish_translation, **translate_options
        ))
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

async def _run_job(job_id: str, url: str) -> None:
    """Keep cancellation visible instead of leaving a stale running job."""
    # Moon Begin
    try:
        await process_job(job_id, url)
    except asyncio.CancelledError:
        job = JOBS[job_id]
        job.state, job.stage, job.error = "cancelled", "任务已取消，进度已保留", None
    except Exception as exc:
        job = JOBS[job_id]
        job.state, job.stage, job.error = "failed", "处理失败", str(exc)
    finally:
        JOB_TASKS.pop(job_id, None)
    # Moon End


def create_job(url: str) -> JobView:
    job_id = uuid.uuid4().hex
    job = JobView(id=job_id, state="queued", stage="等待处理", progress=0)
    JOBS[job_id] = job
    JOB_CONTROLS[job_id] = JobControl()
    JOB_TASKS[job_id] = asyncio.create_task(_run_job(job_id, url))
    return job


# Moon Begin: public task controls used by the browser toolbar.
def pause_job(job_id: str) -> JobView:
    job, control = JOBS[job_id], JOB_CONTROLS[job_id]
    if job.state not in ("queued", "running"):
        return job
    control.previous_stage = job.stage
    control.resume_event.clear()
    job.state, job.stage = "paused", "已暂停（当前识别步骤结束后生效）"
    return job


def resume_job(job_id: str) -> JobView:
    job, control = JOBS[job_id], JOB_CONTROLS[job_id]
    if job.state != "paused":
        return job
    job.state, job.stage = "running", control.previous_stage or "继续处理"
    control.resume_event.set()
    return job


def cancel_job(job_id: str) -> JobView:
    job, control = JOBS[job_id], JOB_CONTROLS[job_id]
    if job.state in ("completed", "failed", "cancelled"):
        return job
    control.cancelled = True
    control.resume_event.set()
    # Moon Modified: stop at the next safe checkpoint. Force-cancelling a worker
    # thread can leave curl writing into the model path after cleanup begins.
    job.state, job.stage, job.error = "cancelled", "任务已取消，进度已保留", None
    return job


def _whisper_model_candidates(
    model: str, configured_path: str = "", install_dir: str = "",
) -> list[Path]:
    """Return model locations in explicit-use, selected-install, then shared-cache order."""
    # Moon Begin
    from huggingface_hub.constants import HF_HUB_CACHE

    candidates: list[Path] = []
    if configured_path.strip():
        candidates.append(Path(configured_path).expanduser())
    install_root = _model_install_root(install_dir)
    candidates.append(install_root / model.replace("/", "--"))
    repo_id = model if "/" in model else f"Systran/faster-whisper-{model}"
    snapshots = Path(HF_HUB_CACHE) / f"models--{repo_id.replace('/', '--')}" / "snapshots"
    if _uses_default_model_root(install_dir) and snapshots.exists():
        candidates.extend(snapshots.glob("*"))
    return list(dict.fromkeys(candidates))
    # Moon End


def _local_model_info(
    model: str, configured_path: str = "", install_dir: str = "",
) -> LocalModelInfo | None:
    """Find the most complete local copy, including interrupted downloads."""
    # Moon Begin
    required = ("config.json", "tokenizer.json", "model.bin")
    candidates = [
        path for path in _whisper_model_candidates(model, configured_path, install_dir)
        if path.is_dir()
    ]
    if not candidates:
        return None
    path = max(candidates, key=lambda item: sum((item / name).is_file() for name in required))
    missing = [name for name in required if not (path / name).is_file()]
    size = (path / "model.bin").stat().st_size if (path / "model.bin").is_file() else 0
    marker = path / ".ytba-model-size"
    expected = int(marker.read_text().strip()) if marker.is_file() else size
    valid = not missing and size > 0 and (not marker.is_file() or size == expected)
    return LocalModelInfo(
        model=model, path=str(path.resolve()), size=size, valid=valid,
        missing_files=missing if missing else (["model.bin（文件不完整）"] if not valid else []),
    )
    # Moon End


def inspect_whisper_model(
    model_name: str | None = None, model_path: str | None = None,
    install_dir: str | None = None,
) -> ModelStatus:
    _configure_private_cuda_runtime()  # Moon Add
    import ctranslate2
    config = load_config()
    model = (model_name or config.whisper_model).removesuffix(".en")
    configured_path = config.whisper_model_path if model_path is None else model_path
    configured_install_dir = config.model_install_dir if install_dir is None else install_dir
    selected = _local_model_info(model, configured_path, configured_install_dir)
    size = selected.size if selected else 0
    valid = bool(selected and selected.valid)
    expected = size
    if selected and selected.path:
        marker = Path(selected.path) / ".ytba-model-size"
        if marker.is_file():
            expected = int(marker.read_text().strip())
    # Report all recognizable standard models so users can see what is already reusable.
    local_models = []
    for known_model in dict.fromkeys(("tiny", "base", "small", "medium", model)):
        info = _local_model_info(
            known_model, configured_path if known_model == model else "", configured_install_dir,
        )
        if info:
            local_models.append(info)
    cuda = bool(ctranslate2.get_cuda_device_count())
    if valid:
        stage, state = "模型可用", "completed"
    elif selected:
        stage, state = "模型未完整安装", "idle"
    else:
        stage, state = "尚未安装", "idle"
    return ModelStatus(
        model=model, configured_path=configured_path,
        resolved_path=selected.path if selected else "", installed=valid, valid=valid,
        size=size, expected_size=expected, device="cuda" if cuda else "cpu",
        cuda_available=cuda, state=state, stage=stage,
        progress=100 if valid else 0, downloaded=size, total=expected,
        missing_files=selected.missing_files if selected else [], local_models=local_models,
    )


def get_model_status(
    model_name: str | None = None, model_path: str | None = None,
    install_dir: str | None = None,
) -> ModelStatus:
    requested = model_name.removesuffix(".en") if model_name else None
    if MODEL_DOWNLOAD and MODEL_DOWNLOAD.state == "running" and (not requested or MODEL_DOWNLOAD.model == requested):
        return MODEL_DOWNLOAD
    return inspect_whisper_model(model_name, model_path, install_dir)


def start_model_download(
    model_name: str | None = None, model_path: str | None = None,
    download_source: str | None = None,
    install_dir: str | None = None,
) -> ModelStatus:
    global MODEL_DOWNLOAD, MODEL_DOWNLOAD_TASK
    if MODEL_DOWNLOAD_TASK and not MODEL_DOWNLOAD_TASK.done():
        return MODEL_DOWNLOAD
    config = load_config()
    model = (model_name or config.whisper_model).removesuffix(".en")
    configured_path = config.whisper_model_path if model_path is None else model_path
    configured_install_dir = config.model_install_dir if install_dir is None else install_dir
    source = download_source or config.whisper_download_source
    MODEL_DOWNLOAD = ModelStatus(
        model=model, configured_path=configured_path,
        state="running", stage="正在连接模型仓库",
    )
    MODEL_DOWNLOAD_CANCEL.clear()

    async def run() -> None:
        global MODEL_DOWNLOAD
        def progress(percent, downloaded, total, speed, source):
            MODEL_DOWNLOAD.progress = percent
            MODEL_DOWNLOAD.downloaded = downloaded
            MODEL_DOWNLOAD.total = total
            MODEL_DOWNLOAD.speed = speed
            MODEL_DOWNLOAD.source = source
            MODEL_DOWNLOAD.stage = "正在下载模型" if percent < 100 else "模型下载完成"
        try:
            path = await asyncio.to_thread(
                _prepare_whisper_model, model, progress, configured_path, source,
                MODEL_DOWNLOAD_CANCEL, configured_install_dir,
            )
            _raise_if_cancelled(MODEL_DOWNLOAD_CANCEL)
            MODEL_DOWNLOAD.resolved_path = path
            MODEL_DOWNLOAD.installed = MODEL_DOWNLOAD.valid = True
            MODEL_DOWNLOAD.state, MODEL_DOWNLOAD.stage, MODEL_DOWNLOAD.progress = "completed", "模型可用", 100
        except (asyncio.CancelledError, DownloadCancelled):
            MODEL_DOWNLOAD.state, MODEL_DOWNLOAD.stage = "cancelled", "下载已取消，可稍后续传"
        except Exception as exc:
            MODEL_DOWNLOAD.state, MODEL_DOWNLOAD.stage, MODEL_DOWNLOAD.error = "failed", "模型下载失败", str(exc)
    MODEL_DOWNLOAD_TASK = asyncio.create_task(run())
    return MODEL_DOWNLOAD


def cancel_model_download() -> ModelStatus:
    # Moon Modified: signal the blocking worker instead of only cancelling its asyncio waiter.
    MODEL_DOWNLOAD_CANCEL.set()
    if MODEL_DOWNLOAD:
        MODEL_DOWNLOAD.state, MODEL_DOWNLOAD.stage = "cancelled", "下载已取消，可稍后续传"
    return MODEL_DOWNLOAD or inspect_whisper_model()


def model_download_worker_active() -> bool:
    # Moon Add: cache cleanup must wait until the blocking worker has observed cancellation.
    return bool(MODEL_DOWNLOAD_TASK and not MODEL_DOWNLOAD_TASK.done())
# Moon End


# Moon Begin: opt-in CUDA runtime installer with byte-level download progress.
def inspect_cuda_runtime() -> CudaRuntimeStatus:
    _configure_private_cuda_runtime()
    required = ("cublas64_12.dll", "cublasLt64_12.dll", "cudnn64_9.dll")
    configured_root = resolve_install_dir("cuda")
    configured_dirs = [
        configured_root / "nvidia" / component / "bin"
        for component in ("cublas", "cudnn", "cuda_nvrtc")
    ]
    search_dirs = configured_dirs
    found = {
        name: next(
            (str(directory / name) for directory in search_dirs if (directory / name).is_file()),
            "",
        )
        for name in required
    }
    installed = all(found.values())
    valid = installed and all(path in CUDA_PRELOADED_PATHS for path in found.values())
    return CudaRuntimeStatus(
        installed=installed, valid=valid,
        state="completed" if valid else "idle",
        stage="GPU 运行库已配置" if valid else "尚未配置 GPU 运行库（默认使用 CPU）",
        progress=100 if valid else 0,
        path=str(configured_root) if valid else "",
    )


def get_cuda_runtime_status() -> CudaRuntimeStatus:
    if CUDA_INSTALL and CUDA_INSTALL.state == "running":
        return CUDA_INSTALL
    return inspect_cuda_runtime()


def _install_cuda_runtime(
    progress: Callable[[str, int, int, float], None],
    cancel_event: threading.Event | None = None,
) -> None:
    import httpx

    install_root = resolve_install_dir("cuda")
    download_dir = CACHE_DIR.parent / "cuda-runtime-downloads"
    download_dir.mkdir(parents=True, exist_ok=True)
    wheels: list[Path] = []
    package_files: list[tuple[str, str, int, Path]] = []
    with httpx.Client(follow_redirects=True, timeout=30) as client:
        for package, label in CUDA_PACKAGES:
            _raise_if_cancelled(cancel_event)
            metadata = client.get(f"https://pypi.org/pypi/{package}/json")
            metadata.raise_for_status()
            data = metadata.json()
            version = data["info"]["version"]
            release = next(
                item for item in data["releases"][version]
                if item["filename"].endswith("win_amd64.whl")
            )
            package_files.append(
                (label, release["url"], int(release["size"]), download_dir / release["filename"])
            )

    total_bytes = sum(item[2] for item in package_files)
    # Moon Add: publish total size before the first response body chunk arrives.
    package_downloaded = [
        min(expected, destination.stat().st_size) if destination.exists() else 0
        for _, _, expected, destination in package_files
    ]
    progress("准备下载 GPU 运行库", sum(package_downloaded), total_bytes, 0)
    for package_index, (label, url, expected, destination) in enumerate(package_files):
        existing = destination.stat().st_size if destination.exists() else 0
        if existing > expected:
            destination.unlink()
            existing = 0
            package_downloaded[package_index] = 0
        started = time.monotonic()
        if existing < expected:
            headers = {"Range": f"bytes={existing}-"} if existing else {}
            with httpx.stream("GET", url, headers=headers, follow_redirects=True, timeout=60) as response:
                if existing and response.status_code != 206:
                    destination.unlink(missing_ok=True)
                    existing = 0
                response.raise_for_status()
                mode = "ab" if existing else "wb"
                with destination.open(mode) as output:
                    downloaded = existing
                    for chunk in response.iter_bytes(1024 * 1024):
                        _raise_if_cancelled(cancel_event)
                        output.write(chunk)
                        downloaded += len(chunk)
                        package_downloaded[package_index] = downloaded
                        elapsed = max(.001, time.monotonic() - started)
                        progress(label, sum(package_downloaded), total_bytes, (downloaded - existing) / elapsed)
        if destination.stat().st_size != expected:
            raise RuntimeError(f"{label} 下载大小校验失败")
        package_downloaded[package_index] = expected
        wheels.append(destination)
        progress(label, sum(package_downloaded), total_bytes, 0)

    _raise_if_cancelled(cancel_event)
    progress("正在安装本机运行库", total_bytes, total_bytes, 0)
    process = subprocess.run(
        [
            sys.executable, "-m", "pip", "install", "--no-index", "--upgrade",
            "--target", str(install_root), *map(str, wheels),
        ],
        capture_output=True, text=True, timeout=600,
    )
    if process.returncode:
        raise RuntimeError(process.stderr.strip() or "CUDA 运行库安装失败")
    _configure_private_cuda_runtime()
    status = inspect_cuda_runtime()
    if not status.valid:
        raise RuntimeError("运行库已安装，但 DLL 加载验证失败，请重启本机服务后检查")


def start_cuda_runtime_install() -> CudaRuntimeStatus:
    global CUDA_INSTALL, CUDA_INSTALL_TASK
    current = inspect_cuda_runtime()
    if current.valid:
        return current
    if CUDA_INSTALL_TASK and not CUDA_INSTALL_TASK.done():
        return CUDA_INSTALL
    CUDA_INSTALL = CudaRuntimeStatus(state="running", stage="正在获取运行库信息")
    CUDA_INSTALL_CANCEL.clear()

    async def run() -> None:
        global CUDA_INSTALL
        def publish(component: str, downloaded: int, total: int, speed: float) -> None:
            CUDA_INSTALL.component = component
            CUDA_INSTALL.stage = component
            CUDA_INSTALL.downloaded = downloaded
            CUDA_INSTALL.total = total
            CUDA_INSTALL.speed = speed
            CUDA_INSTALL.progress = min(99, int(downloaded * 100 / total)) if total else 0
        try:
            await asyncio.to_thread(_install_cuda_runtime, publish, CUDA_INSTALL_CANCEL)
            _raise_if_cancelled(CUDA_INSTALL_CANCEL)
            CUDA_INSTALL = inspect_cuda_runtime()
        except DownloadCancelled:
            CUDA_INSTALL.state, CUDA_INSTALL.stage = "cancelled", "下载已取消，可稍后继续"
        except Exception as exc:
            CUDA_INSTALL.state, CUDA_INSTALL.stage, CUDA_INSTALL.error = "failed", "GPU 运行库配置失败", str(exc)

    CUDA_INSTALL_TASK = asyncio.create_task(run())
    return CUDA_INSTALL


def cancel_cuda_runtime_install() -> CudaRuntimeStatus:
    # Moon Add: downloaded wheel fragments remain available for HTTP range resume.
    CUDA_INSTALL_CANCEL.set()
    if CUDA_INSTALL and CUDA_INSTALL.state == "running" and (
        not CUDA_INSTALL.total or CUDA_INSTALL.downloaded < CUDA_INSTALL.total
    ):
        CUDA_INSTALL.state, CUDA_INSTALL.stage = "cancelled", "下载已取消，可稍后继续"
    return CUDA_INSTALL or inspect_cuda_runtime()


def cuda_install_worker_active() -> bool:
    # Moon Add
    return bool(CUDA_INSTALL_TASK and not CUDA_INSTALL_TASK.done())
# Moon End
