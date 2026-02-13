from app.services.analyzer import _build_subtitles_cmd


def test_build_subtitles_cmd_without_cookies(monkeypatch):
    monkeypatch.delenv("YTDLP_COOKIES_PATH", raising=False)
    monkeypatch.delenv("YTDLP_MANUAL_MODE", raising=False)
    cmd = _build_subtitles_cmd("https://youtu.be/abc", "ru,en")
    assert "--cookies" not in cmd
    assert "--write-subs" in cmd


def test_build_subtitles_cmd_with_cookies(monkeypatch):
    monkeypatch.setenv("YTDLP_COOKIES_PATH", "/app/cookies.txt")
    monkeypatch.delenv("YTDLP_MANUAL_MODE", raising=False)
    cmd = _build_subtitles_cmd("https://youtu.be/abc", "ru,en")
    assert "--cookies" in cmd
    idx = cmd.index("--cookies")
    assert cmd[idx + 1] == "/app/cookies.txt"


def test_build_subtitles_cmd_manual_mode(monkeypatch):
    monkeypatch.setenv("YTDLP_MANUAL_MODE", "true")
    cmd = _build_subtitles_cmd("https://youtu.be/abc", "ru,en")
    assert "--write-subs" not in cmd
