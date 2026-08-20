from __future__ import annotations

import asyncio
import json
import re
import time

import httpx

from .models import Segment, ServiceConfig
from .prompts import format_prompt, load_prompt
from .diagnostics import log_event


class LlmClient:
    def __init__(self, config: ServiceConfig):
        self.config = config
        self.client = httpx.AsyncClient(timeout=180)
        self._prefer_chat = False  # Moon Add: remember a gateway's working compatibility route.
        self.diagnostic_id = ""

    async def close(self) -> None:
        await self.client.aclose()

    async def _post_with_retry(self, url: str, max_attempts: int = 3, route: str = "", **kwargs) -> httpx.Response:
        """Retry temporary gateway failures without repeating successful requests."""
        # Moon Begin
        transient_statuses = {408, 429, 500, 502, 503, 504}
        last_error: Exception | None = None
        for attempt in range(max_attempts):
            started = time.monotonic()
            try:
                response = await self.client.post(url, **kwargs)
                log_event(
                    "llm_request_attempt", job_id=self.diagnostic_id, route=route,
                    attempt=attempt + 1, status=response.status_code,
                    elapsed_seconds=round(time.monotonic() - started, 2),
                )
                if response.status_code not in transient_statuses or attempt == max_attempts - 1:
                    return response
                retry_after = response.headers.get("Retry-After", "")
                delay = float(retry_after) if retry_after.replace(".", "", 1).isdigit() else 2**attempt
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                log_event(
                    "llm_request_attempt", job_id=self.diagnostic_id, route=route,
                    attempt=attempt + 1, status=type(exc).__name__,
                    elapsed_seconds=round(time.monotonic() - started, 2),
                )
                if attempt == max_attempts - 1:
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
                max_attempts=1, route="responses",
                headers=headers,
                json={"model": model, "instructions": system, "input": user},
            )
        if response is None or response.status_code in (404, 405, 408, 429, 500, 501, 502, 503, 504):
            response = await self._post_with_retry(
                f"{base}/chat/completions",
                route="chat_completions",
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

    async def _stream_summarize(self, model: str, system: str, user: str, on_chunk, control=None):
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
            # Moon Add: a working streaming Chat route should steer concurrent
            # and later translation batches away from an unreliable Responses route.
            self._prefer_chat = True
            async for line in response.aiter_lines():
                if control:
                    await control()
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

    async def translate(self, segments: list[Segment], progress=None, control=None) -> None:
        batch_size = 20  # Moon Modified: expose the first playable translated section sooner.
        context_size = 5  # Moon Add: retain terminology and references across batch boundaries.
        source_language = next((item.source_language for item in segments if item.en), "en")
        language_name = {"en": "英文", "ja": "日文", "ko": "韩文", "zh": "中文"}.get(source_language, "原文")
        for offset in range(0, len(segments), batch_size):
            if control:
                await control()
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
            batch_started = time.monotonic()
            log_event(
                "translation_batch_started", job_id=self.diagnostic_id,
                offset=offset, item_count=len(current), model=self.config.translation_model,
            )
            text = await self._request(
                self.config.translation_model,
                format_prompt("translation", language_name=language_name),
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
                log_event(
                    "translation_batch_missing_retry", job_id=self.diagnostic_id,
                    offset=offset, missing_count=len(missing),
                )
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
            log_event(
                "translation_batch_completed", job_id=self.diagnostic_id,
                offset=offset, item_count=len(current),
                elapsed_seconds=round(time.monotonic() - batch_started, 2),
            )

    async def summarize(
        self, title: str, segments: list[Segment], on_stream=None, resume_from: str = "", control=None
    ) -> tuple[str, list[str]]:
        lines = []
        for s in segments:
            ts = f"[{s.start:.0f}s]"
            # Moon Modified: summarization starts from the stable extracted original text.
            lines.append(f"{ts} {s.en}")
        transcript = "\n".join(lines)
        # Moon Modified: sparse captions must produce a sparse summary rather than hallucinated detail.
        json_prompt = (
            "仅根据给定标题和字幕总结视频；标题只用于理解主题，不得把宣传性描述当作视频已讲述的事实。"
            "禁止补充外部知识、猜测画面、扩写背景或虚构细节。信息不足时简短说明可总结的信息有限，"
            "不要凑段落或要点。只返回 JSON 对象：summary 为 1-4 段中文摘要，"
            "key_points 为 0-12 条有明确输入依据的中文要点字符串。不得添加代码围栏。"
        )
        user_msg = f"标题：{title}\n\n字幕：\n{transcript}"
        if on_stream:
            # Moon Begin: stream readable Markdown instead of incomplete JSON fragments.
            stream_prompt = load_prompt("summary")
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
                control,
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
