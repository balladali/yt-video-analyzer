from app.services.analyzer import _build_subtitles_cmd, _runtime_debug_info, _normalize_langs


def test_build_subtitles_cmd_without_cookies(monkeypatch):
    monkeypatch.delenv("YTDLP_COOKIES_PATH", raising=False)
    monkeypatch.delenv("YTDLP_MANUAL_MODE", raising=False)
    monkeypatch.delenv("YTDLP_INCLUDE_REGULAR_SUBS", raising=False)
    cmd = _build_subtitles_cmd("https://youtu.be/abc", "ru,en")
    assert "--cookies" not in cmd
    assert "--write-subs" not in cmd
    assert "--js-runtimes" in cmd
    assert "--ignore-no-formats-error" in cmd


def test_build_subtitles_cmd_with_cookies(monkeypatch):
    monkeypatch.delenv("YTDLP_MANUAL_MODE", raising=False)
    cmd = _build_subtitles_cmd("https://youtu.be/abc", "ru,en", cookies_arg_path="/tmp/cookies.txt")
    assert "--cookies" in cmd
    idx = cmd.index("--cookies")
    assert cmd[idx + 1] == "/tmp/cookies.txt"


def test_build_subtitles_cmd_manual_mode(monkeypatch):
    monkeypatch.setenv("YTDLP_MANUAL_MODE", "true")
    cmd = _build_subtitles_cmd("https://youtu.be/abc", "ru,en")
    assert "--write-subs" not in cmd


def test_build_subtitles_cmd_include_regular_subs(monkeypatch):
    monkeypatch.setenv("YTDLP_MANUAL_MODE", "false")
    monkeypatch.setenv("YTDLP_INCLUDE_REGULAR_SUBS", "true")
    cmd = _build_subtitles_cmd("https://youtu.be/abc", "ru,en")
    assert "--write-subs" in cmd


def test_normalize_langs_default_chain(monkeypatch):
    monkeypatch.delenv("YTDLP_SUB_LANGS", raising=False)
    assert _normalize_langs("ru,en") == "ru,ru-orig,en,en-orig"


def test_runtime_debug_info(monkeypatch, tmp_path):
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    monkeypatch.setenv("YTDLP_COOKIES_PATH", str(cookie_file))
    monkeypatch.setenv("YTDLP_MANUAL_MODE", "true")

    info = _runtime_debug_info()
    assert info["cookies_configured"] is True
    assert info["cookies_file_exists"] is True
    assert info["manual_mode"] is True
