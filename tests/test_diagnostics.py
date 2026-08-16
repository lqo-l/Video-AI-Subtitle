# Moon Begin
from service.app import diagnostics


def test_diagnostics_redacts_credentials_and_limits_large_values():
    value = diagnostics._safe_value({
        "api_key": "secret-value",
        "cookie": "browser-session",
        "normal": "kept",
    })
    assert value["api_key"] == "[redacted]"
    assert value["cookie"] == "[redacted]"
    assert value["normal"] == "kept"
    assert diagnostics._safe_value("x" * 3000).endswith("…")
# Moon End
