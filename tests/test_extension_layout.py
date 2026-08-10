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
    assert 'id="migration_dialog"' in html
    assert 'data-migration="cancel"' in html
    assert 'data-migration="keep"' in html
    assert 'data-migration="migrate"' in html
    assert "selected.has_existing?await askMigration(kind)" in script
    assert 'request("/storage/path",{method:"PUT"' in script


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
