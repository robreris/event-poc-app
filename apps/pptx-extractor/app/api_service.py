import os
from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename
from pathlib import Path
from tasks import process_pptx  # Import the Celery task

# Configure the upload directory.
# You can use an environment variable to specify the directory path, defaulting to an example path:
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/artifacts/uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)

@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "ok"}), 200

@app.route("/upload", methods=["POST"])
def upload():
    # Check if the file part is in the request
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    # Secure the filename and save the file
    file = request.files["file"]
    filename = secure_filename(file.filename)
    pptx_path = UPLOAD_DIR / filename
    file.save(pptx_path)

    # Optionally, you could log the file upload or record metadata here.

    # Enqueue the task to process the uploaded file asynchronously with Celery.
    # The process_pptx task is expected to accept the file path (as a string) and filename.
    task = process_pptx.delay(str(pptx_path), filename)

    # Return a response containing the task ID for tracking.
    return jsonify({
        "status": "file received",
        "file": filename,
        "task_id": task.id
    }), 202

if __name__ == "__main__":
    # For development, you can run the Flask server directly.
    app.run(host="0.0.0.0", port=5000)

