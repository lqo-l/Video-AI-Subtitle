<div align="center">

# YouTube AI Bilingual Subtitle

*浏览器原生的 YouTube AI 字幕 —— 本机 Whisper 转录 + 兼容 OpenAI 的大模型翻译*

[English](README.md) · [简体中文](README_zh.md)

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

</div>

---

## 功能

- **优先复用 YouTube 字幕** —— 有英文字幕直接用，没有时才本地 Whisper 转写，节省时间和资源。
- **GPU 加速转写** —— `faster-whisper` 支持 CUDA 加速，无 GPU 自动降级 CPU。
- **流式翻译** —— 首批字幕数秒内即可播放，后续翻译逐批加入时间轴，无需等待全部完成。
- **批次上下文感知** —— 每批翻译附带前 5 条中英对照作为参考，保证全文术语、指代和语气一致。
- **智能字幕清洗** —— 自动检测并消除 YouTube 滚动字幕的重复词，按自然句重新切分时间轴。
- **翻译与摘要独立配置** —— 翻译模型和摘要模型可分别选择，兼容任意 OpenAI 兼容接口。
- **一键导出 Markdown** —— 下载完整字幕、摘要和关键点，方便离线查看。
- **灵活显示控制** —— 显隐切换、双语/纯中文/纯英文切换、字号与位置调节、半透明背景。

## 架构

```
Chrome 扩展  --  Native Messaging 启动器  --  本机 FastAPI 服务 (127.0.0.1:18765)
                                                  |-- yt-dlp（字幕 / 音频下载）
                                                  |-- faster-whisper（GPU / CPU）
                                                  |-- OpenAI 兼容大模型接口
```

本机服务按需启动，闲置自动关闭。API Key 不随扩展分发，不写入日志，不提交到仓库。

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
| API Key | API 密钥 —— 仅保存在本机配置，不会外传 |
| 翻译模型 | 用于字幕翻译的模型 |
| 摘要模型 | 用于生成摘要和关键点的模型 |
| Whisper 模型 | `tiny.en` / `base.en` / `small.en` / `medium.en` |
| 运行设备 | `auto`（GPU 优先）/ `cuda` / `cpu` |

## 使用

打开任意英文 YouTube 视频，点击扩展图标，选择**处理当前视频**。首批字幕数秒内即可播放，完整字幕、摘要和关键点随后自动生成。

## 常见问题

**一直显示「正在启动本机服务」**
- 确认已用当前扩展 ID 执行 `install-native-host.ps1`。
- 项目目录注册后不可移动。
- 查看日志：`%LOCALAPPDATA%\YouTubeBilingualAssistant\native-service.log`。
- 检查端口 `18765` 是否被占用。

**401 Authorization Required**
- Base URL 必须包含 `/v1`（如 `https://api.deepseek.com/v1`）。
- 确认 API Key 有效且额度充足。

**设置页保存失败（Failed to fetch）**
- 在 `chrome://extensions` 重载扩展后重试。

## 许可证

[Apache License 2.0](LICENSE)
