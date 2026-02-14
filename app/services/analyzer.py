import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from threading import Lock
from typing import Dict, List

import requests

logger = logging.getLogger(__name__)

_ANALYZE_CACHE: dict[tuple[str, str], tuple[float, Dict]] = {}
_CACHE_LOCK = Lock()


def _run(cmd: List[str], cwd: str | None = None) -> str:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{p.stderr}")
    return p.stderr or ""


def _normalize_langs(langs: str | None) -> str:
    default_langs = os.getenv("YTDLP_SUB_LANGS", "ru,ru-orig,en,en-orig")
    if not langs or not langs.strip() or langs.strip() == "ru,en":
        return default_langs
    return langs.replace(" ", "")


def _build_subtitles_cmd(url: str, langs: str, cookies_arg_path: str | None = None) -> List[str]:
    lang_list = _normalize_langs(langs)
    manual_mode = os.getenv("YTDLP_MANUAL_MODE", "true").lower() in {"1", "true", "yes", "on"}
    include_regular_subs = os.getenv("YTDLP_INCLUDE_REGULAR_SUBS", "false").lower() in {"1", "true", "yes", "on"}

    cmd = [
        "yt-dlp",
        "--write-auto-subs",
        "--sub-langs",
        lang_list,
        "--skip-download",
        "--ignore-no-formats-error",
        "--js-runtimes",
        "node",
        "--extractor-args",
        "youtube:player_client=web,android",
    ]

    # To reduce request footprint, regular subtitles are OFF by default.
    # Enable with YTDLP_INCLUDE_REGULAR_SUBS=true when needed.
    if include_regular_subs and not manual_mode:
        cmd.insert(2, "--write-subs")

    if cookies_arg_path:
        cmd.extend(["--cookies", cookies_arg_path])

    cmd.extend(["-o", "%(id)s.%(ext)s", url])
    return cmd


def _prepare_cookies_path(workdir: str) -> str | None:
    cookies_path = os.getenv("YTDLP_COOKIES_PATH", "").strip()
    if not cookies_path:
        return None

    src = Path(cookies_path)
    if not src.exists():
        return None

    # Copy to writable temp path to avoid yt-dlp save errors on read-only mounts.
    dst = Path(workdir) / "cookies.txt"
    shutil.copyfile(src, dst)
    return str(dst)


def _extract_subtitles(url: str, langs: str, workdir: str) -> tuple[str | None, str]:
    cookies_arg_path = _prepare_cookies_path(workdir)
    cmd = _build_subtitles_cmd(url, langs, cookies_arg_path=cookies_arg_path)
    stderr = _run(cmd, cwd=workdir)

    for ext in ("*.vtt", "*.srt"):
        files = list(Path(workdir).glob(ext))
        if files:
            return files[0].read_text(encoding="utf-8", errors="ignore"), stderr
    return None, stderr


def _runtime_debug_info() -> Dict:
    cookies_path = os.getenv("YTDLP_COOKIES_PATH", "").strip()
    manual_mode = os.getenv("YTDLP_MANUAL_MODE", "true").lower() in {"1", "true", "yes", "on"}
    include_regular_subs = os.getenv("YTDLP_INCLUDE_REGULAR_SUBS", "false").lower() in {"1", "true", "yes", "on"}
    return {
        "cookies_configured": bool(cookies_path),
        "cookies_file_exists": bool(cookies_path and Path(cookies_path).exists()),
        "manual_mode": manual_mode,
        "include_regular_subs": include_regular_subs,
        "sub_langs_default": os.getenv("YTDLP_SUB_LANGS", "ru,ru-orig,en,en-orig"),
    }


def _clean_vtt(text: str) -> str:
    lines = text.splitlines()
    cleaned: List[str] = []
    ts = re.compile(r"^\d{2}:\d{2}:\d{2}\.\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}\.\d{3}")

    for ln in lines:
        ln = ln.strip()
        if not ln or ln.startswith("WEBVTT") or ln.startswith("Kind:") or ln.startswith("Language:"):
            continue
        if ts.match(ln):
            continue
        ln = re.sub(r"<[^>]+>", "", ln)
        if ln:
            cleaned.append(ln)

    deduped: List[str] = []
    prev = ""
    for ln in cleaned:
        if ln != prev:
            deduped.append(ln)
        prev = ln

    return "\n".join(deduped).strip()


def _cache_ttl_sec() -> int:
    raw = os.getenv("ANALYZE_CACHE_TTL_SEC", "900").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 900


def _cache_get(url: str, langs: str) -> Dict | None:
    ttl = _cache_ttl_sec()
    if ttl <= 0:
        return None
    key = (url, _normalize_langs(langs))
    now = time.time()
    with _CACHE_LOCK:
        item = _ANALYZE_CACHE.get(key)
        if not item:
            return None
        ts, payload = item
        if now - ts > ttl:
            _ANALYZE_CACHE.pop(key, None)
            return None
        return dict(payload)


def _cache_put(url: str, langs: str, payload: Dict) -> None:
    ttl = _cache_ttl_sec()
    if ttl <= 0:
        return
    key = (url, _normalize_langs(langs))
    with _CACHE_LOCK:
        _ANALYZE_CACHE[key] = (time.time(), dict(payload))


def _summarize_with_llm(text: str) -> Dict:
    api_key = os.getenv("OPENROUTER_API_KEY")
    model = os.getenv("LLM_MODEL", "openai/gpt-4o-mini")
    if not api_key:
        return {
            "summary": "OPENROUTER_API_KEY не задан — возвращаю только транскрипт.",
            "key_points": [],
        }

    prompt = (
        "Сделай краткий разбор видео по транскрипту. "
        "Верни JSON с полями summary (строка) и key_points (массив строк, 5-8 пунктов)."
    )

    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "Ты помощник для анализа видео по субтитрам."},
                {"role": "user", "content": f"{prompt}\n\nТранскрипт:\n{text[:12000]}"},
            ],
            "temperature": 0.2,
        },
        timeout=60,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]

    import json

    try:
        parsed = json.loads(content)
    except Exception:
        parsed = {"summary": content, "key_points": []}
    return parsed


def analyze_video(url: str, langs: str = "ru,en") -> Dict:
    debug_mode = os.getenv("YTDLP_DEBUG", "false").lower() in {"1", "true", "yes", "on"}
    runtime_debug = _runtime_debug_info()

    cached = _cache_get(url, langs)
    if cached is not None:
        cached["cache_hit"] = True
        if debug_mode:
            cached.setdefault("debug_info", {})
            cached["debug_info"]["cache_ttl_sec"] = _cache_ttl_sec()
        return cached

    with tempfile.TemporaryDirectory(prefix="ytva-") as td:
        cmd_preview = _build_subtitles_cmd(url, langs)
        if debug_mode:
            logger.info("yt-dlp analyze start: url=%s, manual_mode=%s, cookies_configured=%s, cookies_file_exists=%s", url, runtime_debug["manual_mode"], runtime_debug["cookies_configured"], runtime_debug["cookies_file_exists"])

        try:
            raw_subs, stderr = _extract_subtitles(url, langs, td)
        except Exception as e:
            msg = str(e)
            status = "extract_error"
            if "Sign in to confirm you’re not a bot" in msg or "Sign in to confirm you're not a bot" in msg:
                status = "blocked_by_youtube"

            logger.exception("yt-dlp subtitle extraction failed for url=%s", url)

            out = {
                "url": url,
                "status": status,
                "summary": "Не удалось получить субтитры с YouTube.",
                "key_points": [],
                "transcript": "",
            }
            if debug_mode:
                out["debug_info"] = {
                    **runtime_debug,
                    "yt_dlp_command": cmd_preview,
                }
                out["debug"] = msg[-3000:]
            _cache_put(url, langs, out)
            return out

        if not raw_subs:
            out = {
                "url": url,
                "status": "no_subtitles",
                "summary": "Субтитры не найдены. Нужен fallback через Whisper (ещё не реализован).",
                "key_points": [],
                "transcript": "",
            }
            if debug_mode:
                out["debug_info"] = {
                    **runtime_debug,
                    "yt_dlp_command": cmd_preview,
                }
                if stderr:
                    out["debug"] = stderr[-3000:]
            _cache_put(url, langs, out)
            return out

        transcript = _clean_vtt(raw_subs)
        llm = _summarize_with_llm(transcript)

        out = {
            "url": url,
            "status": "ok",
            "summary": llm.get("summary", ""),
            "key_points": llm.get("key_points", []),
            "transcript": transcript,
        }
        if debug_mode:
            out["debug_info"] = {
                **runtime_debug,
                "yt_dlp_command": cmd_preview,
            }
            if stderr:
                out["debug"] = stderr[-1000:]
        _cache_put(url, langs, out)
        return out
