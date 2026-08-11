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


def test_page_subtitles_are_used_before_whisper_fallback(tmp_path, monkeypatch):
    # Moon Add: Bilibili page tracks cover captions yt-dlp may not enumerate.
    page_segments = [Segment(start=0, end=1, en="Page caption", source_language="en")]
    monkeypatch.setattr(pipeline, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(pipeline, "WORK_DIR", tmp_path / "work")
    monkeypatch.setattr(pipeline, "_download", lambda *args: (_ for _ in ()).throw(AssertionError("不应下载音频")))
    class FakeClient:
        def __init__(self, config): pass
        async def translate(self, segments, progress):
            segments[0].zh="页面字幕";progress(1,1)
        async def summarize(self, title, segments, on_stream, resume_from=""):
            on_stream("## 内容摘要\n摘要\n\n## 关键点\n- 要点");return "摘要",["要点"]
        async def close(self): pass
    monkeypatch.setattr(pipeline, "LlmClient", FakeClient)
    monkeypatch.setattr(pipeline, "load_config", lambda: ServiceConfig())
    (tmp_path / "cache").mkdir();(tmp_path / "work").mkdir()
    job_id="page-subtitle-job"
    pipeline.JOBS[job_id]=JobView(id=job_id,state="queued",stage="等待处理",progress=0)
    asyncio.run(pipeline.process_job(job_id,"https://www.bilibili.com/video/BV1test",page_segments,"en"))
    job=pipeline.JOBS.pop(job_id)
    assert job.result.source == "bilibili_subtitles"
    assert job.result.segments[0].en == "Page caption"


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
    progress = []
    previews = []

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
    segments, language = pipeline._transcribe(
        tmp_path / "audio.wav", "small.en", "cpu",
        transcription_progress=lambda current, total: progress.append((current, total)),
        expected_duration=12.0,
        transcription_preview=lambda items, language: previews.append((items, language)),
    )

    assert observed["model"] == "small"
    assert observed["language_argument"] is None
    assert language == "ja"
    assert segments[0].source_language == "ja"
    assert progress == [(0, 12.0), (1.0, 12.0)]
    assert previews[0] == ([], "ja")
    assert previews[-1][1] == "ja"
    assert previews[-1][0][0].en == "テスト"


def test_transcribe_auto_falls_back_when_cuda_fails_during_iteration(monkeypatch, tmp_path):
    """CTranslate2 may load cuBLAS only after the lazy iterator starts."""
    # Moon Begin
    observed_devices = []
    progress = []

    class FakeInfo:
        language = "en"

    class FakeItem:
        start, end, text = 0.0, 1.0, " hello "

    class FakeWhisperModel:
        def __init__(self, model_name, device, compute_type):
            self.device = device
            observed_devices.append(device)

        def transcribe(self, *args, **kwargs):
            if self.device == "cuda":
                def broken_iterator():
                    raise RuntimeError("Library cublas64_12.dll is not found")
                    yield
                return broken_iterator(), FakeInfo()
            return [FakeItem()], FakeInfo()

    import ctranslate2
    monkeypatch.setattr(ctranslate2, "get_cuda_device_count", lambda: 1)
    monkeypatch.setattr(pipeline, "WhisperModel", FakeWhisperModel)
    monkeypatch.setattr(pipeline, "_prepare_whisper_model", lambda model, callback: model)

    segments, language = pipeline._transcribe(
        tmp_path / "audio.wav", "small", "auto",
        lambda *values: progress.append(values),
    )

    assert observed_devices == ["cuda", "cpu"]
    assert language == "en"
    assert segments[0].en == "hello"
    assert progress[-1][-1] == "GPU 运行库不可用，已降级 CPU"
    # Moon End


def test_prepare_whisper_model_reuses_complete_legacy_model(monkeypatch, tmp_path):
    # Moon Add: an existing application model must bypass all network access.
    model_dir = tmp_path / "models" / "small"
    model_dir.mkdir(parents=True)
    for name in ("config.json", "model.bin", "tokenizer.json"):
        (model_dir / name).write_bytes(b"cached")
    (model_dir / ".ytba-model-size").write_text("6")
    monkeypatch.setattr(pipeline, "CACHE_DIR", tmp_path / "cache")
    progress = []
    assert pipeline._prepare_whisper_model(
        "small.en", lambda *args: progress.append(args)
    ) == str(model_dir)
    assert progress == [(100, 6, 6, 0, "本机缓存")]


def test_inspect_whisper_model_reports_complete_and_partial_models(monkeypatch, tmp_path):
    # Moon Add: interrupted downloads must explain the missing file while complete models remain reusable.
    models = tmp_path / "models"
    small = models / "small"
    medium = models / "medium"
    small.mkdir(parents=True)
    medium.mkdir(parents=True)
    for name in ("config.json", "tokenizer.json", "model.bin"):
        (small / name).write_bytes(b"complete")
    (small / ".ytba-model-size").write_text(str(len(b"complete")))
    for name in ("config.json", "tokenizer.json"):
        (medium / name).write_bytes(b"partial")
    monkeypatch.setattr(pipeline, "CACHE_DIR", tmp_path / "cache")
    # Moon Add: isolate this fixture from real models installed in the user's shared HF cache.
    monkeypatch.setattr(
        pipeline, "_whisper_model_candidates",
        lambda model, configured_path="", install_dir="": [models / model],
    )
    monkeypatch.setattr(pipeline, "load_config", lambda: ServiceConfig(whisper_model="medium"))

    small_status = pipeline.inspect_whisper_model("small")
    medium_status = pipeline.inspect_whisper_model("medium")

    assert small_status.valid is True
    assert small_status.resolved_path == str(small.resolve())
    assert medium_status.valid is False
    assert medium_status.stage == "模型未完整安装"
    assert medium_status.missing_files == ["model.bin"]
    assert any(item.model == "small" and item.valid for item in medium_status.local_models)


def test_new_model_download_reports_live_bytes_and_speed(monkeypatch, tmp_path):
    # Moon Add: tqdm must keep its internal counters even when console rendering is suppressed.
    import huggingface_hub
    from huggingface_hub import constants

    class File:
        rfilename = "model.bin"
        size = 100

    class Info:
        siblings = [File()]

    class FakeApi:
        def __init__(self, endpoint):
            self.endpoint = endpoint

        def model_info(self, *args, **kwargs):
            return Info()

    destination = tmp_path / "downloaded-model"

    def fake_snapshot_download(repo_id, endpoint, allow_patterns, tqdm_class, **kwargs):
        bar = tqdm_class(total=100, initial=0)
        bar.update(40)
        bar.close()
        destination.mkdir()
        (destination / "model.bin").write_bytes(b"x" * 100)
        return str(destination)

    monkeypatch.setattr(constants, "HF_HUB_CACHE", str(tmp_path / "hf-cache"))
    monkeypatch.setattr(huggingface_hub, "HfApi", FakeApi)
    monkeypatch.setattr(huggingface_hub, "snapshot_download", fake_snapshot_download)
    monkeypatch.setattr(pipeline, "CACHE_DIR", tmp_path / "app" / "cache")
    updates = []

    assert pipeline._prepare_whisper_model(
        "base", lambda *values: updates.append(values), download_source="official",
    ) == str(destination)
    assert any(0 < percent < 100 and downloaded == 40 and speed > 0 for percent, downloaded, _, speed, _ in updates)


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
