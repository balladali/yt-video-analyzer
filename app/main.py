from fastapi import FastAPI
from pydantic import BaseModel, HttpUrl

from app.services.analyzer import analyze_video

app = FastAPI(title="yt-video-analyzer", version="0.1.0")


class AnalyzeRequest(BaseModel):
    url: HttpUrl
    lang: str = "ru,en"


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    result = analyze_video(str(req.url), req.lang)
    return result
