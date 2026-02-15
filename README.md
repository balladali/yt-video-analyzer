# yt-video-analyzer

A minimal Python service that analyzes YouTube videos using subtitles.

## Features
- Accepts a YouTube URL
- Fetches auto/manual subtitles via `yt-dlp`
- Cleans subtitle transcript (timestamps/noise removal)
- Generates an `answer` via OpenRouter
- Supports optional custom user instruction via `user_prompt`

## API

### Health
`GET /health`

### Analyze
`POST /analyze`

Request body:
```json
{
  "url": "https://youtube.com/shorts/VVh_1g3mpj0",
  "lang": "ru,en",
  "user_prompt": "Give me 5 key takeaways"
}
```

Response (success):
```json
{
  "url": "...",
  "status": "ok",
  "answer": "...",
  "transcript": "..."
}
```

Notes:
- `user_prompt` is optional.
- If `user_prompt` is empty or similar to "analyze", a default analysis prompt is used.

Possible non-`ok` statuses:
- `no_subtitles`
- `extract_error`
- `blocked_by_youtube`

## Local Run
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export OPENROUTER_API_KEY=...
uvicorn app.main:app --reload --port 8000
```

## Docker
```bash
docker build -t yt-video-analyzer .
docker run --rm -p 8000:8000 \
  -e OPENROUTER_API_KEY=... \
  -e YTDLP_COOKIES_PATH=/app/cookies.txt \
  -v /opt/masha/cookies/youtube-cookies.txt:/app/cookies.txt:ro \
  yt-video-analyzer
```

Recommended cookies location: host filesystem (for example `/opt/masha/cookies/youtube-cookies.txt`) mounted read-only into the container.

## Environment Variables

### LLM
- `OPENROUTER_API_KEY` — OpenRouter API key
- `LLM_MODEL=openai/gpt-4o-mini` — OpenRouter model
- `LLM_TEMPERATURE=0.35` — response creativity (higher = more variation, less strictness)

### Subtitle extraction (yt-dlp)
- `YTDLP_COOKIES_PATH=/app/cookies.txt` — path to cookies file inside container
- `YTDLP_EXTRACTOR_ARGS=` — optional extractor args for `yt-dlp`
- `YTDLP_MANUAL_MODE=true` — run `yt-dlp` in manual-like mode
- `YTDLP_INCLUDE_REGULAR_SUBS=false` — do not request regular subtitles on first attempt
- `YTDLP_FALLBACK_REGULAR_ON_EMPTY=true` — fallback to regular subtitles if auto-subs are empty
- `YTDLP_SUB_LANGS=ru,ru-orig` — primary subtitle language chain
- `YTDLP_FALLBACK_LANGS_ON_EMPTY=true` — try fallback languages when primary returns empty
- `YTDLP_SUB_LANGS_FALLBACK=en,en-orig` — fallback language chain
- `YTDLP_KEEP_TMP=false` — keep `/tmp/ytva-*` folders for debugging
- `YTDLP_DEBUG=false` — include extended yt-dlp diagnostics in API output

### Runtime
- `ANALYZE_CACHE_TTL_SEC=900` — in-memory cache TTL for repeated URL requests
- `LOG_LEVEL=INFO|DEBUG` — service log verbosity

## Notes
- The service copies cookies into a temporary writable file before running `yt-dlp`, so read-only cookies mount (`:ro`) is supported.
- YouTube behavior can be non-deterministic (IP/region/time/challenges), so occasional subtitle extraction failures are expected.

## MVP Limitations
- Whisper fallback is not implemented yet
- No job queue / no explicit rate limiting
