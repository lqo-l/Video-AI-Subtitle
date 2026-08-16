# Moon Begin
import asyncio
import json

from service.app import pipeline
from service.app.llm import LlmClient
from service.app.models import JobView, Segment, ServiceConfig


def _set_job(job_id: str) -> None:
    pipeline.JOBS[job_id] = JobView(
        id=job_id, state="queued", stage="等待处理", progress=0
    )


def test_resume_uses_extraction_and_summary_checkpoint(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    work_dir = tmp_path / "work"
    cache_dir.mkdir()
    work_dir.mkdir()
    checkpoint = cache_dir / "resume.partial.v6.json"
    checkpoint.write_text(
        json.dumps(
            {
                "title": "Resume Test",
                "duration": 2,
                "source": "youtube_subtitles",
                "segments": [
                    {"start": 0, "end": 1, "en": "one", "zh": "一"},
                    {"start": 1, "end": 2, "en": "two", "zh": ""},
                ],
                "summary_partial": "## 内容摘要\n已经生成",
                "summary_state": "running",
                "summary": "",
                "key_points": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    observed = {}

    class FakeClient:
        def __init__(self, config):
            pass

        async def translate(self, segments, progress):
            observed["state_during_translation"] = pipeline.JOBS["resume-job"].state
            observed["translation_before"] = [segment.zh for segment in segments]
            segments[1].zh = "二"
            progress(2, 2)

        async def summarize(self, title, segments, on_stream, resume_from=""):
            observed["resume_from"] = resume_from
            on_stream(resume_from + "，继续完成。")
            return "已经生成，继续完成。", ["要点"]

        async def close(self):
            pass

    monkeypatch.setattr(pipeline, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(pipeline, "WORK_DIR", work_dir)
    monkeypatch.setattr(pipeline, "load_config", lambda: ServiceConfig())
    monkeypatch.setattr(pipeline, "LlmClient", FakeClient)
    monkeypatch.setattr(
        pipeline,
        "_download",
        lambda *_: (_ for _ in ()).throw(AssertionError("不应重新提取字幕")),
    )
    _set_job("resume-job")

    asyncio.run(
        pipeline.process_job("resume-job", "https://www.youtube.com/watch?v=resume")
    )

    job = pipeline.JOBS.pop("resume-job")
    assert observed["state_during_translation"] == "running"
    assert observed["translation_before"] == ["一", ""]
    assert observed["resume_from"] == "## 内容摘要\n已经生成"
    assert job.result.segments[0].zh == "一"
    assert job.result.segments[1].zh == "二"
    assert job.summary_state == "completed"
    assert not checkpoint.exists()
    assert (cache_dir / "resume.v6.json").exists()


def test_completed_summary_checkpoint_skips_summary_model(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    work_dir = tmp_path / "work"
    cache_dir.mkdir()
    work_dir.mkdir()
    (cache_dir / "done.partial.v6.json").write_text(
        json.dumps(
            {
                "title": "Done Test",
                "duration": 1,
                "source": "youtube_subtitles",
                "segments": [{"start": 0, "end": 1, "en": "one", "zh": "一"}],
                "summary_partial": "## 内容摘要\n完成",
                "summary_state": "completed",
                "summary": "完成",
                "key_points": ["要点"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    class FakeClient:
        def __init__(self, config):
            pass

        async def translate(self, segments, progress):
            progress(1, 1)

        async def summarize(self, *args, **kwargs):
            raise AssertionError("已完成摘要不应再次请求模型")

        async def close(self):
            pass

    monkeypatch.setattr(pipeline, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(pipeline, "WORK_DIR", work_dir)
    monkeypatch.setattr(pipeline, "load_config", lambda: ServiceConfig())
    monkeypatch.setattr(pipeline, "LlmClient", FakeClient)
    _set_job("done-job")

    asyncio.run(
        pipeline.process_job("done-job", "https://www.youtube.com/watch?v=done")
    )

    job = pipeline.JOBS.pop("done-job")
    assert job.result.summary == "完成"
    assert job.result.key_points == ["要点"]


def test_translation_requests_only_missing_items_in_partial_batch(monkeypatch):
    client = LlmClient(ServiceConfig(api_key="test"))
    segments = [
        Segment(start=0, end=1, en="one", zh="已有译文"),
        Segment(start=1, end=2, en="two"),
    ]
    requests = []

    async def fake_request(model, system, user):
        payload = json.loads(user)
        requests.append(payload)
        return '[{"id": 1, "zh": "新译文"}]'

    monkeypatch.setattr(client, "_request", fake_request)
    asyncio.run(client.translate(segments))
    asyncio.run(client.close())

    assert requests[0]["translate"] == [{"id": 1, "en": "two"}]
    assert segments[0].zh == "已有译文"
    assert segments[1].zh == "新译文"


def test_atomic_checkpoint_write_leaves_valid_json(tmp_path):
    path = tmp_path / "checkpoint.json"
    pipeline._write_json_atomic(path, {"字幕": ["一", "二"]})
    assert json.loads(path.read_text(encoding="utf-8")) == {"字幕": ["一", "二"]}
    assert list(tmp_path.glob("*.tmp")) == []
# Moon End
