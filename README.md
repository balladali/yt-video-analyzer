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

Полезные env-переменные:
- `YTDLP_COOKIES_PATH` — путь к cookies внутри контейнера (например `/app/cookies.txt`)
- `YTDLP_EXTRACTOR_ARGS` — опциональные extractor-args для yt-dlp (по умолчанию пусто; не форсим player_client)
- `YTDLP_MANUAL_MODE=true` — запускать yt-dlp в режиме, максимально близком к ручной команде
- `YTDLP_INCLUDE_REGULAR_SUBS=false` — не дёргать обычные сабы в первой попытке (меньше запросов к YouTube)
- `YTDLP_FALLBACK_REGULAR_ON_EMPTY=true` — если авто-сабы пустые, сделать fallback-попытку с обычными сабами
- `YTDLP_SUB_LANGS=ru,ru-orig` — первичная языковая цепочка (сначала пробуем только RU)
- `YTDLP_FALLBACK_LANGS_ON_EMPTY=true` — при пустом результате сделать fallback по языкам
- `YTDLP_SUB_LANGS_FALLBACK=en,en-orig` — fallback-языки (только если RU не удалось)
- `LLM_TEMPERATURE=0.35` — креативность ответа LLM (выше = более вариативно, но меньше строгости)
- `YTDLP_DEBUG=true` — добавлять debug-поле с хвостом ошибки yt-dlp в ответ API
- `YTDLP_KEEP_TMP=false` — сохранять `/tmp/ytva-*` после анализа для ручной диагностики файлов
- `ANALYZE_CACHE_TTL_SEC=900` — кэш результатов по URL, чтобы не ходить в YouTube повторно
- `LOG_LEVEL=INFO|DEBUG` — уровень логирования сервиса

Примечание: сервис копирует cookies во временный writable файл перед запуском `yt-dlp`, поэтому безопасный read-only mount (`:ro`) поддерживается.

## Ограничения MVP
- Whisper fallback пока не реализован (сделан интерфейс и статус `no_subtitles`)
- Нет очереди задач и rate limit
