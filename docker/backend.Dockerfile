FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml README.md alembic.ini ./
COPY backend ./backend
COPY migrations ./migrations
COPY config ./config
COPY examples ./examples
RUN pip install --no-cache-dir .

EXPOSE 8000
CMD ["sh", "-c", "python -m backend.app.wait_for_db && python -m backend.app.database_preflight && python -m alembic upgrade head && python -m backend.app.database_preflight --require-head && exec uvicorn backend.app.main:app --host 0.0.0.0 --port 8000"]
