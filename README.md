<div align="center">

# YouTube AI Bilingual Subtitle

*Browser-native AI subtitles for YouTube — local Whisper transcription meets OpenAI-compatible translation*

[English](README.md) · [简体中文](README_zh.md)

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

</div>

---

## Features

- **YouTube captions first** — reuses existing English subtitles whenever available, falls back to local Whisper transcription only when needed.
- **GPU-accelerated transcription** — CUDA support via `faster-whisper`, with automatic CPU fallback.
- **Streaming translation** — first batch is playable within seconds; subsequent segments join the timeline as they arrive.
- **True parallel pipeline** — English summarization starts immediately alongside translation, with a live streamed summary.
- **Clear completion states** — transcript and summary tabs independently highlight processing, completion, and failure.
- **Batch-aware context** — each batch receives 5 preceding translations as reference, preserving terminology and tone across the entire video.
- **Smart caption cleanup** — detects and collapses YouTube rolling-caption duplicates, re-segments into natural sentences.
- **Independent model selection** — translation and summarization use separately configurable models via any OpenAI-compatible API.
- **One-click Markdown export** — download full transcripts with summaries and key points for offline reference.
- **Flexible display controls** — toggle visibility, switch between bilingual / English-only / Chinese-only, adjust font size and position, enable semi-transparent background.

## Architecture

```
Chrome Extension  --  Native Messaging Host  --  Local FastAPI Server (127.0.0.1:18765)
                                                     |-- yt-dlp (caption / audio download)
                                                     |-- faster-whisper (GPU / CPU)
                                                     |-- OpenAI-compatible LLM
```

The local server starts on demand and shuts down when idle. API keys are never bundled, logged, or committed.

## Prerequisites

| Requirement | Notes |
|---|---|
| Windows 10 / 11 (x64) | |
| Chrome | |
| Python 3.11+ (x64) | |
| FFmpeg | `winget install Gyan.FFmpeg` |
| NVIDIA GPU + CUDA drivers | Optional; CPU fallback works out of the box |
| OpenAI-compatible API endpoint | e.g. DeepSeek, OpenAI, or self-hosted gateway |

## Quick Start

```powershell
# 1. Clone the repository
git clone https://github.com/lqo-l/youtube-local-ai-subtitle.git
cd youtube-local-ai-subtitle

# 2. Install Python dependencies
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\install.ps1

# 3. Load the extension in Chrome
#    chrome://extensions -> Developer mode -> Load unpacked -> select "extension" folder

# 4. Copy the 32-character extension ID, then register the native host
.\scripts\install-native-host.ps1 -ExtensionId "<your-extension-id>"

# 5. Reload the extension in chrome://extensions
```

## Configuration

Open the extension popup, click **Settings**, and fill in:

| Field | Description |
|---|---|
| Base URL | OpenAI-compatible API root, e.g. `https://api.deepseek.com/v1` |
| API Key | Your API key — stored only in local config, never transmitted elsewhere |
| Translation model | Model used for subtitle translation |
| Summary model | Model used for summary and key-point generation |
| Whisper model | `tiny.en` / `base.en` / `small.en` / `medium.en` |
| Device | `auto` (GPU preferred) / `cuda` / `cpu` |

## Usage

Navigate to any English YouTube video. Click the extension icon and select **Process Current Video**. The first translated subtitle batch appears within seconds; the full transcript, summary, and key points follow automatically.

## Troubleshooting

**Stuck on "Starting local service"**
- Confirm `install-native-host.ps1` ran with the correct extension ID.
- The project directory must not be moved after registration.
- Logs: `%LOCALAPPDATA%\YouTubeBilingualAssistant\native-service.log`.
- Ensure port `18765` is free.

**401 Authorization Required**
- Base URL must include `/v1` (e.g. `https://api.deepseek.com/v1`).
- Verify API key validity and quota.

**Settings page fails to save ("Failed to fetch")**
- Reload the extension in `chrome://extensions` and retry.

## License

[Apache License 2.0](LICENSE)
