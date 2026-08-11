# Moon Begin
from pathlib import Path


def test_fullscreen_push_requires_open_panel():
    css = (Path(__file__).parents[1] / "extension" / "content.css").read_text(encoding="utf-8")
    fullscreen_rules = [
        line for line in css.splitlines()
        if "ytba-layout-push" in line and "ytba-fullscreen-host" in line
    ]
    assert fullscreen_rules
    assert all("ytba-panel-open" in line for line in fullscreen_rules)


def test_bilibili_uses_draggable_launcher_instead_of_prompt():
    script = (Path(__file__).parents[1] / "extension" / "content.js").read_text(encoding="utf-8")
    assert 'site==="bilibili"?showLauncher:showPrompt' in script
    assert 'launcher.id="ytba-launcher"' in script
    assert 'launcher.textContent="译"' in script
    assert "bindLauncherDrag" in script


def test_bilibili_page_subtitles_are_sent_before_whisper_fallback():
    # Moon Modified: only the live Bilibili player CID may select a page subtitle track.
    root = Path(__file__).parents[1] / "extension"
    script = (root / "content.js").read_text(encoding="utf-8")
    background = (root / "background.js").read_text(encoding="utf-8")
    manifest = (root / "manifest.json").read_text(encoding="utf-8")
    assert 'type:"fetch-bilibili-subtitles"' in script
    assert 'type:"fetch-bilibili-subtitles",identity' in script
    assert 'ytba:get-bilibili-playback-identity' in script
    assert "requireBilibiliPlaybackIdentity(pageSubtitles)" in script
    assert "无法确认 B 站当前播放器" in script
    assert "page_subtitles:pageSubtitles.segments" in script
    assert "https://api.bilibili.com/x/player/v2" in background
    assert "message.identity" in background
    assert "pages?.[page-1]" not in background
    assert "cleanBilibiliCaption" in background
    identity_script = (root / "bilibili-page-identity.js").read_text(encoding="utf-8")
    assert "getVideoMessage" in identity_script
    assert "performance.getEntriesByType" in identity_script
    assert "https://*.hdslb.com/*" in manifest


def test_bilibili_page_caption_cache_is_scoped_to_current_player_cid():
    # Moon Add: URL p may be stale after SPA navigation and must not collide in cache.
    root = Path(__file__).parents[1]
    content = (root / "extension" / "content.js").read_text(encoding="utf-8")
    pipeline = (root / "service" / "app" / "pipeline.py").read_text(encoding="utf-8")
    assert 'url.searchParams.set("ytba_cid"' in content
    assert 'f"bilibili_{video_id}_cid{current_cid}"' in pipeline


def test_chinese_source_replaces_redundant_language_picker_with_static_label():
    # Moon Add: Chinese source and Chinese translation are the same display content.
    script = (Path(__file__).parents[1] / "extension" / "content.js").read_text(encoding="utf-8")
    assert 'data-language-static hidden>中文</span>' in script
    assert 'const chineseSource=result?.source_language==="zh"' in script
    assert "languageSelect.hidden=chineseSource" in script
    assert "staticLanguage.hidden=!chineseSource" in script


def test_collapsed_panel_hides_content_without_reflow_flash():
    css = (Path(__file__).parents[1] / "extension" / "content.css").read_text(encoding="utf-8")
    collapsed_rule = next(
        line for line in css.splitlines()
        if "#ytba-root.ytba-collapsed > *:not(.ytba-edge-handle)" in line
    )
    assert "display:none !important" in collapsed_rule


def test_settings_checks_preserve_status_and_disabled_buttons_use_default_cursor():
    # Moon Add: manual checks give quiet local feedback without replacing stable status copy.
    root = Path(__file__).parents[1] / "extension"
    html = (root / "options.html").read_text(encoding="utf-8")
    script = (root / "options.js").read_text(encoding="utf-8")
    assert "button:disabled{opacity:.5;cursor:default}" in html
    assert 'model_state.classList.add("checking")' in script
    assert 'cuda_state.classList.add("checking")' in script
    assert 'model_state.textContent="检查中…"' not in script
    assert 'cuda_state.textContent="检查中…"' not in script


def test_settings_downloads_offer_real_cancel_actions():
    # Moon Add: cancellation is visible only for active transfers and calls service endpoints.
    root = Path(__file__).parents[1] / "extension"
    html = (root / "options.html").read_text(encoding="utf-8")
    script = (root / "options.js").read_text(encoding="utf-8")
    assert 'id="cancel_model_download"' in html
    assert 'id="cancel_cuda_download"' in html
    assert 'request("/models/download/cancel",{method:"POST"})' in script
    assert 'request("/cuda/install/cancel",{method:"POST"})' in script
    assert "cancel_model_download.hidden=!running" in script
    assert "cancel_cuda_download.hidden=!downloading" in script


def test_settings_group_related_model_gpu_and_panel_controls():
    # Moon Add: related configuration and status live in the same compact group.
    root = Path(__file__).parents[1] / "extension"
    html = (root / "options.html").read_text(encoding="utf-8")
    script = (root / "options.js").read_text(encoding="utf-8")
    assert html.index("Whisper 模型") < html.index('id="whisper_model"') < html.index('id="whisper_download_source"')
    assert html.index("GPU 加速") < html.index('id="device"') < html.index('id="check_cuda"')
    assert '<h3>面板</h3>' in html
    assert "download_model.hidden=data.valid&&!running" in script
    assert "install_cuda.hidden=data.valid&&!running" in script
    assert "已安装 ${humanSize(local.size)}" in script
    assert "status-checking" not in html


def test_settings_offer_folder_picker_and_confirm_existing_migration():
    # Moon Add: model and CUDA targets use native folder selection and explicit migration choice.
    root = Path(__file__).parents[1] / "extension"
    html = (root / "options.html").read_text(encoding="utf-8")
    script = (root / "options.js").read_text(encoding="utf-8")
    assert 'id="model_install_dir" readonly' in html
    assert 'id="cuda_install_dir" readonly' in html
    assert 'id="choose_model_dir"' in html
    assert 'id="choose_cuda_dir"' in html
    assert 'id="reset_model_dir"' in html
    assert 'id="reset_cuda_dir"' in html
    assert 'id="migration_dialog"' in html
    assert 'data-migration="cancel"' in html
    assert 'data-migration="keep"' in html
    assert 'data-migration="migrate"' in html
    assert "selected.has_existing?await askMigration(kind)" in script
    assert 'request("/storage/path",{method:"PUT"' in script
    assert 'request(`/storage/default?kind=${kind}`)' in script
    assert "use_default:useDefault" in script


def test_status_wave_is_host_style_safe_and_tool_pairs_remain_adjacent():
    # Moon Modified: a single pseudo-element spinner avoids host styling of child tags.
    root = Path(__file__).parents[1] / "extension"
    html = (root / "content.js").read_text(encoding="utf-8")
    css = (root / "content.css").read_text(encoding="utf-8")
    pulse = '<div class="ytba-pulse" aria-hidden="true"></div>'
    assert pulse in html
    assert ".ytba-pulse::before" in css
    assert "overflow:hidden !important" in css
    assert "ytba-wave" not in css
    assert html.index('data-control="smaller"') < html.index('data-control="larger"') < html.index('data-control="up"') < html.index('data-control="down"')


def test_transcription_shows_real_media_time_progress():
    # Moon Add: long recognition reports verified media time without synthetic estimates.
    root = Path(__file__).parents[1]
    script = (root / "extension" / "content.js").read_text(encoding="utf-8")
    pipeline = (root / "service" / "app" / "pipeline.py").read_text(encoding="utf-8")
    models = (root / "service" / "app" / "models.py").read_text(encoding="utf-8")
    assert 'data-local-progress hidden' in script
    assert "已识别 ${formatMediaTime(current)} / ${formatMediaTime(total)}" in script
    assert 'job.stage.includes("识别语音")' in script
    assert "transcription_progress(float(item.end), total_duration)" in pipeline
    assert "transcription_seconds: float = 0" in models


def test_recognized_segments_stream_into_transcript_before_translation():
    # Moon Add: source segments have an independent preview lifecycle from translation.
    root = Path(__file__).parents[1]
    script = (root / "extension" / "content.js").read_text(encoding="utf-8")
    pipeline = (root / "service" / "app" / "pipeline.py").read_text(encoding="utf-8")
    models = (root / "service" / "app" / "models.py").read_text(encoding="utf-8")
    assert "recognized_segments: int = 0" in models
    assert "job.preview_segments = recognized" in pipeline
    assert "job.recognized_segments = len(recognized)" in pipeline
    assert "job.recognized_segments!==renderedRecognitionCount" in script
    assert "已识别，等待翻译…" in script
    assert 'job.stage.includes("识别语音") || job.stage.startsWith("翻译中文字幕")' in script


def test_completed_status_offers_play_and_stays_dismissed_after_action():
    # Moon Add: completion provides the next action and does not reappear after it is used.
    root = Path(__file__).parents[1] / "extension"
    script = (root / "content.js").read_text(encoding="utf-8")
    css = (root / "content.css").read_text(encoding="utf-8")
    assert 'data-play-completed hidden>播放视频</button>' in script
    assert "completionNoticeDismissed=true" in script
    assert "status.hidden=true" in script
    assert "player.play().catch(()=>{})" in script
    assert 'playButton.hidden=completionNoticeDismissed' in script
    assert ".ytba-play-completed[hidden],.ytba-status[hidden]" in css


def test_advanced_settings_offer_prompt_files_with_safe_format_warning():
    # Moon Add: editable prompts disclose parser-sensitive format constraints and recovery.
    root = Path(__file__).parents[1] / "extension"
    html = (root / "options.html").read_text(encoding="utf-8")
    script = (root / "options.js").read_text(encoding="utf-8")
    assert 'id="prompt_dir" readonly' in html
    assert 'id="open_prompts"' in html
    assert 'id="restore_translation_prompt"' in html
    assert 'id="restore_summary_prompt"' in html
    assert "{language_name}" in html
    assert "## 内容摘要" in html and "## 关键点" in html
    assert 'request("/prompts")' in script
    assert 'request("/prompts/open",{method:"POST"})' in script
    assert 'request(`/prompts/${kind}/restore`,{method:"POST"})' in script


def test_secondary_storage_actions_are_collapsed_and_cache_scope_is_explicit():
    # Moon Modified: primary actions stay visible while low-frequency settings use fixed disclosure.
    root = Path(__file__).parents[1] / "extension"
    html = (root / "options.html").read_text(encoding="utf-8")
    script = (root / "options.js").read_text(encoding="utf-8")
    assert 'class="advanced-options" id="model_more"' in html
    assert 'class="advanced-options" id="cuda_more"' in html
    assert html.index('id="check_model"') < html.index('id="model_more"')
    assert html.index('id="check_cuda"') < html.index('id="cuda_more"')
    assert html.count("<summary>高级选项</summary>") == 2
    assert html.index('id="model_more"') < html.index('id="whisper_download_source"')
    assert html.index('id="model_more"') < html.index('id="model_install_dir"')
    assert html.index('id="model_more"') < html.index('id="whisper_model_path"')
    assert html.index('id="cuda_more"') < html.index('id="cuda_install_dir"')
    assert html.count("清理下载缓存") == 2
    assert 'request(`/storage/download-cache?${query}`,{method:"DELETE"})' in script
    assert "已安装且可用的文件不会被删除" in script
    assert 'removeAttribute("open")' not in script


def test_panel_opacity_label_stays_on_one_line_and_advanced_options_are_inline():
    # Moon Modified: compact controls do not wrap and advanced settings remain in document flow.
    html = (Path(__file__).parents[1] / "extension" / "options.html").read_text(encoding="utf-8")
    assert ".range-row{display:grid;grid-template-columns:max-content minmax(0,1fr) max-content" in html
    assert ".range-row label{margin:0;white-space:nowrap}" in html
    assert ".advanced-options>summary,.advanced-options[open]>summary" in html
    assert ".advanced-body{display:grid" in html
    assert "action-popover" not in html
# Moon End
