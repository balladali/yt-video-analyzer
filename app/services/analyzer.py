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
    logger.debug("Running command: %s (cwd=%s)", cmd, cwd)
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if p.returncode != 0:
        logger.debug("Command failed rc=%s stderr=%s", p.returncode, (p.stderr or "")[-3000:])
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{p.stderr}")
    logger.debug("Command ok rc=%s stderr_tail=%s", p.returncode, (p.stderr or "")[-1000:])
    return p.stderr or ""


def _normalize_langs(langs: str | None) -> str:
    default_langs = os.getenv("YTDLP_SUB_LANGS", "ru,ru-orig")
    if not langs or not langs.strip() or langs.strip() == "ru,en":
        return default_langs
    return langs.replace(" ", "")


def _fallback_langs() -> str:
    return os.getenv("YTDLP_SUB_LANGS_FALLBACK", "en,en-orig").replace(" ", "")


def _build_subtitles_cmd(
    url: str,
    langs: str,
    cookies_arg_path: str | None = None,
    include_regular_subs_override: bool | None = None,
) -> List[str]:
    lang_list = _normalize_langs(langs)
    manual_mode = os.getenv("YTDLP_MANUAL_MODE", "true").lower() in {"1", "true", "yes", "on"}
    include_regular_subs = os.getenv("YTDLP_INCLUDE_REGULAR_SUBS", "false").lower() in {"1", "true", "yes", "on"}
    if include_regular_subs_override is not None:
        include_regular_subs = include_regular_subs_override

    cmd = [
        "yt-dlp",
        "--write-auto-subs",
        "--sub-langs",
        lang_list,
        "--skip-download",
        "--ignore-no-formats-error",
        "--js-runtimes",
        "node",
        "--remote-components",
        "ejs:github",
    ]

    extractor_args = os.getenv("YTDLP_EXTRACTOR_ARGS", "").strip()
    if extractor_args:
        cmd.extend(["--extractor-args", extractor_args])

    # To reduce request footprint, regular subtitles are OFF by default.
    # Enable with YTDLP_INCLUDE_REGULAR_SUBS=true when needed.
    if include_regular_subs and (include_regular_subs_override is True or not manual_mode):
        cmd.insert(2, "--write-subs")

    if cookies_arg_path:
        cmd.extend(["--cookies", cookies_arg_path])

    cmd.extend(["-o", "%(id)s.%(ext)s", url])
    return cmd


def _prepare_cookies_path(workdir: str) -> str | None:
    cookies_path = os.getenv("YTDLP_COOKIES_PATH", "").strip()
    if not cookies_path:
        logger.debug("Cookies path is not configured")
        return None

    src = Path(cookies_path)
    if not src.exists():
        logger.debug("Cookies file does not exist: %s", cookies_path)
        return None
    if src.is_dir():
        logger.debug("Cookies path points to a directory, expected file: %s", cookies_path)
        return None

    # Copy to writable temp path to avoid yt-dlp save errors on read-only mounts.
    dst = Path(workdir) / "cookies.txt"
    shutil.copyfile(src, dst)
    logger.debug("Copied cookies file to temp path: %s", dst)
    return str(dst)


def _list_subs_debug(url: str, langs: str, cookies_arg_path: str | None = None) -> Dict:
    cmd = [
        "yt-dlp",
        "--list-subs",
        "--sub-langs",
        _normalize_langs(langs),
        "--skip-download",
        "--ignore-no-formats-error",
        "--js-runtimes",
        "node",
        "--remote-components",
        "ejs:github",
    ]
    extractor_args = os.getenv("YTDLP_EXTRACTOR_ARGS", "").strip()
    if extractor_args:
        cmd.extend(["--extractor-args", extractor_args])
    if cookies_arg_path:
        cmd.extend(["--cookies", cookies_arg_path])
    cmd.append(url)

    logger.debug("Running list-subs debug command: %s", cmd)
    p = subprocess.run(cmd, capture_output=True, text=True)
    return {
        "list_subs_command": cmd,
        "list_subs_rc": p.returncode,
        "list_subs_stdout": (p.stdout or "")[-20000:],
        "list_subs_stderr": (p.stderr or "")[-20000:],
    }


def _extract_subtitles(
    url: str,
    langs: str,
    workdir: str,
    include_regular_subs_override: bool | None = None,
    run_list_subs_debug: bool = False,
) -> tuple[str | None, str, List[str], Dict]:
    cookies_arg_path = _prepare_cookies_path(workdir)
    list_subs_debug = _list_subs_debug(url, langs, cookies_arg_path=cookies_arg_path) if run_list_subs_debug else {}
    cmd = _build_subtitles_cmd(
        url,
        langs,
        cookies_arg_path=cookies_arg_path,
        include_regular_subs_override=include_regular_subs_override,
    )
    stderr = _run(cmd, cwd=workdir)
    workdir_files = sorted([p.name for p in Path(workdir).glob("*")])

    for ext in ("*.vtt", "*.srt"):
        files = list(Path(workdir).glob(ext))
        logger.debug("Subtitle scan for %s found %d files", ext, len(files))
        if files:
            file_path = files[0]
            size = file_path.stat().st_size if file_path.exists() else 0
            logger.debug("Using subtitle file: %s (size=%d bytes)", file_path, size)

            preview = ""
            try:
                preview = file_path.read_text(encoding="utf-8", errors="ignore")[:160]
            except Exception:
                preview = ""
            logger.debug("Subtitle preview: %s", preview.replace("\n", " "))

            return (
                file_path.read_text(encoding="utf-8", errors="ignore"),
                stderr,
                cmd,
                {
                    "subtitle_file_found": True,
                    "subtitle_file_path": str(file_path),
                    "subtitle_file_size": size,
                    "subtitle_preview": preview,
                    "workdir_files": workdir_files,
                    "stderr_len": len(stderr or ""),
                    **list_subs_debug,
                },
            )

    logger.debug("No subtitle files found in workdir=%s", workdir)
    return None, stderr, cmd, {
        "subtitle_file_found": False,
        "subtitle_file_path": "",
        "subtitle_file_size": 0,
        "subtitle_preview": "",
        "workdir_files": workdir_files,
        "stderr_len": len(stderr or ""),
        **list_subs_debug,
    }


def _runtime_debug_info() -> Dict:
    cookies_path = os.getenv("YTDLP_COOKIES_PATH", "").strip()
    manual_mode = os.getenv("YTDLP_MANUAL_MODE", "true").lower() in {"1", "true", "yes", "on"}
    include_regular_subs = os.getenv("YTDLP_INCLUDE_REGULAR_SUBS", "false").lower() in {"1", "true", "yes", "on"}
    fallback_regular_on_empty = os.getenv("YTDLP_FALLBACK_REGULAR_ON_EMPTY", "true").lower() in {"1", "true", "yes", "on"}
    fallback_langs_on_empty = os.getenv("YTDLP_FALLBACK_LANGS_ON_EMPTY", "true").lower() in {"1", "true", "yes", "on"}
    keep_tmp = os.getenv("YTDLP_KEEP_TMP", "false").lower() in {"1", "true", "yes", "on"}
    return {
        "cookies_configured": bool(cookies_path),
        "cookies_file_exists": bool(cookies_path and Path(cookies_path).exists()),
        "manual_mode": manual_mode,
        "include_regular_subs": include_regular_subs,
        "fallback_regular_on_empty": fallback_regular_on_empty,
        "fallback_langs_on_empty": fallback_langs_on_empty,
        "keep_tmp": keep_tmp,
        "sub_langs_default": os.getenv("YTDLP_SUB_LANGS", "ru,ru-orig"),
        "sub_langs_fallback": _fallback_langs(),
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


def _cache_get(url: str, langs: str, user_prompt: str | None = None) -> Dict | None:
    ttl = _cache_ttl_sec()
    if ttl <= 0:
        return None
    key = (url, _normalize_langs(langs), (user_prompt or "").strip())
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


def _cache_put(url: str, langs: str, payload: Dict, user_prompt: str | None = None) -> None:
    ttl = _cache_ttl_sec()
    if ttl <= 0:
        return
    key = (url, _normalize_langs(langs), (user_prompt or "").strip())
    with _CACHE_LOCK:
        _ANALYZE_CACHE[key] = (time.time(), dict(payload))


def _summarize_with_llm(text: str, user_prompt: str | None = None) -> Dict:
    api_key = os.getenv("OPENROUTER_API_KEY")
    model = os.getenv("LLM_MODEL", "openai/gpt-4o-mini")
    if not api_key:
        return {
            "summary": "OPENROUTER_API_KEY не задан — возвращаю только транскрипт.",
            "key_points": [],
        }

    normalized_prompt = (user_prompt or "").strip()
    is_default_analyze = (not normalized_prompt) or bool(re.search(r"проанализир(?:уй|овать|уйте)|анализ", normalized_prompt, re.IGNORECASE))

    if is_default_analyze:
        prompt = (
            "Сделай краткий разбор видео по транскрипту. "
            "Верни JSON с полями summary (строка) и key_points (массив строк, 5-8 пунктов)."
        )
    else:
        prompt = (
            "Выполни задачу пользователя строго по транскрипту видео. "
            "Если данных в транскрипте недостаточно, так и скажи. "
            "Верни JSON с полями summary (основной ответ пользователю) и key_points (массив коротких пунктов, 3-8).\n"
            f"Задача пользователя: {normalized_prompt}"
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
                {"role": "system", "content": "Ты помощник для анализа видео по субтитрам. Отвечай по запросу пользователя, без выдумок."},
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


def analyze_video(url: str, langs: str = "ru,en", user_prompt: str | None = None) -> Dict:
    debug_mode = os.getenv("YTDLP_DEBUG", "false").lower() in {"1", "true", "yes", "on"}
    keep_tmp = os.getenv("YTDLP_KEEP_TMP", "false").lower() in {"1", "true", "yes", "on"}
    runtime_debug = _runtime_debug_info()

    cached = _cache_get(url, langs, user_prompt=user_prompt)
    if cached is not None:
        logger.debug("Cache hit for url=%s langs=%s", url, _normalize_langs(langs))
        cached["cache_hit"] = True
        if debug_mode:
            cached.setdefault("debug_info", {})
            cached["debug_info"]["cache_ttl_sec"] = _cache_ttl_sec()
        return cached

    td = tempfile.mkdtemp(prefix="ytva-")
    try:
        primary_langs = _normalize_langs(langs)
        fallback_langs = _fallback_langs()
        cmd_preview = _build_subtitles_cmd(url, primary_langs)
        fallback_regular_on_empty = runtime_debug.get("fallback_regular_on_empty", True)
        fallback_langs_on_empty = runtime_debug.get("fallback_langs_on_empty", True)
        if debug_mode:
            logger.info("yt-dlp analyze start: url=%s, manual_mode=%s, cookies_configured=%s, cookies_file_exists=%s", url, runtime_debug["manual_mode"], runtime_debug["cookies_configured"], runtime_debug["cookies_file_exists"])
            logger.debug("yt-dlp primary command preview: %s", cmd_preview)

        try:
            raw_subs, stderr, used_cmd, file_debug = _extract_subtitles(
                url,
                primary_langs,
                td,
                run_list_subs_debug=debug_mode,
            )
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
                    "tmp_dir": td,
                    "tmp_kept": keep_tmp,
                }
                out["debug"] = msg[-3000:]
            _cache_put(url, langs, out, user_prompt=user_prompt)
            return out

        if not raw_subs and fallback_regular_on_empty:
            try:
                raw_subs, stderr_fallback, used_cmd_fallback, file_debug_fallback = _extract_subtitles(
                    url,
                    primary_langs,
                    td,
                    include_regular_subs_override=True,
                    run_list_subs_debug=debug_mode,
                )
                if raw_subs:
                    file_debug = file_debug_fallback
                stderr = (stderr or "") + "\n" + (stderr_fallback or "")
                used_cmd = used_cmd_fallback
                if debug_mode:
                    logger.info("yt-dlp fallback with regular subtitles enabled for url=%s", url)
            except Exception:
                logger.exception("yt-dlp fallback extraction failed for url=%s", url)

        if not raw_subs and fallback_langs_on_empty and fallback_langs and fallback_langs != primary_langs:
            try:
                raw_subs, stderr_lang_fallback, used_cmd_lang_fallback, file_debug_lang_fallback = _extract_subtitles(
                    url,
                    fallback_langs,
                    td,
                    include_regular_subs_override=False,
                    run_list_subs_debug=debug_mode,
                )
                if raw_subs:
                    file_debug = file_debug_lang_fallback
                stderr = (stderr or "") + "\n" + (stderr_lang_fallback or "")
                used_cmd = used_cmd_lang_fallback
                if debug_mode:
                    logger.info("yt-dlp fallback with fallback langs (%s) for url=%s", fallback_langs, url)
            except Exception:
                logger.exception("yt-dlp fallback langs extraction failed for url=%s", url)

        if not raw_subs and fallback_regular_on_empty and fallback_langs_on_empty and fallback_langs and fallback_langs != primary_langs:
            try:
                raw_subs, stderr_lang_regular, used_cmd_lang_regular, file_debug_lang_regular = _extract_subtitles(
                    url,
                    fallback_langs,
                    td,
                    include_regular_subs_override=True,
                    run_list_subs_debug=debug_mode,
                )
                if raw_subs:
                    file_debug = file_debug_lang_regular
                stderr = (stderr or "") + "\n" + (stderr_lang_regular or "")
                used_cmd = used_cmd_lang_regular
                if debug_mode:
                    logger.info("yt-dlp fallback with regular subtitles on fallback langs (%s) for url=%s", fallback_langs, url)
            except Exception:
                logger.exception("yt-dlp fallback regular+langs extraction failed for url=%s", url)

        if debug_mode and not raw_subs:
            logger.debug("No subtitles after primary+fallback attempts for url=%s", url)

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
                    "yt_dlp_command": used_cmd if 'used_cmd' in locals() else cmd_preview,
                    "tmp_dir": td,
                    "tmp_kept": keep_tmp,
                    **(file_debug if 'file_debug' in locals() else {}),
                }
                if stderr:
                    out["debug"] = stderr[-3000:]
                    out["stderr_full"] = stderr[-20000:]
            _cache_put(url, langs, out, user_prompt=user_prompt)
            return out

        transcript = _clean_vtt(raw_subs)
        llm = _summarize_with_llm(transcript, user_prompt=user_prompt)

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
                "yt_dlp_command": used_cmd if 'used_cmd' in locals() else cmd_preview,
                "tmp_dir": td,
                "tmp_kept": keep_tmp,
                **(file_debug if 'file_debug' in locals() else {}),
            }
            if stderr:
                out["debug"] = stderr[-1000:]
                out["stderr_full"] = stderr[-20000:]
        _cache_put(url, langs, out, user_prompt=user_prompt)
        return out
    finally:
        if keep_tmp:
            logger.info("Keeping temp directory for debug: %s", td)
        else:
            shutil.rmtree(td, ignore_errors=True)
