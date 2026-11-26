FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
RUN pip install --no-cache-dir torch==2.11.0 torchvision==0.26.0 --index-url https://download.pytorch.org/whl/cu128
RUN pip install --no-cache-dir opencv-python-headless scipy
COPY backend/ /app/backend/
COPY services/ai_engine/ /app/services/ai_engine/
RUN useradd --uid 10002 --create-home aiworker && mkdir -p /app/storage/recordings && chown -R aiworker:aiworker /app/storage /home/aiworker
USER aiworker
CMD ["python", "-m", "services.ai_engine.worker"]
