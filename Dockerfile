FROM python:3.12-slim

WORKDIR /app

# libmagic1 is required by python-magic (real file-content sniffing for
# upload validation) — the slim base image does NOT include it by default;
# omitting this line would make uploads fail at runtime, not at build time.
RUN apt-get update && apt-get install -y --no-install-recommends libmagic1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY data/ ./data/

# Cloud Run injects PORT — default to 8080 for local docker run
ENV PORT=8080
EXPOSE 8080

CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
