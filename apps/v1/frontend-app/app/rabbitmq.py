import os
from celery import Celery
import json
import aio_pika
from app.state import state

# Environment-based configuration
RABBITMQ_HOST = os.environ.get("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_USER = os.environ.get("RABBIT_USERNAME", "guest")
RABBITMQ_PASS = os.environ.get("RABBIT_PASSWORD", "guest")
RABBITMQ_PORT = os.environ.get("RABBITMQ_PORT", "5672")
RABBITMQ_VHOST = os.environ.get("RABBITMQ_VHOST", "/")

# Full AMQP broker URL
CELERY_BROKER_URL = (
    f"amqp://{RABBITMQ_USER}:{RABBITMQ_PASS}@{RABBITMQ_HOST}:{RABBITMQ_PORT}{RABBITMQ_VHOST}"
)

# Set up the Celery client (does NOT run tasks—just enqueues them)
celery_app = Celery(
    'tasks',
    broker=CELERY_BROKER_URL
)

def publish_message(data: dict):
    """
    Publishes a message that invokes the 'process_pptx' task on the worker.
    The task must be registered as @celery_app.task in the worker side.
    """
    task_name = "tasks.process_pptx"  # must match your worker task name
    args = [data["file_path"], data["filename"], data["file_id"], data["job_id"], data["voice"], data["tts_engine"], data["piper_args"]]  # match task signature

    result = celery_app.send_task(
        name=task_name,
        args=args,
        queue="ppt_tasks",  # must match queue in @task(queue='ppt_tasks')
    )

    print(f"Task {result.id} published to queue 'ppt_tasks'.")

async def rabbitmq_listener():
    print("Starting RabbitMQ listener...")
    try:
        connection = await aio_pika.connect_robust(CELERY_BROKER_URL)
        channel = await connection.channel()
        queue = await channel.declare_queue("download_ready", durable=True)

        async with queue.iterator() as queue_iter:
            async for message in queue_iter:
                async with message.process():
                    try:
                        data = json.loads(message.body)
                        print(f"Received download-ready message: {data}")
                        if data["event"] == "artifact-ready":
                            file_path = data["file_path"]
                            file_id = data["file_id"]
                            job_id = data["job_id"]
                            state.ready_downloads[file_id] = file_path
                            print(f"Video from job with id {job_id} associated with file id {file_id} ready at {file_path}")
                    except Exception as inner:
                        print(f"Error handling message: {inner}") 
    except Exception as outer:
        print(f"Failed to connect or consume RabbitMQ: {outer}")
