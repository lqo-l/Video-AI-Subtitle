# Moon Begin
import asyncio
import json

from service.app import pipeline
from service.app.llm import LlmClient
from service.app.models import JobView, Segment, ServiceConfig


def test_caption_selection_prefers_english_then_japanese_then_chinese():
    captions = {"danmaku": [{}], "zh-CN": [{}], "ja-JP": [{}], "en-US": [{}]}
    assert pipeline._select_caption(captions) == ("en-US", "en")
    assert pipeline._select_caption({"danmaku": [{}], "ja-JP": [{}]}) == ("ja-JP", "ja")
    assert pipeline._select_caption({"danmaku": [{}], "zh-CN": [{}]}) == ("zh-CN", "zh")
    assert pipeline._select_caption({"danmaku": [{}]}) is None


def test_read_bilibili_srt_preserves_japanese_language(tmp_path):
    subtitle = tmp_path / "video.ja.srt"
    subtitle.write_text(
        "1\n00:00:01,000 --> 00:00:02,500\nこんにちは\n\n",
        encoding="utf-8",
    )
    segments = pipeline._read_subtitle(subtitle, "ja")
    assert len(segments) == 1
    assert segments[0].en == "こんにちは"
    assert segments[0].source_language == "ja"


def test_japanese_translation_uses_language_aware_prompt(monkeypatch):
    client = LlmClient(ServiceConfig(api_key="test"))
    segments = [Segment(start=0, end=1, en="こんにちは", source_language="ja")]
    prompts = []

    async def fake_request(model, system, user):
        prompts.append(system)
        payload = json.loads(user)
        return json.dumps([{"id": payload["translate"][0]["id"], "zh": "你好"}])

    monkeypatch.setattr(client, "_request", fake_request)

    async def run():
        await client.translate(segments)
        await client.close()

    asyncio.run(run())
    assert "日文视频字幕" in prompts[0]
    assert segments[0].zh == "你好"


def test_transcribe_uses_multilingual_model_and_auto_detection(monkeypatch, tmp_path):
    observed = {}

    class FakeInfo:
        language = "ja"

    class FakeItem:
        start, end, text = 0.0, 1.0, " テスト "

    class FakeWhisperModel:
        def __init__(self, model_name, device, compute_type):
            observed.update(model=model_name, device=device, compute_type=compute_type)

        def transcribe(self, path, language, vad_filter, beam_size):
            observed["language_argument"] = language
            return [FakeItem()], FakeInfo()

    monkeypatch.setattr(pipeline, "WhisperModel", FakeWhisperModel)
    # Moon Add: unit tests must not download model weights from Hugging Face.
    monkeypatch.setattr(pipeline, "_prepare_whisper_model", lambda model, callback: model)
    segments, language = pipeline._transcribe(tmp_path / "audio.wav", "small.en", "cpu")

    assert observed["model"] == "small"
    assert observed["language_argument"] is None
    assert language == "ja"
    assert segments[0].source_language == "ja"


def test_bilibili_japanese_pipeline_writes_site_specific_cache(tmp_path, monkeypatch):
    cache_dir, work_dir = tmp_path / "cache", tmp_path / "work"
    cache_dir.mkdir()
    work_dir.mkdir()

    class FakeClient:
        def __init__(self, config):
            pass

        async def translate(self, segments, progress):
            assert segments[0].source_language == "ja"
            segments[0].zh = "测试"
            progress(1, 1)

        async def summarize(self, title, segments, on_stream, resume_from=""):
            on_stream("## 内容摘要\n摘要")
            return "摘要", ["要点"]

        async def close(self):
            pass

    monkeypatch.setattr(pipeline, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(pipeline, "WORK_DIR", work_dir)
    monkeypatch.setattr(pipeline, "load_config", lambda: ServiceConfig())
    monkeypatch.setattr(pipeline, "LlmClient", FakeClient)
    monkeypatch.setattr(pipeline, "_download", lambda url, directory: (
        {
            "title": "Bilibili Japanese", "duration": 1,
            "_ytba_source": "bilibili_subtitles", "_ytba_language": "ja",
        },
        [Segment(start=0, end=1, en="テスト", source_language="ja")],
        None,
    ))
    job_id = "bilibili-ja-job"
    pipeline.JOBS[job_id] = JobView(
        id=job_id, state="queued", stage="等待处理", progress=0
    )

    asyncio.run(pipeline.process_job(
        job_id, "https://www.bilibili.com/video/BV1test123?p=2"
    ))

    job = pipeline.JOBS.pop(job_id)
    assert job.result.platform == "bilibili"
    assert job.result.source_language == "ja"
    assert job.result.source == "bilibili_subtitles"
    assert job.result.segments[0].zh == "测试"
    assert (cache_dir / "bilibili_BV1test123_p2.v2.json").exists()
# Moon End
