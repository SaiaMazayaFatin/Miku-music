FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends openjdk-17-jre-headless \
    && rm -rf /var/lib/apt/lists/*

COPY . /app

RUN pip install --no-cache-dir \
    "discord-py>=2.7.1" \
    "python-dotenv>=1.1.1" \
    "pynacl>=1.6.2" \
    "wavelink>=3.4.1" \
    "yt-dlp>=2026.3.17"

RUN chmod +x /app/start.sh

EXPOSE 10000

CMD ["/app/start.sh"]
