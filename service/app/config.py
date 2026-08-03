from __future__ import annotations

import json
import os
from pathlib import Path

from .models import ServiceConfig


APP_DIR = Path(os.getenv("LOCALAPPDATA", Path.home())) / "YouTubeBilingualAssistant"
CONFIG_PATH = APP_DIR / "config.json"
CACHE_DIR = APP_DIR / "cache"
WORK_DIR = APP_DIR / "work"


def ensure_dirs() -> None:
    for path in (APP_DIR, CACHE_DIR, WORK_DIR):
        path.mkdir(parents=True, exist_ok=True)


def load_config() -> ServiceConfig:
    ensure_dirs()
    if not CONFIG_PATH.exists():
        return ServiceConfig()
    return ServiceConfig.model_validate_json(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(config: ServiceConfig) -> None:
    ensure_dirs()
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(config.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CONFIG_PATH)

