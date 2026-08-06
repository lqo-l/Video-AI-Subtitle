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
# Moon End
