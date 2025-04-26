from fastapi import FastAPI, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.storage import save_to_efs, save_bumper_to_efs
from app.rabbitmq import publish_message, rabbitmq_listener
from app.state import state
import uuid
import os
from datetime import datetime
import hashlib
import asyncio

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(rabbitmq_listener())

@app.get("/check-download/{file_id}")
async def check_download(file_id: str):
    if file_id in state.ready_downloads:
        return JSONResponse(content={"ready": True, "download_url": f"/download/{file_id}"})
    else:
        return JSONResponse(content={"ready": False})

@app.get("/download/{file_id}")
async def download_file(file_id: str):
    file_path = state.ready_downloads.get(file_id)
    if not file_path:
        return {"error": "File not ready yet"}
    return FileResponse(file_path, filename=os.path.basename(file_path))

@app.post("/upload")
async def upload_files(
     ppt: UploadFile = File(...),
     bumper1: UploadFile = File(...),
     bumper2: UploadFile = File(...),
     voice: str = Form(...)
):
    file_id = str(uuid.uuid4())
    job_id = hashlib.sha256(datetime.utcnow().isoformat().encode()).hexdigest()[:10]

    metadata = {
        "event": "ppt-uploaded",
        "filename": ppt.filename,
        "file_path": "/artifacts/powerpoints/"+ppt.filename,
        "upload_time": datetime.utcnow().isoformat(),
        "file_id": file_id,
        "job_id": job_id,
        "voice": voice,
    }

    metadata["file_path"] = save_to_efs(ppt, ppt.filename, metadata)
    save_bumper_to_efs(bumper1, f"{job_id}-bumper1.mp4")
    save_bumper_to_efs(bumper2, f"{job_id}-bumper2.mp4")

    publish_message(metadata)
    print("Powerpoint uploaded and sent with selected voice {voice}...")
    return {"status": "ok", "file_id": file_id, "file_name":ppt.filename}

@app.get("/")
def get_form():
    return FileResponse("static/index.html")
