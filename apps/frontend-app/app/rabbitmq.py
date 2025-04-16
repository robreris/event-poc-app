import os
from celery import Celery
import json

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
celery_app = Celery(broker=CELERY_BROKER_URL)

def publish_message(data: dict):
    """
    Publishes a message that invokes the 'process_pptx' task on the worker.
    The task must be registered as @celery_app.task in the worker side.
    """
    task_name = "tasks.process_pptx"  # must match your worker task name
    args = [data["file_path"], data["filename"]]  # match task signature

    result = celery_app.send_task(
        name=task_name,
        args=args,
        queue="ppt_tasks",  # must match queue in @task(queue='ppt_tasks')
    )

    print(f"Task {result.id} published to queue 'ppt_tasks'.")
