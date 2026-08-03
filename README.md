# YouTube 双语字幕助手

Chrome 扩展配合 Windows 本机服务，为英文 YouTube 视频生成中英双语字幕、独立字幕面板、中文摘要和关键点。处理完成后视频停在开头并通知用户手动播放。

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

## 安装

要求：Windows、Python 3.11 x64、Chrome、FFmpeg。NVIDIA 显卡需要已安装可用驱动。

1. 如果没有 FFmpeg，运行 `winget install Gyan.FFmpeg`，完成后重新打开 PowerShell。
2. 在项目目录运行：

   ```powershell
   Set-ExecutionPolicy -Scope Process Bypass
   .\scripts\install.ps1
   ```

3. Chrome 打开 `chrome://extensions`，启用“开发者模式”，点击“加载已解压的扩展程序”，选择项目中的 `extension` 目录。
4. 在扩展卡片复制 32 位扩展 ID，然后运行：

   ```powershell
   .\scripts\install-native-host.ps1 -ExtensionId "粘贴扩展ID"
   ```

5. 在 `chrome://extensions` 重新加载扩展。点击扩展图标进入“设置”，填写模型配置。
6. 打开 YouTube 视频，按页面提示开始处理。点击处理时服务自动启动，任务完成或失败后自动关闭。

推荐初始配置：

- Base URL：`https://ai-gateway.kurogames.com/v1`
- Whisper：`small.en`
- 设备：`auto`
- 翻译模型：选择网关内速度较快且便宜的文本模型
- 摘要模型：`gpt-5.6-sol`

## 迁移到另一台机器

运行 `.\scripts\package.ps1`，把 `dist\youtube-bilingual-assistant.zip` 复制到另一台 Windows 机器并解压，然后重新执行安装步骤。模型、缓存和 API Key 不会打进压缩包。

## 数据与安全

服务只监听 `127.0.0.1:18765`。YouTube 音频在处理时写入临时目录，任务结束后删除。字幕结果保留在本地缓存。API Key 不会返回给扩展，也不会进入 Git。

当前为个人使用 MVP。YouTube 登录受限视频及 DRM 视频不保证可处理。

## 本机服务管理

- 正常情况：由扩展按需启动和关闭，无需手动操作。
- 手动调试：`.\scripts\start.ps1`
- 如果扩展 ID 变化，重新运行 `install-native-host.ps1` 注册新 ID。

Chrome 安全策略不允许网页扩展直接执行任意本地路径，因此安装脚本注册 Chrome 官方 Native Messaging 启动器。启动器仅允许指定扩展 ID 调用。
