from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class ServiceConfig(BaseModel):
    base_url: str = ""
    api_key: str = ""
    translation_model: str = "deepseek-v4-flash"
    summary_model: str = "deepseek-chat"
    whisper_model: str = "small"
    # Moon Add: optional local multilingual faster-whisper directory.
    whisper_model_path: str = ""
    # Moon Add: user-selected roots for future model and GPU runtime installations.
    model_install_dir: str = ""
    cuda_install_dir: str = ""
    whisper_download_source: Literal["auto", "mirror", "official"] = "auto"
    device: Literal["auto", "cuda", "cpu"] = "cpu"


class PublicConfig(BaseModel):
    base_url: str
    translation_model: str
    summary_model: str
    whisper_model: str
    whisper_model_path: str
    model_install_dir: str
    cuda_install_dir: str
    whisper_download_source: str
    device: str
    api_key_configured: bool


class WhisperModelSelection(BaseModel):
    # Moon Add: model choice is persisted independently from other unsaved settings.
    whisper_model: Literal["tiny", "base", "small", "medium"]


# Moon Begin: native folder selection and migration contracts for the options page.
class StoragePathSelection(BaseModel):
    kind: Literal["model", "cuda"]
    path: str = ""
    changed: bool = False
    has_existing: bool = False


class StoragePathUpdate(BaseModel):
    kind: Literal["model", "cuda"]
    path: str = ""
    migrate: bool = False
    # Moon Add: preserve default-path semantics instead of storing a resolved snapshot.
    use_default: bool = False


class StoragePathResult(BaseModel):
    kind: Literal["model", "cuda"]
    path: str
    migrated: bool = False
    migrated_items: int = 0


class DownloadCacheResult(BaseModel):
    kind: Literal["model", "cuda"]
    removed_files: int = 0
    freed_bytes: int = 0
# Moon End


class PageSubtitleIdentity(BaseModel):
    # Moon Add: an official Bilibili API resolution is carried with its cues.
    bvid: str = ""
    cid: int = Field(default=0, ge=0)
    duration: float = Field(default=0, ge=0)


class PageSubtitleProvenance(BaseModel):
    # Moon Add: privacy-safe request/track fingerprints make subtitle mix-ups traceable.
    request_id: str = Field(default="", max_length=80)
    navigation_generation: int = Field(default=0, ge=0)
    requested_url_hash: str = Field(default="", max_length=80)
    player_response_hash: str = Field(default="", max_length=80)
    track_id: str = Field(default="", max_length=160)
    track_language: str = Field(default="", max_length=40)
    track_kind: str = Field(default="", max_length=80)
    subtitle_url_hash: str = Field(default="", max_length=80)
    subtitle_payload_hash: str = Field(default="", max_length=80)
    cue_timing_hash: str = Field(default="", max_length=80)


class PageSubtitleDiagnostic(BaseModel):
    # Moon Add: metadata only; subtitle text is intentionally excluded.
    status: Literal["found", "no_tracks", "tracks_invalid", "lookup_failed", "stale_route"]
    identity: PageSubtitleIdentity | None = None
    track_count: int = Field(default=0, ge=0)
    ignored_ai_track_count: int = Field(default=0, ge=0)
    rejected_tracks: list[dict[str, str | float]] = Field(default_factory=list)
    error: str = ""
    provenance: PageSubtitleProvenance | None = None


class VideoRequest(BaseModel):
    url: HttpUrl
    # Moon Add: page-loaded Bilibili captions are a higher-fidelity fallback than ASR.
    page_subtitles: list["Segment"] = Field(default_factory=list)
    page_subtitle_language: Literal["en", "ja", "ko", "zh"] | None = None
    page_subtitle_identity: PageSubtitleIdentity | None = None
    page_subtitle_status: Literal["found", "no_tracks"] | None = None
    page_subtitle_provenance: PageSubtitleProvenance | None = None


class Segment(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    en: str
    zh: str = ""
    # Moon Add: `en` remains the cache-compatible original-text field.
    source_language: Literal["en", "ja", "ko", "zh"] = "en"


class ProcessedVideo(BaseModel):
    video_id: str
    title: str
    url: str
    duration: float | None = None
    source: Literal["youtube_subtitles", "bilibili_subtitles", "whisper"]
    platform: Literal["youtube", "bilibili"] = "youtube"
    source_language: Literal["en", "ja", "ko", "zh"] = "en"
    segments: list[Segment]
    summary: str
    key_points: list[str]


class JobView(BaseModel):
    id: str
    state: Literal["queued", "running", "paused", "completed", "failed", "cancelled"]
    stage: str
    progress: int
    # Moon Add: expose real media-time progress while Whisper yields segments.
    transcription_seconds: float = 0
    transcription_total_seconds: float = 0
    recognized_segments: int = 0
    # Moon Add: expose incremental translation state to the browser panel.
    translated_segments: int = 0
    total_segments: int = 0
    preview_segments: list[Segment] = Field(default_factory=list)
    error: str | None = None
    result: ProcessedVideo | None = None
    summary_partial: str = ""
    # Moon Add: summary has an independent lifecycle from translation.
    summary_state: Literal["idle", "running", "completed", "failed"] = "idle"
    summary_error: str | None = None
    platform: Literal["youtube", "bilibili"] = "youtube"
    source_language: Literal["en", "ja", "ko", "zh"] = "en"
    # Moon Add: let the panel distinguish embedded captions from speech recognition.
    source: Literal["youtube_subtitles", "bilibili_subtitles", "whisper"] | None = None


# Moon Begin: model inspection and pre-download are exposed to the settings page.
class LocalModelInfo(BaseModel):
    model: str
    path: str = ""
    size: int = 0
    valid: bool = False
    missing_files: list[str] = Field(default_factory=list)


class ModelStatus(BaseModel):
    model: str
    configured_path: str = ""
    resolved_path: str = ""
    installed: bool = False
    valid: bool = False
    size: int = 0
    expected_size: int = 0
    device: str = "cpu"
    cuda_available: bool = False
    state: Literal["idle", "running", "completed", "failed", "cancelled"] = "idle"
    stage: str = "尚未检查"
    progress: int = 0
    downloaded: int = 0
    total: int = 0
    speed: float = 0
    source: str = ""
    error: str | None = None
    missing_files: list[str] = Field(default_factory=list)
    local_models: list[LocalModelInfo] = Field(default_factory=list)
# Moon End


# Moon Begin: opt-in private CUDA runtime installation state.
class CudaRuntimeStatus(BaseModel):
    installed: bool = False
    valid: bool = False
    state: Literal["idle", "running", "completed", "failed", "cancelled"] = "idle"
    stage: str = "尚未配置"
    component: str = ""
    progress: int = 0
    downloaded: int = 0
    total: int = 0
    speed: float = 0
    path: str = ""
    error: str | None = None
# Moon End
