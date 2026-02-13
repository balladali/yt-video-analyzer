import logging
import os
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel, HttpUrl

from app.services.analyzer import analyze_video

log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, log_level, logging.INFO), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("yt-video-analyzer")

app = FastAPI(title="yt-video-analyzer", version="0.1.0")


class AnalyzeRequest(BaseModel):
    url: HttpUrl
    lang: str = "ru,en"


@app.on_event("startup")
def on_startup():
    cookies_path = os.getenv("YTDLP_COOKIES_PATH", "").strip()
    manual_mode = os.getenv("YTDLP_MANUAL_MODE", "false").lower() in {"1", "true", "yes", "on"}
    debug_mode = os.getenv("YTDLP_DEBUG", "false").lower() in {"1", "true", "yes", "on"}

    logger.info(
        "startup config: manual_mode=%s, ytdlp_debug=%s, cookies_configured=%s, cookies_file_exists=%s, cookies_path=%s",
        manual_mode,
        debug_mode,
        bool(cookies_path),
        bool(cookies_path and Path(cookies_path).exists()),
        cookies_path or "<not-set>",
    )


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    result = analyze_video(str(req.url), req.lang)
    return result
