FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
# ROLE: api (requests), worker (periodic jobs + Telegram bot) or all (both, one process - the default).
# WEB_CONCURRENCY: processes serving requests in this container (api/all).
CMD ["sh", "-c", "if [ \"${ROLE:-all}\" = worker ]; then exec uvicorn server:app --host 0.0.0.0 --port 8000 --workers 1; else exec uvicorn server:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY:-1}; fi"]
