# SCI-PATH User Management
# Build from this folder:
#   docker build -t sci-path-um .
# Run:
#   docker run --rm -p 8001:8001 --env-file .env -v um-data:/app/data sci-path-um

FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    CORS_ORIGINS=http://localhost:3000 \
    DATABASE_URL=sqlite:///./data/users.db

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY app ./app

RUN mkdir -p /app/data

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8001/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
