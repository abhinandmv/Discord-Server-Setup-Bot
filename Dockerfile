# Small image for running the bot 24/7 (Railway, Fly.io, a VPS, a Raspberry Pi…).
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/app/data/bot.db

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as a normal user, not root.
RUN useradd --create-home bot && mkdir -p /app/data && chown -R bot /app/data
USER bot

# The SQLite database lives here: mount a volume so it survives redeploys.
VOLUME ["/app/data"]

CMD ["python", "bot.py"]
