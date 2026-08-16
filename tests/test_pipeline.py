from service.app import pipeline
from service.app.pipeline import cache_key_from_url, platform_from_url, video_id_from_url


def test_video_id_from_watch_url():
    assert video_id_from_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_video_id_from_short_url():
    assert video_id_from_url("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_bilibili_video_id_and_part_cache_key():
    # Moon Add
    url = "https://www.bilibili.com/video/BV1GJ411x7h7?p=3"
    assert video_id_from_url(url) == "BV1GJ411x7h7"
    assert platform_from_url(url) == "bilibili"
    assert cache_key_from_url(url) == "bilibili_BV1GJ411x7h7_p3"


def test_bilibili_live_player_cid_scopes_page_subtitle_cache():
    # Moon Add: the current player can differ from the URL's p after SPA navigation.
    url = "https://www.bilibili.com/video/BV1GJ411x7h7?p=3&ytba_cid=987654"
    assert cache_key_from_url(url) == "bilibili_BV1GJ411x7h7_cid987654"


def test_bilibili_page_caption_cache_schema_invalidates_stale_player_results():
    # Moon Modified: version 6 does not reuse caches created from a stale player CID.
    assert pipeline.CACHE_SCHEMA_VERSION == 6


def test_truncated_media_download_error_is_retryable():
    # Moon Add: an advertised length larger than the received bytes is a transient CDN failure.
    assert pipeline._is_retryable_media_download_error(
        RuntimeError("Downloaded 801884 bytes, expected 47146339 bytes")
    )
    assert not pipeline._is_retryable_media_download_error(RuntimeError("视频需要登录"))


def test_truncated_download_failure_uses_actionable_message(monkeypatch):
    # Moon Add: users should see a retry action, not yt-dlp's raw Content-Length exception.
    import asyncio

    job = pipeline.JobView(id="truncated", state="queued", stage="等待处理", progress=0)
    pipeline.JOBS[job.id] = job
    async def fail_download(*_args):
        raise RuntimeError("ERROR: [download] Got error: Downloaded 1 bytes, expected 2 bytes")
    monkeypatch.setattr(pipeline, "process_job", fail_download)
    asyncio.run(pipeline._run_job(job.id, "https://www.bilibili.com/video/BV1test"))
    assert job.stage == "音频下载多次中断"
    assert job.error == "B 站音频下载多次中断，请稍后点击重试"
    pipeline.JOBS.pop(job.id, None)


def test_bilibili_bangumi_id():
    assert video_id_from_url("https://www.bilibili.com/bangumi/play/ep12345") == "ep12345"
