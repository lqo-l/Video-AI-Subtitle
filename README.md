<div align="center">

# Video AI Bilingual Subtitle

*English/Japanese subtitles for YouTube and Bilibili — local Whisper transcription meets OpenAI-compatible translation*

[English](README.md) · [简体中文](README_zh.md)

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

Current version: `v0.18.1`

</div>

---

## Features

- **YouTube and Bilibili** — works on YouTube videos, Bilibili videos, and Bilibili bangumi pages.
- **English and Japanese sources** — detects English or Japanese speech and translates both into Simplified Chinese.
- **Site captions first** — reuses public English/Japanese captions, summarizes native Chinese captions directly, and falls back to local Whisper only when needed.
- **GPU-accelerated transcription** — multilingual `faster-whisper` supports CUDA with automatic CPU fallback.
- **Runtime-aware fallback** — Auto mode also falls back when missing cuBLAS/cuDNN is detected only during lazy transcription iteration.
- **Opt-in GPU setup** — Whisper defaults to CPU; users may explicitly install project-private CUDA libraries from Advanced Settings with component, byte, speed, and percentage progress.
- **Streaming translation** — first batch is playable within seconds; subsequent segments join the timeline as they arrive.
- **True parallel pipeline** — source-language summarization starts immediately alongside translation, with a live streamed summary.
- **Clear completion states** — transcript and summary tabs independently highlight processing, completion, and failure.
- **Checkpoint resume** — preserves extracted captions, translated batches, and streamed summaries; **↻ Retry** continues without repeating completed work.
- **Flexible sidebar** — switch sides, drag to resize, choose overlay or push mode in fullscreen, and collapse with `>` / `<`.
- **Batch-aware context** — each batch receives 5 preceding source/Chinese pairs as reference, preserving terminology and tone.
- **Smart caption cleanup** — detects and collapses rolling-caption duplicates in English and Japanese, then restores readable segments.
- **Independent model selection** — translation and summarization use separately configurable models via any OpenAI-compatible API.
- **One-click Markdown export** — download full transcripts with summaries and key points for offline reference.
- **Flexible display controls** — toggle visibility, switch between source+Chinese / source-only / Chinese-only, adjust font size and position, and enable a background.
- **Advanced local settings** — validate a custom multilingual Whisper path, select mirror/official downloads, pre-download weights, and inspect size, speed, and percentage.
- **Custom install targets** — choose separate folders for Whisper models and GPU runtime files, with confirmed migration that preserves the original files.
- **Controllable resume cache** — cancellation keeps resumable progress; the More menu can clear transfer cache without removing installed files.
- **Task controls** — pause, resume, or cancel while preserving completed extraction, translation, and summary checkpoints.
- **Unified layout and appearance** — overlay/push applies in windowed and fullscreen playback, controls are grouped, and panel background transparency is configurable.
- **Workspace-style push mode** — the site header and content reflow together beside a full-height, clearly separated assistant workspace.
- **Bilibili header awareness** — the sidebar stays below the live site header in page mode and returns to full height in fullscreen.
- **Quiet Bilibili launcher** — replaces the automatic prompt with a draggable, position-persistent “译” button.
- **Dismissible assistant** — close the sidebar normally or right-click its collapsed edge button; it stays hidden until **Process Current Video** is clicked again.

## Architecture

```
YouTube / Bilibili  --  Chrome Extension  --  Native Messaging  --  Local FastAPI (127.0.0.1:18765)
                                                     |-- yt-dlp (caption / audio download)
                                                     |-- multilingual faster-whisper (GPU / CPU)
                                                     |-- user-configured OpenAI-compatible API
```

The local server starts on demand and closes after a task. The API key is stored only in the local service configuration and is never bundled or logged; titles and captions are sent with the key to the model endpoint you configure.

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
git clone https://github.com/lqo-l/Video-AI-Subtitle.git
cd Video-AI-Subtitle

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
| API Key | Stored locally and sent only to the model endpoint you configure |
| Translation model | Model used for subtitle translation |
| Summary model | Model used for summary and key-point generation |
| Whisper model | Multilingual `tiny` / `base` / `small` / `medium`; defaults to `small` |
| Model install folder | Target for future Whisper downloads; existing models can be migrated after confirmation |
| Device | `auto` (GPU preferred) / `cuda` / `cpu` |
| GPU runtime folder | Target used by one-click GPU setup; existing runtime files can be migrated after confirmation |

## Usage

Navigate to an English or Japanese YouTube/Bilibili video. Click the extension icon and select **Process Current Video**. Public captions are reused when available; otherwise local Whisper downloads and transcribes the audio with automatic language detection. The first use of a Whisper model shows byte-based download progress; later runs reuse the standard Hugging Face cache. English-only `.en` weights cannot transcribe Japanese, so enabling Japanese still requires the matching multilingual model. The first translated batch becomes playable while the summary runs in parallel.

After a browser, network, or local-service interruption, click **Process Current Video** again or **↻ Retry** in the sidebar. Completed extraction, translation, and summary progress is reused. **Clear Subtitle Cache** also removes these checkpoints.

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

**Bilibili falls back to audio transcription**
- Some official Bilibili CC captions require an authenticated subtitle API. The extension does not read browser cookies and safely falls back to local transcription.
- Multi-part videos are cached independently by BV ID and `p` parameter.

**First Japanese transcription downloads another model**
- Legacy `small.en` settings are migrated to multilingual `small`; its weights are downloaded on first use.

## License

[Apache License 2.0](LICENSE)
