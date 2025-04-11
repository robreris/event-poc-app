from fastapi import FastAPI, UploadFile, File
from app.storage import save_to_efs
from app.rabbitmq import publish_message
import uuid
import os
from datetime import datetime

app = FastAPI()

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    file_id = str(uuid.uuid4())
    saved_path = save_to_efs(file, file_id)

    metadata = {
        "filename": file.filename,
        "upload_time": datetime.utcnow().isoformat(),
        "path": saved_path,
        "file_id": file_id
    }

    publish_message(metadata)
    return {"status": "ok", "file_id": file_id}
