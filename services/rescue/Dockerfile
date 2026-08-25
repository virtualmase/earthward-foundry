# Earthward Rescue Task Force service — self-contained image.
# Build from the repo root or from this directory:
#   docker build -t earthward-rescue services/rescue
# Run:
#   docker run -p 5001:5001 -e RESCUE_API_KEY=... -v rescue-data:/app/data earthward-rescue

FROM python:3.12-slim

WORKDIR /app

# Install dependencies first so they're cached independently of source changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# The SQLite file is the whole incident log — keep it on a mountable path so
# a container recreate doesn't silently drop the append-only record.
ENV RESCUE_DB_PATH=/app/data/earthward_rescue.db
RUN mkdir -p /app/data

# Never run the service as root.
RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

ENV PYTHONUNBUFFERED=1 \
    RESCUE_API_HOST=0.0.0.0 \
    RESCUE_API_PORT=5001

EXPOSE 5001

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python3 -c "import urllib.request,sys,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"RESCUE_API_PORT\",5001)}/health', timeout=2)" || exit 1

CMD ["gunicorn", "--workers", "1", "--threads", "4", "--bind", "0.0.0.0:5001", "wsgi:app"]
