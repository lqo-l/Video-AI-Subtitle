from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class ServiceConfig(BaseModel):
    base_url: str = "https://ai-gateway.kurogames.com/v1"
    api_key: str = ""
    translation_model: str = "deepseek-v4-flash"
    summary_model: str = "gpt-5.6-sol"
    whisper_model: str = "small.en"
    device: Literal["auto", "cuda", "cpu"] = "auto"


class PublicConfig(BaseModel):
    base_url: str
    translation_model: str
    summary_model: str
    whisper_model: str
    device: str
    api_key_configured: bool


class VideoRequest(BaseModel):
    url: HttpUrl


class Segment(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    en: str
    zh: str = ""


class ProcessedVideo(BaseModel):
    video_id: str
    title: str
    url: str
    duration: float | None = None
    source: Literal["youtube_subtitles", "whisper"]
    segments: list[Segment]
    summary: str
    key_points: list[str]


class JobView(BaseModel):
    id: str
    state: Literal["queued", "running", "completed", "failed"]
    stage: str
    progress: int
    # Moon Add: expose incremental translation state to the browser panel.
    translated_segments: int = 0
    total_segments: int = 0
    preview_segments: list[Segment] = Field(default_factory=list)
    error: str | None = None
    result: ProcessedVideo | None = None
