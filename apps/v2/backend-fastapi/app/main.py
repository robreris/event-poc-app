from fastapi import FastAPI, UploadFile, File, Form, Request, APIRouter, HTTPException
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
    NFS_MOUNT_POINT
)

app = FastAPI()
router = APIRouter()
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
    # asyncio.create_task(rabbitmq_listener())
    pass

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

@app.post("/job/submit")
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

@app.get("/health")
async def health_check():
    """
    Health check endpoint
    """
    return {"status": "healthy"}

@app.get("/")
def get_form():
    return FileResponse("static/index.html")
