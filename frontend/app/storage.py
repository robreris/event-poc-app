import os, json
from fastapi import UploadFile

PPT_PATH = "/artifacts/powerpoints/"
MD_PATH = "/artifacts/metadata/"

def save_to_efs(file: UploadFile, file_id: str, mdata: dict[str, any]) -> str:
    os.makedirs(PPT_PATH, exist_ok=True)
    os.makedirs(MD_PATH, exist_ok=True)
    full_path_ppt = os.path.join(PPT_PATH, f"{file_id}.pptx")
    full_path_mdata = os.path.join(MD_PATH, f"{mdata['job_id']}-metadata.txt")

    with open(full_path_ppt, "wb") as f:
        f.write(file.file.read())

    with open(full_path_mdata, "w") as g:
        json.dump(mdata, g, indent=2)

    print(f"Powerpoint saved to {full_path_ppt}")  
    print(f"Job metadata saved to {full_path_mdata}")  
    return full_path_ppt
