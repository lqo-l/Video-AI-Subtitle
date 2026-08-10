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
# Moon End
