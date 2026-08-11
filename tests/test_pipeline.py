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


def test_bilibili_bangumi_id():
    assert video_id_from_url("https://www.bilibili.com/bangumi/play/ep12345") == "ep12345"
