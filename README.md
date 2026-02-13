# yt-video-analyzer

Минимальный Python-сервис для анализа YouTube-видео по субтитрам.

## Что умеет
- Принимает YouTube URL
- Достаёт авто/обычные субтитры через `yt-dlp`
- Чистит транскрипт от таймкодов/мусора
- Делает summary и key points через OpenRouter

## API

### Health
`GET /health`

### Analyze
`POST /analyze`
```json
{
  "url": "https://youtube.com/shorts/VVh_1g3mpj0",
  "lang": "ru,en"
}
```

Ответ:
```json
{
  "url": "...",
  "status": "ok",
  "summary": "...",
  "key_points": ["..."],
  "transcript": "..."
}
```

## Локальный запуск
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

Где хранить cookies: лучше на хосте (например `/opt/masha/cookies/youtube-cookies.txt`) и монтировать в контейнер только для чтения.

## Ограничения MVP
- Whisper fallback пока не реализован (сделан интерфейс и статус `no_subtitles`)
- Нет очереди задач и rate limit
