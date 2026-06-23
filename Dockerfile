# Praxis backend — the FastAPI agent API.
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PRAXIS_MEMORY_PATH=/data/memory.sqlite

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY praxis ./praxis

# Persistent memory lives on a mounted volume so learning survives restarts.
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8000
# Defaults to the offline simulation (no API keys needed). For a real Linear
# workspace, set ANTHROPIC_API_KEY + LINEAR_API_KEY and append `--live`.
CMD ["python", "-m", "praxis", "serve", "--offline", "--host", "0.0.0.0", "--port", "8000"]
