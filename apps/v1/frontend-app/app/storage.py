import os, json
from fastapi import UploadFile

PPT_PATH = "/artifacts/powerpoints/"
MD_PATH = "/artifacts/metadata/"
BUMPER_PATH = "/artifacts/bumpers/"

def save_bumper_to_efs(file: UploadFile, target_filename: str) -> str:
    os.makedirs(BUMPER_PATH, exist_ok=True)
    full_path = os.path.join(BUMPER_PATH, target_filename)

    with open(full_path, "wb") as f:
        f.write(file.file.read())
    print(f"Bumper saved to {full_path}")
    return full_path

def save_to_efs(file: UploadFile, file_name: str, mdata: dict[str, any]) -> str:
    os.makedirs(PPT_PATH, exist_ok=True)
    os.makedirs(MD_PATH, exist_ok=True)
    full_path_ppt = os.path.join(PPT_PATH, f"{file_name}")
    full_path_mdata = os.path.join(MD_PATH, f"{mdata['job_id']}-metadata.txt")

    with open(full_path_ppt, "wb") as f:
        f.write(file.file.read())

    with open(full_path_mdata, "w") as g:
        json.dump(mdata, g, indent=2)

    print(f"Powerpoint saved to {full_path_ppt}")  
    print(f"Job metadata saved to {full_path_mdata}")  
    return full_path_ppt
