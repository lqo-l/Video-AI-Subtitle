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
        batch_size = 20  # Moon Modified: expose the first playable translated section sooner.
        context_size = 5  # Moon Add: retain terminology and references across batch boundaries.
        for offset in range(0, len(segments), batch_size):
            batch = segments[offset : offset + batch_size]
            # Moon Begin: previous translations are context-only; the model must not output them.
            context_start = max(0, offset - context_size)
            context = [
                {"id": i, "en": segments[i].en, "zh": segments[i].zh}
                for i in range(context_start, offset)
            ]
            current = [{"id": offset + i, "en": item.en} for i, item in enumerate(batch)]
            payload = {"context_only": context, "translate": current}
            text = await self._request(
                self.config.translation_model,
                "将英文视频字幕翻译成自然、准确、简洁的简体中文。context_only 是前文中英对照，只用于理解指代、术语和语气，禁止输出或改写。仅翻译 translate 数组。只返回 JSON 数组，每项格式为 {id, zh}；ID 必须来自 translate，不得遗漏、增加或重复，不得添加 Markdown。",
                json.dumps(payload, ensure_ascii=False),
            )
            # Moon End
            match = re.search(r"\[[\s\S]*\]", text)
            if not match:
                raise RuntimeError("翻译模型未返回有效 JSON 数组")
            expected_ids = {offset + i for i in range(len(batch))}
            translated = {
                int(x["id"]): str(x["zh"]).strip()
                for x in json.loads(match.group())
                if int(x["id"]) in expected_ids
            }
            if set(translated) != expected_ids:
                missing = sorted(expected_ids - set(translated))
                raise RuntimeError(f"翻译模型漏掉字幕 ID：{missing}")
            for i, item in enumerate(batch):
                item.zh = translated[offset + i]
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
