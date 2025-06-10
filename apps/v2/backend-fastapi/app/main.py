from fastapi import FastAPI, UploadFile, File, Form, Request, APIRouter
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from app.storage import save_to_efs, save_bumper_to_efs
from app.rabbitmq import publish_message, rabbitmq_listener
from app.state import state
from typing import List
import uuid
import os
from datetime import datetime
import hashlib
import asyncio

app = FastAPI()
router = APIRouter()
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(rabbitmq_listener())

@app.get("/debug-ready")
async def debug_ready():
    return state.ready_downloads

@app.get("/check-download/{file_id}")
async def check_download(file_id: str):
    print(f"check-download called for file_id: {file_id}")
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
     videos: List[UploadFile] = File(...),
     voice: str = Form(...)
):
    # 1. Generate a unique job_id for this upload session
    job_id = str(uuid.uuid4())
    pptx_file_id = str(uuid.uuid4())

    pptx_filename = f"{job_id}_{pptx_file_id}_{ppt.filename}"
    pptx_nfs_path = save_to_efs(ppt, pptx_filename, {"job_id": job_id, "file_id": pptx_file_id})

    video_infos = []
    for vid in videos:
        video_id = str(uuid.uuid4())
        video_filename = f"{job_id}_{video_id}_{vid.filename}"
        video_nfs_path = save_to_efs(vid, video_filename, {"job_id": job_id, "file_id": video_id})
        video_infos.append({
            "file_id": video_id,
            "filename": vid.filename,
            "nfs_path": video_nfs_path,
        })

    # 4. (Placeholder) Generate slide metadata—replace with real extraction later
    slides = [
        {"slide_id": i+1, "slide_number": i+1, "nfs_path": f"/nfs/slides/{job_id}_slide_{i+1}.png"}
        for i in range(3)
    ]

    # 5. Return ALL real metadata for frontend tracking
    return {
        "job_id": job_id,
        "pptx_file_id": pptx_file_id,
        "pptx_filename": ppt.filename,
        "pptx_nfs_path": pptx_nfs_path,
        "videos": video_infos,
        "tts_voice": voice,
        "slides": slides,
    }    

@app.post("/job/submit")
async def submit_job(request: Request):
    data = await request.json()

    job_id = hashlib.sha256(datetime.utcnow().isoformat().encode()).hexdigest()[:10]

    publish_message({
        "event": "process-sequence",
        "job_id": job_id,
        **data
    })
    print("Powerpoint uploaded and sent with selected voice {voice}...")
    return {"job_id": job_id}

@app.get("/")
def get_form():
    return FileResponse("static/index.html")
