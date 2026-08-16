<div align="center">

# Video AI Subtitle

*A local-first Chrome companion for translating and understanding YouTube and Bilibili videos.*

[简体中文](README_zh.md) · [Releases](https://github.com/lqo-l/Video-AI-Subtitle/releases) · [Report an issue](https://github.com/lqo-l/Video-AI-Subtitle/issues)

[![License](https://img.shields.io/github/license/lqo-l/Video-AI-Subtitle?color=4f46e5)](LICENSE)
[![Latest release](https://img.shields.io/github/v/release/lqo-l/Video-AI-Subtitle?display_name=tag&color=10b981)](https://github.com/lqo-l/Video-AI-Subtitle/releases)

</div>

Turn English or Japanese video speech into timestamped Chinese subtitles, then read the live summary beside the player. Existing captions are reused whenever possible; otherwise transcription runs on your own PC with Whisper.

## Why Video AI Subtitle

| | |
|---|---|
| **Watch sooner** | Translation arrives in batches. Start playing as soon as the first translated captions are ready. |
| **Read instead** | A streaming summary and key points appear alongside the transcript, with Markdown export when you are done. |
| **Runs where it matters** | Works on YouTube and Bilibili, including Bilibili episodes and multi-part videos. |
| **Local transcription** | Uses local `faster-whisper` with optional CUDA acceleration and automatic CPU fallback. |
| **Resume safely** | Extraction, translation, and summary checkpoints survive an interruption; retry continues from completed work. |
| **Fits the player** | A resizable, collapsible sidebar supports left/right placement and overlay or push layouts. |

## How it works

```text
Video page
  └─ Chrome extension
       ├─ Reuse available caption tracks
       └─ Otherwise: download audio → local Whisper transcription
                                      ├─ batch translation
                                      └─ streaming summary
```

The extension starts the local service only while a task is active. Video titles and captions are sent to the OpenAI-compatible model endpoint you configure for translation and summarization. Whisper transcription, installed models, task cache, and API-key storage remain local.

## Quick start

**Requirements:** Windows 10/11 (x64), Chrome, Python 3.11+, FFmpeg, and an OpenAI-compatible API endpoint. An NVIDIA GPU is optional.

```powershell
git clone https://github.com/lqo-l/Video-AI-Subtitle.git
cd Video-AI-Subtitle
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\install.ps1
```

Then:

1. Open `chrome://extensions`, enable **Developer mode**, and choose **Load unpacked** → the repository’s `extension` folder.
2. Copy the generated 32-character extension ID.
3. Run `./scripts/install-native-host.ps1 -ExtensionId "<extension-id>"` from the repository root.
4. Reload the extension, open its **Settings**, and enter your model endpoint, API key, translation model, and summary model.

Open a supported video, click the extension, then select **Process Current Video**.

> The project folder must stay in place after registering the native host. If you move it, run the registration command again.

## Captions and transcription

| Priority | Source | Notes |
|---|---|---|
| 1 | Platform captions | Uses the video’s available English, Japanese, or Chinese caption tracks. |
| 2 | Bilibili caption API | Resolves the exact video part from the current URL before requesting Bilibili’s caption track. Some AI/CC tracks require an active Bilibili login; Chrome supplies that session directly without the extension reading or storing cookies. |
| 3 | Local Whisper | Downloads the current video audio and transcribes it locally. Choose CPU, CUDA, and model size in Settings. |

## Settings at a glance

- **Models:** translation and summary models are configured independently through any OpenAI-compatible endpoint.
- **Whisper:** choose a multilingual `tiny`, `base`, `small`, or `medium` model. `small` is the default; use a multilingual model for Japanese.
- **Performance:** CPU works everywhere. CUDA can be configured from Advanced Settings when an NVIDIA GPU is available.
- **Storage:** model and GPU-runtime folders can be relocated; resumable task/download cache can be cleared separately.
- **Player UI:** adjust subtitle language, size, position, background, sidebar side, width, layout mode, and transparency.

### Extension updates

Starting with `v0.18.7`, when the popup finds a newer release, select **Update now**. The local updater downloads the GitHub Release archive, verifies its SHA-256 digest, replaces program files, and reloads the extension. Models, task cache, API configuration, and the Chrome extension ID are retained.

Finish or cancel active video tasks before updating. Versions below `v0.18.7` do not include the local updater and need one final manual installation; subsequent updates can use this flow.

### GPU runtime compatibility

The one-click GPU setup installs only the runtime DLLs required by `faster-whisper` / CTranslate2. It does **not** install a full CUDA Toolkit or NVIDIA driver.

| Required component | Compatible major version |
|---|---|
| NVIDIA display driver | New enough to support CUDA 12 |
| cuBLAS | 12.x (`cublas64_12.dll`, `cublasLt64_12.dll`) |
| cuDNN | 9.x (`cudnn64_9.dll`) |
| NVRTC | CUDA 12.x |

CUDA Toolkit 11.x or cuDNN 8.x is not compatible. A system CUDA 12.x installation may already provide part of the requirement, but the current plugin validates its own selected runtime folder; it does not yet automatically reuse a system-wide Toolkit installation. CPU remains a supported fallback.

## Troubleshooting

| Problem | What to check |
|---|---|
| Stuck at “Starting local service” | Re-run `install-native-host.ps1` with the current extension ID; confirm the project folder was not moved. Logs: `%LOCALAPPDATA%\YouTubeBilingualAssistant\native-service.log`. |
| `401` / `403` from the model service | Confirm the Base URL includes `/v1`, and verify the configured API key and model name. |
| Bilibili starts transcription instead of using captions | The current video may not expose a caption track, or the track may require a Bilibili login. Whisper is the intended fallback. |
| First transcription is slow | Whisper may be downloading the selected model, or CPU mode is active. Model download progress is shown in Settings. |
| GPU setup does not detect an existing CUDA Toolkit | The plugin needs the exact cuBLAS 12 and cuDNN 9 runtime DLLs, not only a CUDA driver or Toolkit 11.x. It currently validates the plugin-selected runtime folder. |

For a detailed local record, open **Settings → More Settings → Diagnostic logs**. Logs rotate automatically and exclude API keys, cookies, and caption text.

## License

[Apache License 2.0](LICENSE)
