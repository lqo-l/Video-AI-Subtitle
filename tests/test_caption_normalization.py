from service.app.models import Segment
from service.app.pipeline import _normalize_rolling_captions


def test_rolling_captions_remove_overlapping_words():
    # Moon Begin: reproduce YouTube's expanding and sliding automatic captions.
    raw = [
        Segment(start=2, end=4, en="Hello everyone. This is Reza. Welcome to"),
        Segment(start=2.5, end=5, en="Hello everyone. This is Reza. Welcome to the very first lesson. In this one,"),
        Segment(start=5, end=7, en="the very first lesson. In this one, we're starting from a completely empty"),
        Segment(start=7, end=10, en="we're starting from a completely empty level and building the foundation of the whole course."),
    ]

    normalized = _normalize_rolling_captions(raw)
    transcript = " ".join(item.en for item in normalized)

    assert transcript.count("Hello everyone.") == 1
    assert transcript.count("the very first lesson.") == 1
    assert transcript.count("we're starting from a completely empty") == 1
    assert transcript.endswith("whole course.")
    assert all(item.start < item.end for item in normalized)
    assert all(left.end <= right.end for left, right in zip(normalized, normalized[1:]))
    # Moon End


def test_japanese_rolling_captions_remove_overlapping_characters():
    # Moon Begin
    raw = [
        Segment(start=0, end=2, en="今日は良い天気", source_language="ja"),
        Segment(start=1, end=3, en="今日は良い天気ですね。", source_language="ja"),
        Segment(start=3, end=5, en="ですね。散歩に行きましょう！", source_language="ja"),
    ]

    normalized = _normalize_rolling_captions(raw)
    transcript = "".join(item.en for item in normalized)

    assert transcript == "今日は良い天気ですね。散歩に行きましょう！"
    assert all(item.source_language == "ja" for item in normalized)
    assert all(item.start < item.end for item in normalized)
    # Moon End
