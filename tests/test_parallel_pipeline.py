import asyncio
import json

from service.app import pipeline
from service.app.models import JobView, Segment, ServiceConfig


def test_translation_and_summary_start_concurrently(tmp_path, monkeypatch):
    # Moon Begin: each branch waits for the other to start, proving neither is awaited first.
    translation_started = asyncio.Event()
    summary_started = asyncio.Event()
    summary_entry_zh = []

    class FakeClient:
        def __init__(self, config):
            pass

        async def translate(self, segments, progress):
            translation_started.set()
            await asyncio.wait_for(summary_started.wait(), timeout=1)
            segments[0].zh = "你好"
            progress(1, 1)

        async def summarize(self, title, segments, on_stream, resume_from=""):
            summary_entry_zh.append(segments[0].zh)
            summary_started.set()
            await asyncio.wait_for(translation_started.wait(), timeout=1)
            on_stream("## 内容摘要\n测试摘要")
            return "测试摘要", ["测试要点"]

        async def close(self):
            pass

    monkeypatch.setattr(pipeline, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(pipeline, "WORK_DIR", tmp_path / "work")
    monkeypatch.setattr(pipeline, "load_config", lambda: ServiceConfig())
    monkeypatch.setattr(pipeline, "LlmClient", FakeClient)
    monkeypatch.setattr(
        pipeline,
        "_download",
        lambda url, directory: (
            {"title": "Parallel Test", "duration": 1},
            [Segment(start=0, end=1, en="Hello")],
            None,
        ),
    )
    (tmp_path / "cache").mkdir()
    (tmp_path / "work").mkdir()
    job_id = "parallel-job"
    pipeline.JOBS[job_id] = JobView(id=job_id, state="queued", stage="等待处理", progress=0)

    asyncio.run(pipeline.process_job(job_id, "https://www.youtube.com/watch?v=parallel"))

    job = pipeline.JOBS.pop(job_id)
    assert job.state == "completed"
    assert job.summary_state == "completed"
    assert job.summary_partial == "## 内容摘要\n测试摘要"
    assert job.result.summary == "测试摘要"
    assert summary_entry_zh == [""]
    # Moon End


def test_streamed_summary_markdown_is_parsed():
    from service.app.llm import LlmClient

    text = "## 内容摘要\n第一段。\n\n第二段。\n\n## 关键点\n- 要点一\n- 要点二"
    summary, points = LlmClient._parse_streamed_summary(text)
    assert summary == "第一段。\n\n第二段。"
    assert points == ["要点一", "要点二"]


def test_summary_failure_does_not_discard_translated_subtitles(tmp_path, monkeypatch):
    class FakeClient:
        def __init__(self, config):
            pass

        async def translate(self, segments, progress):
            segments[0].zh = "你好"
            progress(1, 1)

        async def summarize(self, title, segments, on_stream, resume_from=""):
            raise RuntimeError("summary unavailable")

        async def close(self):
            pass

    monkeypatch.setattr(pipeline, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(pipeline, "WORK_DIR", tmp_path / "work")
    monkeypatch.setattr(pipeline, "load_config", lambda: ServiceConfig())
    monkeypatch.setattr(pipeline, "LlmClient", FakeClient)
    monkeypatch.setattr(
        pipeline,
        "_download",
        lambda url, directory: (
            {"title": "Failure Isolation", "duration": 1},
            [Segment(start=0, end=1, en="Hello")],
            None,
        ),
    )
    (tmp_path / "cache").mkdir()
    (tmp_path / "work").mkdir()
    job_id = "summary-failure-job"
    pipeline.JOBS[job_id] = JobView(id=job_id, state="queued", stage="等待处理", progress=0)

    asyncio.run(pipeline.process_job(job_id, "https://www.youtube.com/watch?v=summaryfail"))

    job = pipeline.JOBS.pop(job_id)
    assert job.state == "completed"
    assert job.summary_state == "failed"
    assert job.result.segments[0].zh == "你好"
    assert job.result.summary == ""
    assert not (tmp_path / "cache" / "summaryfail.v5.json").exists()
    assert (tmp_path / "cache" / "summaryfail.partial.v5.json").exists()
