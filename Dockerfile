FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
RUN groupadd --system workbuddy && useradd --system --gid workbuddy --home-dir /app workbuddy
COPY pyproject.toml README.md /app/
COPY src /app/src
COPY migrations /app/migrations
COPY alembic.ini /app/alembic.ini
COPY config /app/config
COPY scripts /app/scripts
RUN pip install . && mkdir -p /app/var/objects && chown -R workbuddy:workbuddy /app

USER workbuddy
EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=5s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" || exit 1

CMD ["uvicorn", "workbuddy.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
