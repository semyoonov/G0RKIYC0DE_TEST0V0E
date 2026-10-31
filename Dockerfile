FROM node:22-slim AS frontend

WORKDIR /app/frontend

RUN npm config set fetch-retries 5 \
    && npm config set fetch-retry-mintimeout 10000 \
    && npm config set fetch-retry-maxtimeout 60000 \
    && (npm install -g pnpm@9 || npm install -g pnpm@9 --registry=https://registry.npmmirror.com)

COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml frontend/.npmrc ./
RUN pnpm install --frozen-lockfile || pnpm install --frozen-lockfile --registry=https://registry.npmmirror.com || pnpm install --no-frozen-lockfile --registry=https://registry.npmmirror.com

COPY frontend/ ./
RUN pnpm build


FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg espeak-ng ca-certificates curl unzip \
    && rm -rf /var/lib/apt/lists/*

# GigaChat, SaluteSpeech и MAX Bot API подписаны Russian Trusted Root CA; без него
# TLS-проверка к этим хостам падает, и пришлось бы отключать verify.
ARG RUSSIAN_CA_URL=https://gu-st.ru/content/lending/russian_trusted_root_ca_pem.crt
RUN curl -fsSL --retry 3 --retry-delay 3 "$RUSSIAN_CA_URL" -o /usr/local/share/ca-certificates/russian_trusted_root_ca.crt \
    && update-ca-certificates

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && python -c "import certifi, pathlib; bundle = pathlib.Path(certifi.where()); extra = pathlib.Path('/usr/local/share/ca-certificates/russian_trusted_root_ca.crt').read_text().strip(); bundle.write_text(bundle.read_text() + chr(10) + extra + chr(10))"

COPY . .
COPY --from=frontend /app/frontend/dist ./frontend/dist

# Модель Vosk лежит в репозитории (models/vosk-model-small-ru-0.22): сборка не скачивает её из сети.
RUN test -d models/vosk-model-small-ru-0.22 || (echo "Vosk model is missing from models/" && exit 1)

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && python main.py"]
