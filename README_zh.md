<div align="center">

# 视频 AI 字幕助手

*为 YouTube 与 Bilibili 提供本机转录、双语字幕与流式摘要的 Chrome 扩展。*

[English](README.md) · [发布版本](https://github.com/lqo-l/Video-AI-Subtitle/releases) · [反馈问题](https://github.com/lqo-l/Video-AI-Subtitle/issues)

[![许可证](https://img.shields.io/github/license/lqo-l/Video-AI-Subtitle?color=4f46e5)](LICENSE)
[![最新发布](https://img.shields.io/github/v/release/lqo-l/Video-AI-Subtitle?display_name=tag&color=10b981)](https://github.com/lqo-l/Video-AI-Subtitle/releases)

</div>

将英文或日文视频转换为带时间轴的中文字幕；字幕出现的同时，右侧面板会流式生成摘要和关键点。优先复用站点字幕，没有可用字幕时再调用你电脑上的 Whisper 识别。

## 它解决什么问题

| | |
|---|---|
| **不用等全部处理完** | 字幕按批翻译；第一批完成即可播放，后续内容无缝加入。 |
| **不看视频也能理解** | 右侧同步展示流式摘要、关键点和完整字幕，并支持导出 Markdown。 |
| **支持常用视频站** | 支持 YouTube、Bilibili、B 站番剧和多分 P 视频。 |
| **转录留在本机** | 使用本机 `faster-whisper`；可选 CUDA 加速，异常时自动降级 CPU。 |
| **中断后接着做** | 原文、翻译和摘要均有断点；重试不会重复完成过的步骤。 |
| **不破坏观看体验** | 侧栏可左右放置、拖拽宽度、收缩，并切换覆盖/挤压布局。 |

## 工作方式

```text
视频页面
  └─ Chrome 扩展
       ├─ 优先读取可用字幕轨
       └─ 无字幕时：下载音频 → 本机 Whisper 识别
                                     ├─ 分批翻译
                                     └─ 流式生成摘要
```

本机服务只在任务进行时启动。标题和字幕会发送到你配置的 OpenAI 兼容模型服务，用于翻译与摘要；Whisper 转录、模型文件、任务缓存和 API Key 存储均留在本机。

## 快速开始

**环境要求：** Windows 10/11（x64）、Chrome、Python 3.11+、FFmpeg，以及一个 OpenAI 兼容接口。NVIDIA 显卡为可选项。

```powershell
git clone https://github.com/lqo-l/Video-AI-Subtitle.git
cd Video-AI-Subtitle
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\install.ps1
```

接着完成四步：

1. 打开 `chrome://extensions`，启用**开发者模式**，点击**加载已解压的扩展程序**，选择仓库中的 `extension` 文件夹。
2. 复制扩展生成的 32 位 ID。
3. 在仓库根目录运行 `./scripts/install-native-host.ps1 -ExtensionId "<扩展ID>"`。
4. 重载扩展，打开**设置**，填写模型接口地址、API Key、翻译模型和摘要模型。

之后打开支持的视频，点击扩展图标并选择**处理当前视频**。

> 注册本机启动器后请勿移动项目目录；若移动过，请重新执行注册命令。

## 字幕来源与转录

| 优先级 | 来源 | 说明 |
|---|---|---|
| 1 | 站点字幕 | 使用视频可用的英文、日文或中文字幕轨。 |
| 2 | B 站字幕接口 | 先由当前 URL 精确定位视频分 P，再请求可验证的普通字幕轨。由于 B 站 AI 字幕接口可能返回与当前视频不匹配的内容，`v1.0.0` 暂不读取带 AI 标记的轨道。 |
| 3 | 本机 Whisper | 下载当前视频音频后在本机识别；可在设置中选择 CPU、CUDA 和模型大小。 |

## 设置概览

- **模型配置：** 翻译模型与摘要模型独立设置，兼容任意 OpenAI 兼容接口。
- **Whisper：** 可选多语言 `tiny`、`base`、`small`、`medium`；默认 `small`，日语请使用多语言模型。
- **性能：** 默认 CPU；有 NVIDIA 显卡时可在更多设置中主动配置 CUDA。
- **存储：** 模型与 GPU 运行库可迁移到指定位置；任务/下载缓存可单独清理。
- **播放界面：** 可调字幕语言、字号、位置、背景，及侧栏位置、宽度、布局和透明度。

### 插件更新

从 `v0.18.7` 开始，扩展弹窗发现新版本时可直接点击**立即更新**：更新器会下载 GitHub Release 安装包、校验 SHA-256、替换程序文件并重载扩展。模型、任务缓存、API 配置和 Chrome 扩展 ID 均会保留。

更新前请先完成或取消正在运行的视频任务。低于 `v0.18.7` 的旧版本没有本机更新器，仍需手动下载一次新版安装包；之后即可使用一键更新。

### GPU 运行时兼容性

一键配置下载的是 `faster-whisper` / CTranslate2 需要的运行时 DLL，**不是**完整 CUDA Toolkit，也不会安装或替换 NVIDIA 显卡驱动。

| 所需组件 | 兼容的主版本 |
|---|---|
| NVIDIA 显卡驱动 | 需足够新并支持 CUDA 12 |
| cuBLAS | 12.x（`cublas64_12.dll`、`cublasLt64_12.dll`） |
| cuDNN | 9.x（`cudnn64_9.dll`） |
| NVRTC | CUDA 12.x |

CUDA Toolkit 11.x 或 cuDNN 8.x 不兼容。系统已安装 CUDA Toolkit 12.x 时，可能已具备部分 DLL；但当前插件只验证自己选择的运行库目录，尚不会自动复用系统级 Toolkit。CPU 始终是受支持的回退方案。

## 常见问题

| 问题 | 处理方式 |
|---|---|
| 一直显示「正在启动本机服务」 | 用当前扩展 ID 重新执行 `install-native-host.ps1`，并确认项目目录没有移动。日志：`%LOCALAPPDATA%\YouTubeBilingualAssistant\logs\native-service.log`。 |
| 模型服务返回 `401` / `403` | 确认 Base URL 含 `/v1`，并检查 API Key 与模型名称。 |
| B 站未读取字幕而开始识别 | 当前视频可能没有可验证的普通字幕轨；B 站 AI 字幕当前会被忽略，Whisper 会作为正常回退。 |
| 首次识别较慢 | 可能正在下载所选 Whisper 模型，或当前为 CPU 模式；下载进度会显示在设置中。 |
| 已安装 CUDA Toolkit 但插件仍显示未配置 | 插件要求精确的 cuBLAS 12 与 cuDNN 9 运行时 DLL；仅有显卡驱动或 CUDA Toolkit 11.x 不足。当前仅验证插件选择的运行库目录。 |

需要进一步排查时，可在**设置 → 更多设置 → 诊断日志**打开日志文件夹。日志会自动轮转，且不会记录 API Key、Cookie 或字幕正文。

## 许可证

[Apache License 2.0](LICENSE)
