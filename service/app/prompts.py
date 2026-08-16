# Moon Begin
from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from .config import APP_DIR, ensure_dirs


PROMPTS_DIR = APP_DIR / "prompts"
PROMPT_FILES = {
    "translation": "translation_system_prompt.txt",
    "summary": "summary_stream_prompt.txt",
}
DEFAULT_PROMPTS = {
    "translation": (
        "将{language_name}视频字幕翻译成自然、准确、简洁的简体中文。"
        "context_only 是前文原文与中文对照，只用于理解指代、术语和语气，"
        "禁止输出或改写。仅翻译 translate 数组。只返回 JSON 数组，"
        "每项格式为 {{id, zh}}；ID 必须来自 translate，不得遗漏、增加或重复，"
        "不得添加 Markdown。"
    ),
    "summary": (
        "根据视频标题和原文字幕生成简体中文内容提炼。标题只用于理解主题，"
        "不得把标题中的宣传性描述当作视频已讲述的事实。严格限于输入中明确提供的信息，"
        "不得补充外部知识、猜测画面内容、扩写背景或虚构细节。\n"
        "信息量决定输出长度：字幕很少、内容重复或信息不足时，只写能够被输入直接支持的简短总结，"
        "不要为了凑段落或要点而重复、推断或发挥；必要时明确写“可总结的信息有限”。\n"
        "严格使用以下 Markdown 结构：\n"
        "## 内容摘要\n1-4 段摘要\n\n## 关键点\n- 0-12 条有实际信息的要点\n"
        "没有可靠要点时保留“## 关键点”标题但不添加列表。"
        "不要输出代码围栏、JSON 或额外前言。"
    ),
}


def _validate_kind(kind: str) -> str:
    if kind not in PROMPT_FILES:
        raise HTTPException(400, "未知的提示词类型")
    return kind


def prompt_path(kind: str) -> Path:
    _validate_kind(kind)
    return PROMPTS_DIR / PROMPT_FILES[kind]


def ensure_prompt_file(kind: str) -> Path:
    path = prompt_path(kind)
    ensure_dirs()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(DEFAULT_PROMPTS[kind] + "\n", encoding="utf-8")
    return path


def load_prompt(kind: str) -> str:
    path = ensure_prompt_file(kind)
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(f"无法读取{kind}提示词文件：{exc}") from exc
    if not text:
        raise RuntimeError(f"{kind}提示词文件为空，请恢复默认提示词后重试")
    return text


def format_prompt(kind: str, **values: str) -> str:
    try:
        return load_prompt(kind).format(**values)
    except (KeyError, ValueError) as exc:
        raise RuntimeError(
            f"{kind}提示词格式无效：{exc}。请恢复默认提示词，"
            "并保留说明中要求的占位符与 JSON/Markdown 结构。"
        ) from exc


def restore_default_prompt(kind: str) -> Path:
    path = prompt_path(kind)
    ensure_dirs()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_PROMPTS[kind] + "\n", encoding="utf-8")
    return path
# Moon End
