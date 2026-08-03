# YouTube 本地 AI 双语字幕助手

一个面向 Windows + Chrome 的本地优先 YouTube 双语字幕工具。它优先复用视频自带英文字幕；无字幕时使用本机 Whisper 转写，再通过 OpenAI 兼容接口生成简体中文翻译、摘要和关键点。

> 当前版本：`v0.8.2`。项目处于个人使用阶段，仅支持英文到简体中文。

## 功能

- 优先使用 YouTube 英文字幕；没有字幕时由 `yt-dlp` 下载音频并使用 `faster-whisper` 转写。
- NVIDIA GPU 优先，自动模式无法使用 CUDA 时降级至 CPU。
- 完整处理后再播放，避免字幕延迟。
- 视频内中英双语字幕、右侧可跳转字幕面板、摘要与关键点。
- 翻译阶段显示已完成数量和百分比，并逐批在字幕面板展示已翻译内容。
- 第一批翻译完成后即可手动播放；未翻译时间段暂不显示，后续字幕完成后无缝加入时间轴。
- 每批翻译附带前 5 条中英对照作为只读上下文，保持术语、指代和语气连续。
- 自动消除 YouTube 滚动字幕的重复词，并按句子、停顿和长度重新切分时间轴。
- 翻译模型和总结模型可分别配置，兼容 OpenAI Responses API 和 Chat Completions API。
- 结果缓存在 `%LOCALAPPDATA%\YouTubeBilingualAssistant\cache`，API Key 仅保存在本机配置文件。
- 一键导出 Markdown 文档。
- 扩展弹窗可一键清理全部字幕缓存，不影响 API Key 和模型设置。
- 播放时可临时隐藏字幕、切换中英/中文/英文、调节字号与位置，并可开启半透明背景；偏好保存在 Chrome 本地。
- 右侧面板可收缩为页面边缘标签并重新展开，全屏时自动贴合顶部且不挤压播放器。
- 字幕字号随实际播放器宽度动态缩放，全屏自动放大、小窗口自动缩小，并叠加手动字号设置。

## 工作方式

```text
Chrome 扩展 → Native Messaging 启动器 → 本机 FastAPI 服务
                                      ├─ yt-dlp / YouTube 英文字幕
                                      ├─ faster-whisper（GPU/CPU）
                                      └─ OpenAI 兼容翻译与总结接口
```

扩展仅在处理任务时启动本机服务，任务完成、失败或释放面板后自动关闭。API Key 不会进入扩展包或 Git 仓库。

## 快速安装（Windows）

### 环境要求

- Windows 10/11 x64
- Chrome
- Python 3.11 x64（推荐；当前测试版本）
- FFmpeg
- 可选：NVIDIA 显卡和驱动；没有 GPU 时自动使用 CPU
- 一个兼容 OpenAI Responses API 或 Chat Completions API 的模型网关

### 第一步：安装依赖

如果没有 Python 或 FFmpeg，可运行：

```powershell
winget install Python.Python.3.11
winget install Gyan.FFmpeg
```

安装完成后重新打开 PowerShell，进入项目根目录并执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\install.ps1
```

脚本会在项目根目录创建 `.venv` 并安装服务依赖。

### 第二步：加载 Chrome 扩展

1. Chrome 打开 `chrome://extensions`。
2. 启用右上角“开发者模式”。
3. 点击“加载已解压的扩展程序”。
4. 选择项目根目录下的 `extension` 文件夹。
5. 在扩展卡片上复制 32 位扩展 ID。

### 第三步：注册本机启动器

回到项目根目录运行：

```powershell
.\scripts\install-native-host.ps1 -ExtensionId "粘贴扩展ID"
```

然后回到 `chrome://extensions`，点击本扩展的“重新加载”。扩展 ID 在换电脑、换 Chrome 用户配置或删除后重新加载时可能变化；变化后重新执行上面的注册命令。

### 第四步：配置模型

点击 Chrome 工具栏中的扩展图标，再点击“设置”：

| 配置 | 示例 | 说明 |
|---|---|---|
| Base URL | `https://example.com/v1` | OpenAI 兼容接口根地址 |
| API Key | `你的密钥` | 只保存在本机配置文件 |
| 翻译模型 | `deepseek-v4-flash` | 默认值，可替换为其他文本模型 |
| 摘要模型 | `gpt-5.6-sol` | 可与翻译模型不同 |
| Whisper 模型 | `small.en` | 速度和精度较均衡 |
| 运行设备 | `auto` | GPU 优先，失败自动降级 CPU |

配置文件位置：

```text
%LOCALAPPDATA%\YouTubeBilingualAssistant\config.json
```

### 第五步：使用

打开英文 YouTube 视频，接受页面提示或从扩展弹窗点击“处理当前视频”。第一批翻译完成后即可手动播放，后续字幕会逐批加入时间轴。

## 给 AI / 自动化代理的安装说明

自动化安装时按以下顺序执行，不要读取、提交或输出用户的 API Key：

1. 将仓库克隆或解压到一个长期稳定的绝对路径；注册 Native Host 后不要随意移动目录。
2. 检查 `python --version` 为 3.11 x64，检查 `ffmpeg -version` 可用。
3. 在仓库根目录运行 `powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1`。
4. 指导用户在 `chrome://extensions` 加载绝对路径 `<仓库根目录>\extension`。Chrome 内部页不能可靠自动化时必须让用户操作。
5. 获取用户复制的 32 位小写扩展 ID，运行：

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\install-native-host.ps1 -ExtensionId "<扩展ID>"
   ```

6. 确认以下注册表值指向项目内生成的 Manifest：

   ```text
   HKCU\Software\Google\Chrome\NativeMessagingHosts\com.moon.youtube_bilingual_assistant
   ```

7. 提醒用户重新加载扩展。不要长期启动 `start.ps1`；正常工作流由扩展按需启动 `127.0.0.1:18765` 服务。
8. 模型配置应由用户在扩展设置页填写。不得把 API Key 写入仓库、安装日志或命令历史。

## 迁移到另一台机器

运行 `.\scripts\package.ps1`，把 `dist\youtube-bilingual-assistant.zip` 复制到另一台 Windows 机器并解压，然后重新执行安装步骤。模型、缓存和 API Key 不会打进压缩包。

## 数据目录与安全

服务只监听 `127.0.0.1:18765`。YouTube 音频在处理时写入临时目录，任务结束后删除。字幕结果保留在本地缓存。API Key 不会返回给扩展，也不会进入 Git。

当前为个人使用 MVP。YouTube 登录受限视频及 DRM 视频不保证可处理。

## 本机服务管理

- 正常情况：由扩展按需启动和关闭，无需手动操作。
- 手动调试：`.\scripts\start.ps1`
- 如果扩展 ID 变化，重新运行 `install-native-host.ps1` 注册新 ID。

Chrome 安全策略不允许网页扩展直接执行任意本地路径，因此安装脚本注册 Chrome 官方 Native Messaging 启动器。启动器仅允许指定扩展 ID 调用。

## 常见问题

### 一直显示“正在启动本机服务”

- 确认已用当前扩展 ID 运行 `install-native-host.ps1`。
- 确认项目目录没有在注册后被移动。
- 查看日志：`%LOCALAPPDATA%\YouTubeBilingualAssistant\native-service.log`。
- 检查 `127.0.0.1:18765` 是否被其他程序占用。

### 修改代码后没有生效

在 `chrome://extensions` 点击扩展的“重新加载”，再刷新 YouTube 页面。

### 如何重新生成一个可迁移压缩包

```powershell
.\scripts\package.ps1
```

输出文件为 `dist\youtube-bilingual-assistant.zip`；其中不包含 `.venv`、API Key、模型和视频缓存。

## 开发与测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q
Get-ChildItem extension -Filter *.js | ForEach-Object { node --check $_.FullName }
```

## 许可证

暂未添加开源许可证。发布者保留全部权利；如需开源复用，请先补充明确许可证。
