<div align="center">

# 视频 AI 双语字幕助手

*YouTube / Bilibili 英日视频字幕 —— 本机 Whisper 转录 + 兼容 OpenAI 的大模型翻译*

[English](README.md) · [简体中文](README_zh.md)

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

</div>

---

## 功能

- **双站点支持** —— 在 YouTube 与 Bilibili 视频、B 站番剧页面直接生成字幕和摘要。
- **英日双语源支持** —— 自动识别英文或日文原声，统一翻译为自然的简体中文。
- **优先复用站点字幕** —— 有公开英/日字幕直接使用；仅有中文字幕时直接生成摘要；没有字幕才使用本机 Whisper。
- **GPU 加速转写** —— 多语言 `faster-whisper` 支持 CUDA 加速，无 GPU 自动降级 CPU。
- **流式翻译** —— 首批字幕数秒内即可播放，后续翻译逐批加入时间轴，无需等待全部完成。
- **真正并行处理** —— 原文字幕提取后立即并行翻译与总结，摘要内容实时流式显示。
- **清晰状态提示** —— 字幕与摘要标签分别显示处理中、完成或失败状态，完成时高亮提示。
- **断点续传** —— 中断后保留原文提取、已翻译批次和流式摘要；点击面板「↻ 重试」从缓存继续，不重复消耗已完成步骤。
- **灵活侧栏** —— 支持左右切换、拖拽边缘调整宽度；全屏可选择覆盖或挤压画面，`>` / `<` 可收缩为页面边缘入口。
- **批次上下文感知** —— 每批翻译附带前 5 条原文与中文对照作为参考，保证全文术语、指代和语气一致。
- **智能字幕清洗** —— 自动检测并消除滚动字幕的重复词，按自然句重新切分时间轴。
- **翻译与摘要独立配置** —— 翻译模型和摘要模型可分别选择，兼容任意 OpenAI 兼容接口。
- **一键导出 Markdown** —— 下载完整字幕、摘要和关键点，方便离线查看。
- **灵活显示控制** —— 显隐切换、原文+中文/纯中文/纯原文切换、字号与位置调节、半透明背景。

## 架构

```
YouTube / Bilibili  --  Chrome 扩展  --  Native Messaging  --  本机 FastAPI (127.0.0.1:18765)
                                                  |-- yt-dlp（字幕 / 音频下载）
                                                  |-- 多语言 faster-whisper（GPU / CPU）
                                                  |-- 用户配置的 OpenAI 兼容接口
```

本机服务按需启动，任务结束后关闭。API Key 仅保存在本机配置文件，不随扩展分发、不写入日志；处理时标题和字幕会连同 Key 发送到你配置的模型服务。

## 环境要求

| 依赖 | 说明 |
|---|---|
| Windows 10 / 11 (x64) | |
| Chrome 浏览器 | |
| Python 3.11+ (x64) | |
| FFmpeg | `winget install Gyan.FFmpeg` |
| NVIDIA 显卡 + CUDA 驱动 | 可选，无 GPU 自动使用 CPU |
| OpenAI 兼容 API 端点 | 如 DeepSeek、OpenAI 或自建网关 |

## 快速开始

```powershell
# 1. 克隆仓库
git clone https://github.com/lqo-l/youtube-local-ai-subtitle.git
cd youtube-local-ai-subtitle

# 2. 安装 Python 依赖
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\install.ps1

# 3. 在 Chrome 中加载扩展
#    chrome://extensions -> 开发者模式 -> 加载已解压的扩展程序 -> 选择 extension 文件夹

# 4. 复制 32 位扩展 ID，注册本机启动器
.\scripts\install-native-host.ps1 -ExtensionId "<你的扩展ID>"

# 5. 在 chrome://extensions 中重载扩展
```

## 配置

点击扩展图标，进入**设置**页面：

| 配置项 | 说明 |
|---|---|
| Base URL | OpenAI 兼容接口根地址，如 `https://api.deepseek.com/v1` |
| API Key | 保存在本机配置；请求时仅发送到你填写的模型服务 |
| 翻译模型 | 用于字幕翻译的模型 |
| 摘要模型 | 用于生成摘要和关键点的模型 |
| Whisper 模型 | `tiny` / `base` / `small` / `medium` 多语言模型；默认 `small` |
| 运行设备 | `auto`（GPU 优先）/ `cuda` / `cpu` |

## 使用

打开英文或日文 YouTube/Bilibili 视频，点击扩展图标，选择**处理当前视频**。公开字幕会被优先复用；否则插件下载音频并由本机 Whisper 自动识别语言。首次使用某个 Whisper 模型时会显示模型下载百分比；下载完成后将复用本机缓存。首批中文字幕生成后即可播放，摘要和关键点并行产生。

如果浏览器、网络或本机服务中断，重新点击**处理当前视频**或侧栏中的 **↻ 重试**即可继续。插件会分别复用已提取原文字幕、已完成翻译和摘要生成进度；弹窗中的**清理字幕缓存**会同时清除这些断点。

## 常见问题

**一直显示「正在启动本机服务」**
- 确认已用当前扩展 ID 执行 `install-native-host.ps1`。
- 项目目录注册后不可移动。
- 查看日志：`%LOCALAPPDATA%\YouTubeBilingualAssistant\native-service.log`。
- 检查端口 `18765` 是否被占用。

**401 Authorization Required**
- Base URL 必须包含 `/v1`（如 `https://api.deepseek.com/v1`）。
- 确认 API Key 有效且额度充足。

**模型网关返回 502 / 503**
- 服务会自动退避重试；若 Responses 路由持续失败，会切换到 Chat Completions 并在后续批次复用该路由。
- 仍然失败时可稍后点击侧栏 **↻ 重试**，已完成的字幕和摘要不会重新处理。

**Bilibili 显示没有字幕并开始转写**
- 部分 B 站官方 CC 字幕仅对登录接口开放。插件不会读取浏览器 Cookie，会自动降级为本机音频转写。
- B 站分 P 视频按 BV 号和 `p` 参数分别缓存。

**从旧版升级后首次日语转写需要下载模型**
- 旧版 `small.en` 会自动迁移为多语言 `small`；首次使用时需要重新下载对应模型。

**设置页保存失败（Failed to fetch）**
- 在 `chrome://extensions` 重载扩展后重试。

## 许可证

[Apache License 2.0](LICENSE)
