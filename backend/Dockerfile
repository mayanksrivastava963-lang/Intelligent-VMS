FROM node:24-bookworm-slim@sha256:873f586f3794f52281bd039bf02c048a0be08fde619338f9941bad1eb6b34530 AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm@sha256:44cf1793efa7c7a476bb0f2cff81443f4a072c90c1cb127e2924933daa3e8c64
ARG VMS_BUILD_VERSION=0.1.0-rc3
ARG VMS_BUILD_SHA=dev
ARG VMS_BUILD_TIMESTAMP=
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    VMS_BUILD_VERSION=${VMS_BUILD_VERSION} \
    VMS_BUILD_SHA=${VMS_BUILD_SHA} \
    VMS_BUILD_TIMESTAMP=${VMS_BUILD_TIMESTAMP}
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt /app/backend/requirements.txt
COPY backend/requirements.lock.txt /app/backend/requirements.lock.txt
RUN pip install --no-cache-dir -r backend/requirements.lock.txt
COPY backend/ /app/backend/
COPY services/recording_engine/ /app/services/recording_engine/
COPY --from=frontend /build/dist /app/frontend/dist
RUN useradd --uid 10001 --create-home recorder && mkdir -p /app/storage/recordings && chown -R recorder:recorder /app/storage
USER recorder
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
