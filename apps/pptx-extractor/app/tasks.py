import os
from celery import Celery
from pathlib import Path
from note_extractor import extract_notes
from image_extractor import convert_pptx_to_images

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

# Configure the Celery app.
# Replace 'RABBITMQ_HOST' with your actual RabbitMQ host name or IP.
celery_app = Celery(
    'tasks',
    broker=CELERY_BROKER_URL
)

# Configure where to store the slide images.
SLIDES_DIR = Path(os.getenv("SLIDES_DIR", "/artifacts/slides/"))
SLIDES_DIR.mkdir(parents=True, exist_ok=True)

NOTES_DIR = Path(os.getenv("NOTES_DIR", "/artifacts/notes/"))
NOTES_DIR.mkdir(parents=True, exist_ok=True)

@celery_app.task(queue='ppt_tasks', name="tasks.process_pptx")
def process_pptx(file_path, filename, job_id):
    """
    Processes the PowerPoint file by extracting notes and converting slides to images.
    """
    print(f"Called process_pptx, file_path: {file_path}")
    pptx_path = Path(file_path)
    try:
        # Extract notes from the PowerPoint file.
        print("Extracting notes...")
        NOTES_JOB_DIR = NOTES_DIR / job_id
        NOTES_JOB_DIR.mkdir(parents=True, exist_ok=True)
        extract_notes(pptx_path, NOTES_JOB_DIR)

        print("Converting pptx to images...")
        # Convert PPTX slides to images.
        IMS_JOB_DIR = SLIDES_DIR / job_id
        IMS_JOB_DIR.mkdir(parents=True, exist_ok=True)
        convert_pptx_to_images(pptx_path, IMS_JOB_DIR)
        # Optionally, you can store or send results here (e.g., update a database).
        result = {
            "status": "processed",
            "filename": filename,
            "job_id": job_id,
            "slides_processed": len(list(SLIDES_DIR.glob("slide_*.png")))
        }
        print(f"Successfully processed {filename}: {result}")
        return result
    except Exception as e:
        # Handle exceptions, log errors, or trigger retries as needed.
        error_result = {"status": "error", "filename": filename, "job_id": job_id, "error": str(e)}
        print(f"Error processing {filename}: {error_result}")
        return error_result

