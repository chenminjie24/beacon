FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md alembic.ini /app/
COPY alembic /app/alembic
COPY sql /app/sql
COPY src /app/src

RUN pip install --upgrade pip && pip install -e ".[api,db]"

EXPOSE 8080
CMD ["uvicorn", "relay.main:app", "--host", "0.0.0.0", "--port", "8080"]
