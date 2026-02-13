import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List

import requests

logger = logging.getLogger(__name__)


def _run(cmd: List[str], cwd: str | None = None) -> str:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{p.stderr}")
    return p.stderr or ""


def _build_subtitles_cmd(url: str, langs: str) -> List[str]:
    lang_list = langs.replace(" ", "")
    manual_mode = os.getenv("YTDLP_MANUAL_MODE", "false").lower() in {"1", "true", "yes", "on"}

    cmd = ["yt-dlp", "--write-auto-subs", "--sub-langs", lang_list, "--skip-download"]

    # Default mode tries both regular and auto subtitles.
    # Manual mode mimics the successful host command as close as possible.
    if not manual_mode:
        cmd.insert(2, "--write-subs")

    cookies_path = os.getenv("YTDLP_COOKIES_PATH", "").strip()
    if cookies_path:
        cmd.extend(["--cookies", cookies_path])

    cmd.extend(["-o", "%(id)s.%(ext)s", url])
    return cmd


def _extract_subtitles(url: str, langs: str, workdir: str) -> tuple[str | None, str]:
    cmd = _build_subtitles_cmd(url, langs)
    stderr = _run(cmd, cwd=workdir)

    for ext in ("*.vtt", "*.srt"):
        files = list(Path(workdir).glob(ext))
        if files:
            return files[0].read_text(encoding="utf-8", errors="ignore"), stderr
    return None, stderr


def _runtime_debug_info() -> Dict:
    cookies_path = os.getenv("YTDLP_COOKIES_PATH", "").strip()
    manual_mode = os.getenv("YTDLP_MANUAL_MODE", "false").lower() in {"1", "true", "yes", "on"}
    return {
        "cookies_configured": bool(cookies_path),
        "cookies_file_exists": bool(cookies_path and Path(cookies_path).exists()),
        "manual_mode": manual_mode,
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
        return out
