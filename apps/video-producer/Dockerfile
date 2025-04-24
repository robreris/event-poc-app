FROM python:3.11-slim

WORKDIR /app
COPY . /app

# Install FFmpeg
RUN apt-get update && apt-get install -y ffmpeg && apt-get clean

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

CMD ["celery", "-A", "ffmpeg_service", "worker", "--loglevel=info", "-Q", "video_producer"]
