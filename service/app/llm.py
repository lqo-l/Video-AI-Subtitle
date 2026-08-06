from __future__ import annotations

import asyncio
import json
import re

import httpx

from .models import Segment, ServiceConfig


class LlmClient:
    def __init__(self, config: ServiceConfig):
        self.config = config
        self.client = httpx.AsyncClient(timeout=180)
        self._prefer_chat = False  # Moon Add: remember a gateway's working compatibility route.

    async def close(self) -> None:
        await self.client.aclose()

    async def _post_with_retry(self, url: str, **kwargs) -> httpx.Response:
        """Retry temporary gateway failures without repeating successful requests."""
        # Moon Begin
        transient_statuses = {408, 429, 500, 502, 503, 504}
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = await self.client.post(url, **kwargs)
                if response.status_code not in transient_statuses or attempt == 2:
                    return response
                retry_after = response.headers.get("Retry-After", "")
                delay = float(retry_after) if retry_after.replace(".", "", 1).isdigit() else 2**attempt
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                if attempt == 2:
                    raise
                delay = 2**attempt
            await asyncio.sleep(min(delay, 10))
        if last_error:
            raise last_error
        raise RuntimeError("模型请求重试失败")
        # Moon End

    async def _request(self, model: str, system: str, user: str) -> str:
        if not self.config.api_key:
            raise RuntimeError("请先在扩展设置中填写 API Key")
        if not self.config.base_url:
            raise RuntimeError("请先在扩展设置中填写 Base URL")
        headers = {"Authorization": f"Bearer {self.config.api_key}", "Content-Type": "application/json"}
        base = self.config.base_url.rstrip("/")

        # Moon Begin: retry a flaky Responses route, then fall back to Chat Completions.
        # Once Chat succeeds, use it directly for later batches in the same job.
        response = None
        if not self._prefer_chat:
            response = await self._post_with_retry(
                f"{base}/responses",
                headers=headers,
                json={"model": model, "instructions": system, "input": user},
            )
        if response is None or response.status_code in (404, 405, 408, 429, 500, 501, 502, 503, 504):
            response = await self._post_with_retry(
                f"{base}/chat/completions",
                headers=headers,
                json={
                    "model": model,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                    "temperature": 0.2,
                },
            )
            if response.is_success:
                self._prefer_chat = True
        # Moon End
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

    async def _stream_summarize(self, model: str, system: str, user: str, on_chunk):
        if not self.config.api_key:
            raise RuntimeError("请先在扩展设置中填写 API Key")
        if not self.config.base_url:
            raise RuntimeError("请先在扩展设置中填写 Base URL")
        headers = {"Authorization": f"Bearer {self.config.api_key}", "Content-Type": "application/json"}
        base = self.config.base_url.rstrip("/")
        accumulated = []
        async with self.client.stream(
            "POST", f"{base}/chat/completions",
            headers=headers,
            json={"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], "temperature": 0.2, "stream": True},
        ) as response:
            if response.status_code in (404, 405, 501):
                # Moon Add: Responses-only gateways may not expose streaming chat.
                fallback = await self._request(model, system, user)
                on_chunk(fallback)
                return fallback
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        delta = chunk["choices"][0].get("delta", {}).get("content", "")
                        if delta:
                            accumulated.append(delta)
                            on_chunk("".join(accumulated))
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
        return "".join(accumulated)

    async def translate(self, segments: list[Segment], progress=None) -> None:
        batch_size = 20  # Moon Modified: expose the first playable translated section sooner.
        context_size = 5  # Moon Add: retain terminology and references across batch boundaries.
        source_language = next((item.source_language for item in segments if item.en), "en")
        language_name = {"en": "英文", "ja": "日文", "zh": "中文"}.get(source_language, "原文")
        for offset in range(0, len(segments), batch_size):
            batch = segments[offset : offset + batch_size]
            if all(item.zh for item in batch):
                if progress:
                    progress(sum(bool(item.zh) for item in segments), len(segments))
                continue
            # Moon Begin: previous translations are context-only; resume requests contain
            # only missing IDs, so an interrupted partial batch is never translated twice.
            context_start = max(0, offset - context_size)
            context = [
                {"id": i, "en": segments[i].en, "zh": segments[i].zh}
                for i in range(context_start, offset)
            ]
            current = [
                {"id": offset + i, "en": item.en}
                for i, item in enumerate(batch)
                if not item.zh
            ]
            payload = {"context_only": context, "translate": current}
            text = await self._request(
                self.config.translation_model,
                f"将{language_name}视频字幕翻译成自然、准确、简洁的简体中文。context_only 是前文原文与中文对照，只用于理解指代、术语和语气，禁止输出或改写。仅翻译 translate 数组。只返回 JSON 数组，每项格式为 {{id, zh}}；ID 必须来自 translate，不得遗漏、增加或重复，不得添加 Markdown。",
                json.dumps(payload, ensure_ascii=False),
            )
            # Moon End
            match = re.search(r"\[[\s\S]*\]", text)
            if not match:
                raise RuntimeError("翻译模型未返回有效 JSON 数组")
            expected_ids = {item["id"] for item in current}
            translated = {
                int(x["id"]): str(x["zh"]).strip()
                for x in json.loads(match.group())
                if int(x["id"]) in expected_ids
            }
            if set(translated) != expected_ids:
                # Retry once: LLMs occasionally drop items from bulk JSON output.
                missing = sorted(expected_ids - set(translated))
                retry_ids = [{"id": i, "en": segments[i].en} for i in missing]
                retry_payload = {"context_only": context, "translate": retry_ids}
                retry_text = await self._request(
                    self.config.translation_model,
                    f"翻译以下{language_name}句子为简体中文。只返回 JSON 数组，每项格式为 {{id, zh}}，不得添加 Markdown。",
                    json.dumps(retry_payload, ensure_ascii=False),
                )
                retry_match = re.search(r"\[[\s\S]*\]", retry_text)
                if retry_match:
                    for x in json.loads(retry_match.group()):
                        try:
                            sid = int(x["id"])
                            if sid in missing:
                                translated[sid] = str(x["zh"]).strip()
                        except (KeyError, ValueError):
                            continue
                if set(translated) != expected_ids:
                    still_missing = sorted(expected_ids - set(translated))
                    raise RuntimeError(f"翻译模型漏掉字幕 ID：{still_missing}")
            for segment_id, translated_text in translated.items():
                segments[segment_id].zh = translated_text
            if progress:
                # Moon Modified: publish the completed count after every batch.
                completed = sum(bool(item.zh) for item in segments)
                progress(completed, len(segments))

    async def summarize(
        self, title: str, segments: list[Segment], on_stream=None, resume_from: str = ""
    ) -> tuple[str, list[str]]:
        lines = []
        for s in segments:
            ts = f"[{s.start:.0f}s]"
            # Moon Modified: summarization starts from the stable extracted original text.
            lines.append(f"{ts} {s.en}")
        transcript = "\n".join(lines)
        json_prompt = "总结视频内容。只返回 JSON 对象：summary 为 2-4 段中文 Markdown 摘要，key_points 为 5-12 条中文要点字符串。不得添加代码围栏。"
        user_msg = f"标题：{title}\n\n字幕：\n{transcript}"
        if on_stream:
            # Moon Begin: stream readable Markdown instead of incomplete JSON fragments.
            stream_prompt = (
                "根据视频原文字幕生成简体中文内容提炼。严格使用以下 Markdown 结构：\n"
                "## 内容摘要\n2-4 段连贯摘要\n\n## 关键点\n- 5-12 条要点\n"
                "不要输出代码围栏、JSON 或额外前言。"
            )
            if resume_from:
                user_msg += (
                    "\n\n以下是中断前已经生成并展示给用户的内容：\n"
                    f"{resume_from}\n\n从最后一个字符后自然续写，只输出尚未生成的后续内容，"
                    "不要重复标题或已有段落。"
                )
            continuation = await self._stream_summarize(
                self.config.summary_model,
                stream_prompt,
                user_msg,
                lambda chunk: on_stream(resume_from + chunk),
            )
            text = resume_from + continuation
            summary, key_points = self._parse_streamed_summary(text)
            return summary, key_points
            # Moon End
        else:
            text = await self._request(
                self.config.summary_model,
                json_prompt,
                user_msg,
            )
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return text.strip(), []
        data = json.loads(match.group())
        return str(data.get("summary", "")).strip(), [str(x) for x in data.get("key_points", [])]

    @staticmethod
    def _parse_streamed_summary(text: str) -> tuple[str, list[str]]:
        # Moon Add: retain a clean final cache while streaming human-readable Markdown.
        normalized = text.strip()
        parts = re.split(r"^##\s*关键点\s*$", normalized, maxsplit=1, flags=re.MULTILINE)
        summary = re.sub(r"^##\s*内容摘要\s*$", "", parts[0], flags=re.MULTILINE).strip()
        points = []
        if len(parts) == 2:
            points = [re.sub(r"^[-*]\s*", "", line).strip() for line in parts[1].splitlines() if re.match(r"^\s*[-*]\s+", line)]
        return summary, points
