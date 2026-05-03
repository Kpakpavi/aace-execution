FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy

RUN pip install --no-cache-dir uv

COPY aace-execution/pyproject.toml aace-execution/uv.lock* /app/

COPY aace-execution/ /app/

RUN uv sync --frozen --no-dev || uv sync --no-dev

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "aace_execution.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
