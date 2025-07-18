import os, json, boto3
from fastapi import UploadFile
from botocore.exceptions import ClientError

PPT_PATH = "/artifacts/powerpoints/"
MD_PATH = "/artifacts/metadata/"
BUMPER_PATH = "/artifacts/bumpers/"
S3_BUCKET = os.getenv("S3_BUCKET", "event-driven-poc-ftnt")
S3_REGION = os.getenv("S3_REGION", "us-east-1")

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

def upload_to_s3(file: UploadFile, file_name: str, job_id: str):
    s3 = boto3.client("s3", region_name=S3_REGION)
    # Run upload
    full_path_ppt = os.path.join(PPT_PATH, f"{file_name}")
    s3_key = job_id+"/"+file_name 
    try:
        s3.upload_file(full_path_ppt, S3_BUCKET, s3_key)
        print(f"[INFO] Uploaded {full_path_ppt} to s3://{S3_BUCKET}/{s3_key}")
    except ClientError as e:
        print(f"S3 upload failed: {e}")
        raise
    # Confirm successful upload
    try:
        response = s3.head_object(Bucket=S3_BUCKET, Key=s3_key)
        print("S3 upload confirmed. Metadata: ")
        print(response) 
    except ClientError as e:
        print("S3 upload confirmation failed: {e}")
        raise
