FROM python:3.11-slim

WORKDIR /app

# Install FFmpeg
RUN apt-get update && apt-get install -y ffmpeg && apt-get clean

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
