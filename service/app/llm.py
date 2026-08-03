from __future__ import annotations

import json
import re

import httpx

from .models import Segment, ServiceConfig


class LlmClient:
    def __init__(self, config: ServiceConfig):
        self.config = config
        self.client = httpx.AsyncClient(timeout=180)

    async def close(self) -> None:
        await self.client.aclose()

    async def _request(self, model: str, system: str, user: str) -> str:
        if not self.config.api_key:
            raise RuntimeError("请先在扩展设置中填写 API Key")
        headers = {"Authorization": f"Bearer {self.config.api_key}", "Content-Type": "application/json"}
        base = self.config.base_url.rstrip("/")

        # Prefer the Responses API used by the configured gateway; retain chat compatibility.
        response = await self.client.post(
            f"{base}/responses",
            headers=headers,
            json={"model": model, "instructions": system, "input": user},
        )
        if response.status_code in (404, 405):
            response = await self.client.post(
                f"{base}/chat/completions",
                headers=headers,
                json={
                    "model": model,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                    "temperature": 0.2,
                },
            )
        response.raise_for_status()
        data = response.json()
        if "choices" in data:
            return data["choices"][0]["message"]["content"]
        if data.get("output_text"):
            return data["output_text"]
        parts = []
        for item in data.get("output", []):
            for content in item.get("content", []):
                if content.get("type") in ("output_text", "text"):
                    parts.append(content.get("text", ""))
        if not parts:
            raise RuntimeError("模型返回中未找到文本")
        return "\n".join(parts)

    async def translate(self, segments: list[Segment], progress=None) -> None:
        batch_size = 40
        for offset in range(0, len(segments), batch_size):
            batch = segments[offset : offset + batch_size]
            payload = [{"id": offset + i, "text": item.en} for i, item in enumerate(batch)]
            text = await self._request(
                self.config.translation_model,
                "将英文视频字幕翻译成自然、准确、简洁的简体中文。保留术语。只返回 JSON 数组，每项格式为 {id, zh}，不得添加 Markdown。",
                json.dumps(payload, ensure_ascii=False),
            )
            match = re.search(r"\[[\s\S]*\]", text)
            if not match:
                raise RuntimeError("翻译模型未返回有效 JSON 数组")
            translated = {int(x["id"]): str(x["zh"]).strip() for x in json.loads(match.group())}
            for i, item in enumerate(batch):
                item.zh = translated.get(offset + i, item.en)
            if progress:
                # Moon Modified: publish the completed count after every batch.
                completed = min(offset + len(batch), len(segments))
                progress(completed, len(segments))

    async def summarize(self, title: str, segments: list[Segment]) -> tuple[str, list[str]]:
        transcript = "\n".join(f"[{s.start:.0f}s] {s.en} / {s.zh}" for s in segments)
        text = await self._request(
            self.config.summary_model,
            "总结视频内容。只返回 JSON 对象：summary 为 2-4 段中文 Markdown 摘要，key_points 为 5-12 条中文要点字符串。不得添加代码围栏。",
            f"标题：{title}\n\n字幕：\n{transcript}",
        )
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return text.strip(), []
        data = json.loads(match.group())
        return str(data.get("summary", "")).strip(), [str(x) for x in data.get("key_points", [])]
