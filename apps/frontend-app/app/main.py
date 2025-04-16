from fastapi import FastAPI, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.storage import save_to_efs
from app.rabbitmq import publish_message
import uuid
import os
from datetime import datetime
import hashlib

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    file_id = str(uuid.uuid4())

    metadata = {
        "event": "ppt-uploaded",
        "filename": file.filename,
        "file_path": "/artifacts/powerpoints/"+file.filename,
        "upload_time": datetime.utcnow().isoformat(),
        "file_id": file_id,
        "job_id": hashlib.sha256(datetime.utcnow().isoformat().encode()).hexdigest()[:10]
    }

    metadata["file_path"] = save_to_efs(file, file.filename, metadata)
    publish_message(metadata)
    print("Powerpoint uploaded and sent...")
    return {"status": "ok", "file_id": file_id, "file_name":file.filename}

@app.get("/")
def get_form():
    return FileResponse("static/index.html")
