import os
from fastapi import UploadFile

EFS_PATH = "/mnt/efs/uploads"

def save_to_efs(file: UploadFile, file_id: str) -> str:
    os.makedirs(EFS_PATH, exist_ok=True)
    full_path = os.path.join(EFS_PATH, f"{file_id}.pptx")
    
    with open(full_path, "wb") as f:
        f.write(file.file.read())
    
    return full_path
