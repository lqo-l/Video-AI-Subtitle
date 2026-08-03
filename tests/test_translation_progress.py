import asyncio

from service.app.llm import LlmClient
from service.app.models import Segment, ServiceConfig


def test_translation_reports_each_completed_batch(monkeypatch):
    # Moon Begin: verify partial translations become observable batch by batch.
    client = LlmClient(ServiceConfig(api_key="test"))
    segments = [Segment(start=i, end=i + 1, en=f"line {i}") for i in range(45)]
    updates = []

    async def fake_request(model, system, user):
        import json

        payload = json.loads(user)
        calls.append(payload)
        return json.dumps([{"id": item["id"], "zh": f"译文 {item['id']}"} for item in payload["translate"]])

    calls = []
    monkeypatch.setattr(client, "_request", fake_request)

    async def run():
        try:
            await client.translate(segments, lambda completed, total: updates.append((completed, total)))
        finally:
            await client.close()

    asyncio.run(run())
    assert updates == [(20, 45), (40, 45), (45, 45)]
    assert segments[39].zh == "译文 39"
    assert segments[44].zh == "译文 44"
    assert calls[0]["context_only"] == []
    assert [item["id"] for item in calls[1]["context_only"]] == [15, 16, 17, 18, 19]
    assert calls[1]["context_only"][-1]["zh"] == "译文 19"
    assert [item["id"] for item in calls[1]["translate"]] == list(range(20, 40))
    # Moon End
