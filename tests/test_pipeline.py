from service.app.pipeline import video_id_from_url


def test_video_id_from_watch_url():
    assert video_id_from_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_video_id_from_short_url():
    assert video_id_from_url("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
