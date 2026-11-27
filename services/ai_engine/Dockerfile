FROM python:3.12-slim-bookworm@sha256:44cf1793efa7c7a476bb0f2cff81443f4a072c90c1cb127e2924933daa3e8c64

ARG PYTORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
ARG VMS_BUILD_VERSION=0.1.0-rc3
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 VMS_BUILD_VERSION=${VMS_BUILD_VERSION}
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.lock.txt /app/backend/requirements.lock.txt
RUN pip install --no-cache-dir -r backend/requirements.lock.txt
RUN pip install --no-cache-dir torch==2.11.0 torchvision==0.26.0 --index-url ${PYTORCH_INDEX_URL}
RUN pip install --no-cache-dir opencv-python-headless scipy
COPY backend/ /app/backend/
COPY services/ai_engine/ /app/services/ai_engine/
RUN useradd --uid 10002 --create-home aiworker && mkdir -p /app/storage/recordings && chown -R aiworker:aiworker /app/storage /home/aiworker
USER aiworker
CMD ["python", "-m", "services.ai_engine.worker"]
