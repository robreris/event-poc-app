from fastapi import FastAPI, UploadFile, File, Form, Request, APIRouter, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from app.storage import save_to_efs, save_bumper_to_efs, generate_presigned_url
from app.rabbitmq import publish_message, rabbitmq_listener
from app.state import state
from typing import List, Dict, Any
import uuid
import os
from datetime import datetime
import hashlib
import asyncio
from fastapi.middleware.cors import CORSMiddleware
import shutil
from celery import Celery
from pathlib import Path
import kubernetes
from kubernetes import client, config
import json
from .config import (
    RABBITMQ_HOST,
    RABBITMQ_PORT,
    RABBITMQ_USER,
    RABBITMQ_PASSWORD,
    NFS_MOUNT_POINT,
    S3_BUCKET
)

app = FastAPI()
router = APIRouter(prefix="/api")
#app.mount("/static", StaticFiles(directory="static"), name="static")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600,
)

# Configure Celery with RabbitMQ credentials
celery_app = Celery(
    'tasks',
    broker=f'amqp://{RABBITMQ_USER}:{RABBITMQ_PASSWORD}@{RABBITMQ_HOST}:{RABBITMQ_PORT}//',
    backend='rpc://'
)

# Configure upload directory
UPLOAD_DIR = os.path.join(NFS_MOUNT_POINT, "uploads")

# Ensure upload directory exists
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Store for processed slides from Windows component
windows_processed_jobs: Dict[str, Dict[str, Any]] = {}

def handle_windows_response(ch, method, properties, body):
    """
    Handle response from Windows component
    """
    try:
        data = json.loads(body)
        job_id = data.get("job_id")
        if job_id:
            windows_processed_jobs[job_id] = {
                "slides": data.get("slides", []),
                "videos": data.get("videos", []),
                "ready": True
            }
            print(f"Received processed data for job {job_id}")
    except Exception as e:
        print(f"Error processing Windows component response: {str(e)}")

def get_rabbitmq_credentials():
    """
    Get RabbitMQ credentials either from Kubernetes secrets or environment variables
    """
    try:
        # Try to load Kubernetes config
        try:
            config.load_incluster_config()
            # If we're in Kubernetes, get credentials from secret
            v1 = client.CoreV1Api()
            secret = v1.read_namespaced_secret("my-rabbit-default-user", "event-poc")
            return {
                "username": secret.data["username"].decode(),
                "password": secret.data["password"].decode()
            }
        except (config.ConfigException, kubernetes.client.exceptions.ApiException):
            # If we're not in Kubernetes or secret doesn't exist, use environment variables
            return {
                "username": RABBITMQ_USER,
                "password": RABBITMQ_PASSWORD
            }
    except Exception as e:
        print(f"Error getting RabbitMQ credentials: {str(e)}")
        # Fallback to environment variables
        return {
            "username": RABBITMQ_USER,
            "password": RABBITMQ_PASSWORD
        }

@celery_app.task
def process_uploaded_files(job_data):
    """
    Celery task to process uploaded files and send message to next microservice
    """
    try:
        # Publish message to RabbitMQ for next microservice
        publish_message(job_data, queue="file_processing")
    except Exception as e:
        print(f"Error processing files: {str(e)}")
        raise

@app.on_event("startup")
async def startup_event():
    # Start RabbitMQ listener for Windows component responses
    asyncio.create_task(rabbitmq_listener(queue="windows_response", callback=handle_windows_response))

@router.get("/debug-ready")
async def debug_ready():
    return state.ready_downloads

@router.get("/check-download/{file_id}")
async def check_download(file_id: str):
    print(f"check-download called for file_id: {file_id}")
    if file_id in state.ready_downloads:
        return JSONResponse(content={"ready": True, "download_url": f"/download/{file_id}"})
    else:
        return JSONResponse(content={"ready": False})

@router.get("/check-windows-processing/{job_id}")
async def check_windows_processing(job_id: str):
    """
    Check if Windows component has finished processing the job
    """
    print(f"check-windows-processing called for job_id: {job_id}")
    if job_id in windows_processed_jobs:
        return JSONResponse(content={
            "ready": True,
            "slides": windows_processed_jobs[job_id].get("slides", []),
            "videos": windows_processed_jobs[job_id].get("videos", [])
        })
    else:
        return JSONResponse(content={"ready": False})

@router.get("/download/{file_id}")
async def download_file(file_id: str):
    file_path = state.ready_downloads.get(file_id)
    if not file_path:
        return {"error": "File not ready yet"}
    return FileResponse(file_path, filename=os.path.basename(file_path))

@router.post("/upload")
async def upload_files(
    ppt: UploadFile = File(...),
    videos: List[UploadFile] = File([]),
    voice: str = Form(...)
):
    try:
        print(f"Received upload request - PPT: {ppt.filename}, Voice: {voice}, Videos: {[v.filename for v in videos if v]}")
        
        # Generate unique job ID
        job_id = str(uuid.uuid4())
        
        # Create job directory
        job_dir = os.path.join(UPLOAD_DIR, job_id)
        os.makedirs(job_dir, exist_ok=True)
        print(f"Created job directory: {job_dir}")
        
        # Save PowerPoint file
        ppt_path = os.path.join(job_dir, ppt.filename)
        with open(ppt_path, "wb") as buffer:
            shutil.copyfileobj(ppt.file, buffer)
        print(f"Saved PowerPoint file to: {ppt_path}")
        
        # Save video files
        video_paths = []
        for video in videos:
            if video:
                video_path = os.path.join(job_dir, video.filename)
                with open(video_path, "wb") as buffer:
                    shutil.copyfileobj(video.file, buffer)
                video_paths.append({
                    "filename": video.filename,
                    "nfs_path": video_path
                })
                print(f"Saved video file to: {video_path}")
        
        # Prepare response data
        response_data = {
            "job_id": job_id,
            "pptx_file_id": ppt.filename,
            "pptx_nfs_path": ppt_path,
            "tts_voice": voice,
            "videos": video_paths,
            "slides": []  # Added empty slides array to prevent frontend TypeError
        }
        
        print(f"Publishing message to RabbitMQ: {response_data}")
        # Trigger Celery task
        process_uploaded_files.delay(response_data)
        
        return response_data
    except Exception as e:
        print(f"Error in upload_files: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/job/submit")
async def submit_job(job_data: dict):
    """
    Endpoint to handle job submission and trigger processing
    """
    try:
        # Trigger Celery task for processing
        process_uploaded_files.delay(job_data)
        return {"status": "success", "message": "Job submitted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/health")
async def health_check():
    """
    Health check endpoint
    """
    return {"status": "healthy"}

@router.post("/s3-presign")
async def s3_presign(filename: str, content_type: str):
    """
    Generate a pre-signed S3 upload URL for the given filename and content type.
    """
    key = f"uploads/{uuid.uuid4()}_{filename}"
    url = generate_presigned_url(key, content_type)
    if not url:
        raise HTTPException(status_code=500, detail="Failed to generate presigned URL")
    return {"url": url, "key": key, "bucket": S3_BUCKET}

@router.post("/notify-upload")
async def notify_upload(payload: dict):
    """
    Notify backend that upload to S3 is complete. Payload should include job_id, s3_key, filename, tts_voice, and any other metadata.
    Sends a RabbitMQ message to the Windows component with the S3 key and metadata.
    """
    try:
        job_id = payload.get("job_id") or str(uuid.uuid4())
        s3_key = payload["s3_key"]
        filename = payload["filename"]
        tts_voice = payload.get("tts_voice", "")
        videos = payload.get("videos", [])
        # Prepare message for Windows component
        message = {
            "job_id": job_id,
            "pptx_file_id": filename,
            "pptx_s3_key": s3_key,
            "tts_voice": tts_voice,
            "videos": videos,
            "slides": []
        }
        publish_message(message, queue="file_processing")
        return {"status": "success", "job_id": job_id}
    except Exception as e:
        print(f"Error in notify_upload: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Include the router in the app
app.include_router(router)

@app.get("/")
def get_form():
    return FileResponse("static/index.html")
