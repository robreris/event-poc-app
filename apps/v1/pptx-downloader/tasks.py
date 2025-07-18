import os
import json
import boto3
import pika
from pathlib import Path
from celery import Celery

# --- ENVIRONMENT CONFIG ---
RABBITMQ_HOST = os.environ.get("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_USER = os.environ.get("RABBIT_USERNAME", "guest")
RABBITMQ_PASS = os.environ.get("RABBIT_PASSWORD", "guest")
RABBITMQ_PORT = os.environ.get("RABBITMQ_PORT", "5672")
RABBITMQ_VHOST = os.environ.get("RABBITMQ_VHOST", "/")
RESPONSE_QUEUE = os.environ.get("RESPONSE_QUEUE", "windows_response")
RESULT_S3_BUCKET = os.environ.get("RESULT_S3_BUCKET", "your-bucket")

EFS_NOTES_BASE = Path(os.environ.get("EFS_NOTES_BASE", "/artifacts/notes/"))
EFS_SLIDES_BASE = Path(os.environ.get("EFS_SLIDES_BASE", "/artifacts/slides/"))
EFS_NOTES_BASE.mkdir(parents=True, exist_ok=True)
EFS_SLIDES_BASE.mkdir(parents=True, exist_ok=True)

# Celery config (for downstream microservice)
CELERY_BROKER_URL = (
    f"amqp://{RABBITMQ_USER}:{RABBITMQ_PASS}@{RABBITMQ_HOST}:{RABBITMQ_PORT}{RABBITMQ_VHOST}"
)
celery_app = Celery('tasks', broker=CELERY_BROKER_URL)

def download_from_s3(s3_bucket, s3_key, dest_path):
    s3 = boto3.client("s3")
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading s3://{s3_bucket}/{s3_key} --> {dest_path}")
    s3.download_file(s3_bucket, s3_key, str(dest_path))

def download_batch(s3_bucket, s3_prefix, file_list, efs_dir):
    efs_dir = Path(efs_dir)
    efs_dir.mkdir(parents=True, exist_ok=True)
    local_paths = []
    for fname in file_list:
        s3_key = f"{s3_prefix.rstrip('/')}/{fname}"
        dest_path = efs_dir / fname
        download_from_s3(s3_bucket, s3_key, dest_path)
        local_paths.append(str(dest_path))
    return local_paths

def send_to_tts_processor(notes_dir, job_id, voice, tts_engine, piper_args, file_id, slides_dir):
    # Modify args to match tts_processor.synthesize signature
    args = [str(notes_dir), job_id, voice, tts_engine, piper_args, file_id]
    result = celery_app.send_task(
        name="tts_processor.synthesize",
        args=args,
        queue="tts_tasks",
    )
    print(f"Sent task to tts_processor.synthesize: {args}")
    return result

def process_result_message(body):
    result = json.loads(body)
    print(f"Received manifest for job {result.get('job_id')}")
    job_id = result.get("job_id")
    s3_bucket = result.get("s3_bucket") or RESULT_S3_BUCKET

    # Download notes
    notes_s3_prefix = result["notes_s3_prefix"]
    notes_files = result["notes_files"]
    NOTES_JOB_DIR = EFS_NOTES_BASE / job_id
    notes_paths = download_batch(s3_bucket, notes_s3_prefix, notes_files, NOTES_JOB_DIR)

    # Download slides
    slides_s3_prefix = result["slides_s3_prefix"]
    slides_files = result["slides_files"]
    SLIDES_JOB_DIR = EFS_SLIDES_BASE / job_id
    slides_paths = download_batch(s3_bucket, slides_s3_prefix, slides_files, SLIDES_JOB_DIR)

    # Get TTS parameters (customize as needed)
    voice = result.get("voice", "en_US")
    tts_engine = result.get("tts_engine", "piper")
    piper_args = result.get("piper_args", {})
    file_id = result.get("file_id", "")
    
    # Now send task to downstream TTS processor
    send_to_tts_processor(
        notes_dir=NOTES_JOB_DIR,
        job_id=job_id,
        voice=voice,
        tts_engine=tts_engine,
        piper_args=piper_args,
        file_id=file_id,
        slides_dir=SLIDES_JOB_DIR,
    )

def on_result(ch, method, properties, body):
    try:
        process_result_message(body)
    except Exception as e:
        print(f"Error handling result message: {e}")
    ch.basic_ack(delivery_tag=method.delivery_tag)

def main():
    print("Connecting to RabbtiMQ...")
    credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
    params = pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        port=RABBITMQ_PORT,
        virtual_host=RABBITMQ_VHOST,
        credentials=credentials,
        heartbeat=600,
        blocked_connection_timeout=300
    )
    connection = pika.BlockingConnection(params)
    channel = connection.channel()
    channel.queue_declare(queue=RESPONSE_QUEUE, durable=True)
    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=RESPONSE_QUEUE, on_message_callback=on_result)
    print(f"Listening for results on {RESPONSE_QUEUE} ...")
    channel.start_consuming()

if __name__ == "__main__":
    main()


