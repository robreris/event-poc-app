import os
import json
import time
import pika
import boto3
from pathlib import Path

# S3 config from environment
S3_BUCKET = os.getenv("S3_BUCKET")
S3_REGION = os.getenv("S3_REGION", "us-east-1")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY")

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "localhost")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "localhost")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
QUEUE_NAME = "file_processing"
RESPONSE_QUEUE = "windows_response"

TMP_DIR = Path(os.getenv("TMP_DIR", "C:/Temp/pptx-jobs"))
TMP_DIR.mkdir(parents=True, exist_ok=True)

def download_from_s3(s3_key, local_path):
    s3 = boto3.client(
        "s3",
        region_name=S3_REGION,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
    )
    s3.download_file(S3_BUCKET, s3_key, str(local_path))

def enumerate_slides_and_animations(pptx_path):
    # Stub: Replace with actual logic to enumerate slides and animations
    # For now, just return a dummy list
    slides = [
        {"slide_id": 1, "slide_number": 1, "s3_key": None, "title": "Slide 1"},
        {"slide_id": 2, "slide_number": 2, "s3_key": None, "title": "Slide 2"},
    ]
    videos = []
    return slides, videos

def callback(ch, method, properties, body):
    try:
        job = json.loads(body)
        job_id = job.get("job_id")
        pptx_s3_key = job["pptx_s3_key"]
        pptx_filename = job["pptx_file_id"]
        local_pptx = TMP_DIR / f"{job_id}_{pptx_filename}"
        print(f"[INFO] Downloading {pptx_s3_key} from S3 to {local_pptx}")
        download_from_s3(pptx_s3_key, local_pptx)
        print(f"[INFO] Download complete. Enumerating slides and animations...")
        slides, videos = enumerate_slides_and_animations(local_pptx)
        result = {
            "job_id": job_id,
            "slides": slides,
            "videos": videos
        }
        ch.basic_publish(exchange='', routing_key=RESPONSE_QUEUE, body=json.dumps(result))
        print(f"[INFO] Sent result for job {job_id} to {RESPONSE_QUEUE}")
    except Exception as e:
        print(f"[ERROR] {e}")
        ch.basic_publish(exchange='', routing_key=RESPONSE_QUEUE, body=json.dumps({"status": "failed", "error": str(e)}))
    ch.basic_ack(delivery_tag=method.delivery_tag)

def main():
    while True:
        try:
            connection_params = pika.ConnectionParameters(
                host=RABBITMQ_HOST,
                port=RABBITMQ_PORT,
                credentials=pika.PlainCredentials(
                  RABBITMQ_USER,
                  RABBITMQ_PASS
                ),
                heartbeat=600,
                blocked_connection_timeout=300,
                connection_attempts=3,
                retry_delay=5
            )
            connection = pika.BlockingConnection(connection_params)
            channel = connection.channel()
            channel.queue_declare(queue=QUEUE_NAME)
            channel.queue_declare(queue=RESPONSE_QUEUE)
            channel.basic_qos(prefetch_count=1)
            channel.basic_consume(queue=QUEUE_NAME, on_message_callback=callback)
            print("[INFO] Awaiting file processing jobs...")
            channel.start_consuming()
        except Exception as e:
            print(f"[WARN] Could not connect to RabbitMQ: {e}. Retrying in 10s...")
            time.sleep(10)

if __name__ == "__main__":
    main()
