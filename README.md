# YouTube AI Bilingual Subtitle

[English](#english) | [中文](#中文)

---

## English

A Chrome extension that generates bilingual subtitles for YouTube videos using local Whisper transcription and any OpenAI-compatible LLM for translation and summarization.

### Features

- Reuses YouTube English captions when available; falls back to local Whisper transcription via `faster-whisper`.
- GPU-accelerated transcription with automatic CPU fallback.
- In-video bilingual subtitles with a side panel for navigation, AI-generated summaries, and key points.
- Streaming translation progress -- first batch is playable immediately, with subsequent segments added seamlessly.
- Batch-aware translation context (5 previous segments) maintains terminology and tone across batches.
- Automatic deduplication of YouTube scroll captions and sentence-aware timeline re-segmentation.
- Configurable translation and summarization models (supports OpenAI Chat Completions and Responses APIs).
- One-click Markdown export.
- Subtitle display controls: show/hide, language toggle, font size, position, semi-transparent background.

### Architecture

```
Chrome Extension -> Native Messaging Host -> Local FastAPI Service
                                               |-- yt-dlp / YouTube captions
                                               |-- faster-whisper (GPU/CPU)
                                               |-- OpenAI-compatible LLM
```

The local service listens on `127.0.0.1:18765` and is started on demand by the extension. No API keys are bundled with the extension or committed to the repository.

### Prerequisites

- Windows 10/11 x64
- Chrome
- Python 3.11+ x64
- FFmpeg
- Optional: NVIDIA GPU with CUDA drivers (falls back to CPU)
- An OpenAI-compatible API endpoint

### Installation

#### 1. Install dependencies

```powershell
winget install Python.Python.3.11
winget install Gyan.FFmpeg
```

Restart your terminal, then run from the project root:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\install.ps1
```

#### 2. Load the Chrome extension

1. Open `chrome://extensions` and enable Developer mode.
2. Click **Load unpacked** and select the `extension` folder in the project directory.
3. Copy the 32-character extension ID from the extension card.

#### 3. Register the native messaging host

```powershell
.\scripts\install-native-host.ps1 -ExtensionId "<your-extension-id>"
```

Then click **Reload** on the extension card in `chrome://extensions`.

#### 4. Configure models

Click the extension icon, then **Settings**:

| Field | Description |
|---|---|
| Base URL | OpenAI-compatible API root, e.g. `https://api.deepseek.com/v1` |
| API Key | Your API key (stored only in local config) |
| Translation model | Model identifier for subtitle translation |
| Summary model | Model identifier for summary generation |
| Whisper model | `tiny.en` / `base.en` / `small.en` / `medium.en` |
| Device | `auto` (GPU preferred) / `cuda` / `cpu` |

### Usage

Open any English YouTube video, accept the prompt or click **Process Current Video** from the extension popup. The first batch of translated subtitles is playable immediately.

### Troubleshooting

#### Stuck on "Starting local service"

- Verify you ran `install-native-host.ps1` with the current extension ID.
- Ensure the project directory has not been moved after registration.
- Check logs at `%LOCALAPPDATA%\YouTubeBilingualAssistant\native-service.log`.
- Confirm port `18765` is not in use by another process.

#### "401 Authorization Required" or "Failed to fetch"

- Ensure Base URL includes `/v1` (e.g., `https://api.deepseek.com/v1`).
- Verify the API key is valid and has available quota.
- If the extension settings page returns "Failed to fetch" on save, reload the extension and try again.

#### Changes not taking effect

Reload the extension in `chrome://extensions` and refresh the YouTube page.

### License

[Apache License 2.0](LICENSE)

---

## 中文

一个 Chrome 扩展，为本机 Whisper 转录与任意兼容 OpenAI 接口的大模型驱动的 YouTube 双语字幕工具。

### 功能

- 优先复用 YouTube 英文字幕；无字幕时自动下载音频并使用 `faster-whisper` 本地转写。
- GPU 加速转写，无 GPU 时自动降级为 CPU。
- 视频内中英双语字幕，右侧可跳转字幕面板，AI 生成的摘要与关键点。
- 流式翻译进度：首批翻译完成后即可开始播放，后续字幕逐批无缝加入时间轴。
- 批间上下文感知（前 5 条中英对照），保证术语、指代和语气连贯。
- 自动消除 YouTube 滚动字幕中的重复词，按句子和停顿重新切分时间轴。
- 翻译模型与摘要模型可分别配置，兼容 OpenAI Chat Completions 与 Responses API。
- 一键导出 Markdown 文档。
- 字幕显示控制：显隐切换、语言切换、字号、位置、半透明背景。

### 架构

```
Chrome 扩展 -> Native Messaging 启动器 -> 本机 FastAPI 服务
                                           |-- yt-dlp / YouTube 字幕下载
                                           |-- faster-whisper (GPU/CPU)
                                           |-- 兼容 OpenAI 的大模型接口
```

本机服务监听 `127.0.0.1:18765`，由扩展按需启动和关闭。API Key 不随扩展分发，不提交到仓库。

### 环境要求

- Windows 10/11 x64
- Chrome 浏览器
- Python 3.11+ x64
- FFmpeg
- 可选：NVIDIA 显卡及 CUDA 驱动（无 GPU 时自动使用 CPU）
- 一个兼容 OpenAI 接口的 API 端点

### 安装

#### 1. 安装依赖

```powershell
winget install Python.Python.3.11
winget install Gyan.FFmpeg
```

重启终端后，进入项目根目录执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\install.ps1
```

#### 2. 加载 Chrome 扩展

1. 打开 `chrome://extensions`，启用右上角「开发者模式」。
2. 点击「加载已解压的扩展程序」，选择项目目录下的 `extension` 文件夹。
3. 在扩展卡片上复制 32 位扩展 ID。

#### 3. 注册本机启动器

```powershell
.\scripts\install-native-host.ps1 -ExtensionId "<你的扩展ID>"
```

然后在 `chrome://extensions` 点击该扩展的「重新加载」。

#### 4. 配置模型

点击 Chrome 工具栏中的扩展图标，再点击「设置」：

| 配置项 | 说明 |
|---|---|
| Base URL | 兼容 OpenAI 的接口根地址，如 `https://api.deepseek.com/v1` |
| API Key | 你的 API 密钥（仅保存在本机） |
| 翻译模型 | 字幕翻译使用的模型标识 |
| 摘要模型 | 摘要生成使用的模型标识 |
| Whisper 模型 | `tiny.en` / `base.en` / `small.en` / `medium.en` |
| 设备 | `auto`（GPU 优先）/ `cuda` / `cpu` |

### 使用

打开任意英文 YouTube 视频，接受页面提示或从扩展弹窗点击「处理当前视频」。首批翻译完成后即可开始播放。

### 常见问题

#### 一直显示「正在启动本机服务」

- 确认已用当前扩展 ID 运行 `install-native-host.ps1`。
- 确认项目目录注册后未被移动。
- 查看日志：`%LOCALAPPDATA%\YouTubeBilingualAssistant\native-service.log`。
- 检查 `127.0.0.1:18765` 是否被其他程序占用。

#### 报错 "401 Authorization Required" 或 "Failed to fetch"

- 确保 Base URL 包含 `/v1`（如 `https://api.deepseek.com/v1`）。
- 确认 API Key 有效且有可用额度。
- 若扩展设置页保存时提示 Failed to fetch，重载扩展后重试。

#### 修改代码未生效

在 `chrome://extensions` 重载扩展，刷新 YouTube 页面。

### 许可证

[Apache License 2.0](LICENSE)
