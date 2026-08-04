# Moon Begin
import asyncio
import json

import httpx

from service.app.llm import LlmClient
from service.app.models import ServiceConfig


def test_responses_502_retries_then_falls_back_and_remembers_chat(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/responses"):
            return httpx.Response(502, request=request)
        return httpx.Response(
            200,
            request=request,
            json={"choices": [{"message": {"content": "chat ok"}}]},
        )

    client = LlmClient(
        ServiceConfig(base_url="https://gateway.invalid/v1", api_key="test")
    )
    asyncio.run(client.client.aclose())
    client.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def no_wait(_):
        pass

    monkeypatch.setattr(asyncio, "sleep", no_wait)

    async def run():
        assert await client._request("model", "system", "first") == "chat ok"
        assert await client._request("model", "system", "second") == "chat ok"
        await client.close()

    asyncio.run(run())
    assert calls == [
        "/v1/responses",
        "/v1/responses",
        "/v1/responses",
        "/v1/chat/completions",
        "/v1/chat/completions",
    ]


def test_chat_route_retries_temporary_502(monkeypatch):
    chat_attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal chat_attempts
        if request.url.path.endswith("/responses"):
            return httpx.Response(404, request=request)
        chat_attempts += 1
        if chat_attempts < 3:
            return httpx.Response(502, request=request)
        return httpx.Response(
            200,
            request=request,
            content=json.dumps(
                {"choices": [{"message": {"content": "recovered"}}]}
            ).encode(),
            headers={"Content-Type": "application/json"},
        )

    client = LlmClient(
        ServiceConfig(base_url="https://gateway.invalid/v1", api_key="test")
    )
    asyncio.run(client.client.aclose())
    client.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def no_wait(_):
        pass

    monkeypatch.setattr(asyncio, "sleep", no_wait)

    async def run():
        value = await client._request("model", "system", "user")
        await client.close()
        return value

    assert asyncio.run(run()) == "recovered"
    assert chat_attempts == 3
# Moon End
