import os
from celery import Celery
from pathlib import Path
from note_extractor import extract_notes
from image_extractor import convert_pptx_to_images

# Configure the Celery app.
# Replace 'RABBITMQ_HOST' with your actual RabbitMQ host name or IP.
celery_app = Celery(
    'tasks',
    broker=os.getenv("CELERY_BROKER_URL", "pyamqp://guest@RABBITMQ_HOST//")
)

# Configure where to store the slide images.
SLIDES_DIR = Path(os.getenv("SLIDES_DIR", "/artifacts/slides"))
SLIDES_DIR.mkdir(parents=True, exist_ok=True)

@celery_app.task(queue='ppt_tasks')
def process_pptx(file_path, filename):
    """
    Processes the PowerPoint file by extracting notes and converting slides to images.
    """
    pptx_path = Path(file_path)
    try:
        # Extract notes from the PowerPoint file.
        notes = extract_notes(pptx_path)
        # Convert PPTX slides to images.
        convert_pptx_to_images(pptx_path, SLIDES_DIR)
        # Optionally, you can store or send results here (e.g., update a database).
        result = {
            "status": "processed",
            "filename": filename,
            "slides_processed": len(list(SLIDES_DIR.glob("slide_*.png")))
        }
        print(f"Successfully processed {filename}: {result}")
        return result
    except Exception as e:
        # Handle exceptions, log errors, or trigger retries as needed.
        error_result = {"status": "error", "filename": filename, "error": str(e)}
        print(f"Error processing {filename}: {error_result}")
        return error_result

