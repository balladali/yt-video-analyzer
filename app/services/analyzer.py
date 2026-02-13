import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List

import requests


def _run(cmd: List[str], cwd: str | None = None) -> None:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{p.stderr}")


def _extract_subtitles(url: str, langs: str, workdir: str) -> str | None:
    lang_list = langs.replace(" ", "")
    cmd = [
        "yt-dlp",
        "--write-auto-subs",
        "--write-subs",
        "--sub-langs",
        lang_list,
        "--skip-download",
        "-o",
        "%(id)s.%(ext)s",
        url,
    ]
    _run(cmd, cwd=workdir)

    for ext in ("*.vtt", "*.srt"):
        files = list(Path(workdir).glob(ext))
        if files:
            return files[0].read_text(encoding="utf-8", errors="ignore")
    return None


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
    with tempfile.TemporaryDirectory(prefix="ytva-") as td:
        raw_subs = _extract_subtitles(url, langs, td)

        if not raw_subs:
            return {
                "url": url,
                "status": "no_subtitles",
                "summary": "Субтитры не найдены. Нужен fallback через Whisper (ещё не реализован).",
                "key_points": [],
                "transcript": "",
            }

        transcript = _clean_vtt(raw_subs)
        llm = _summarize_with_llm(transcript)

        return {
            "url": url,
            "status": "ok",
            "summary": llm.get("summary", ""),
            "key_points": llm.get("key_points", []),
            "transcript": transcript,
        }
