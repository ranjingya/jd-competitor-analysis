FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.8.22 /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app ./app
COPY jd_competitor_analysis ./jd_competitor_analysis
COPY assets ./assets

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    REPORTS_DIR=/app/data/reports \
    TASK_DATABASE_PATH=/app/data/analysis-tasks.db

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
