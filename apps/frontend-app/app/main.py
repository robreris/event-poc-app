from fastapi import FastAPI, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.storage import save_to_efs, save_bumper_to_efs
from app.rabbitmq import publish_message
import uuid
import os
from datetime import datetime
import hashlib

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.post("/upload")
async def upload_files(
     ppt: UploadFile = File(...),
     bumper1: UploadFile = File(...),
     bumper2: UploadFile = File(...)
):
    file_id = str(uuid.uuid4())
    job_id = hashlib.sha256(datetime.utcnow().isoformat().encode()).hexdigest()[:10]

    metadata = {
        "event": "ppt-uploaded",
        "filename": ppt.filename,
        "file_path": "/artifacts/powerpoints/"+ppt.filename,
        "upload_time": datetime.utcnow().isoformat(),
        "file_id": file_id,
        "job_id": job_id
    }

    metadata["file_path"] = save_to_efs(ppt, ppt.filename, metadata)
    save_bumper_to_efs(bumper1, f"{job_id}-bumper1.mp4")
    save_bumper_to_efs(bumper2, f"{job_id}-bumper2.mp4")

    publish_message(metadata)
    print("Powerpoint uploaded and sent...")
    return {"status": "ok", "file_id": file_id, "file_name":ppt.filename}

@app.get("/")
def get_form():
    return FileResponse("static/index.html")
