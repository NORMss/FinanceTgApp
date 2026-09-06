FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Слой зависимостей кэшируется отдельно от кода
COPY pyproject.toml ./
RUN pip install --no-cache-dir . && pip uninstall -y financetg-backend

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /app /data
USER appuser

EXPOSE 8000

# Миграции накатываются на старте — для однопроцессного приложения это безопасно
#
# --no-server-header: не сообщаем сканерам, что внутри uvicorn и какой версии
# --timeout-keep-alive 65: дольше, чем держит простаивающее соединение прокси перед ним
#   (у Caddyfile из комплекта — 30с). Закрывать переиспользуемое соединение должен тот,
#   кто его открыл: если первым это делает приложение, прокси успевает отправить запрос
#   в уже закрытое соединение и отвечает 502, хотя приложение живо и здорово.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log --no-server-header --workers 1 --timeout-keep-alive 65"]
