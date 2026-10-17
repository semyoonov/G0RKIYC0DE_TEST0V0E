FROM node:22-slim AS frontend

WORKDIR /app/frontend

RUN npm install -g pnpm@11

COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

COPY frontend/ ./
RUN pnpm build


FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates curl unzip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=frontend /app/frontend/dist ./frontend/dist

ARG VOSK_MODEL_URL=https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip
RUN mkdir -p models \
    && curl -fsSL "$VOSK_MODEL_URL" -o /tmp/vosk-model.zip \
    && unzip -q /tmp/vosk-model.zip -d models \
    && rm /tmp/vosk-model.zip

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && python main.py"]
