from app.services.analyzer import _clean_vtt


def test_clean_vtt_removes_headers_timestamps_and_tags():
    raw = """WEBVTT
Kind: captions
Language: ru

00:00:00.100 --> 00:00:01.200 align:start position:0%
Привет<00:00:00.500><c> мир</c>

00:00:01.200 --> 00:00:02.200
Привет мир
"""
    cleaned = _clean_vtt(raw)
    assert "WEBVTT" not in cleaned
    assert "-->" not in cleaned
    assert "<c>" not in cleaned
    # duplicate line should be collapsed
    assert cleaned == "Привет мир"
