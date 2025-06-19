import os, json
import boto3
from botocore.exceptions import ClientError
from typing import Any
from .config import S3_BUCKET, S3_REGION

PPT_PATH = "/artifacts/powerpoints/"
MD_PATH = "/artifacts/metadata/"
BUMPER_PATH = "/artifacts/bumpers/"

def get_s3_client():
    return boto3.client(
        "s3",
        region_name=S3_REGION
    )

def generate_presigned_url(key, content_type, expiration=3600):
    s3 = get_s3_client()
    try:
        url = s3.generate_presigned_url(
            "put_object",
            Params={"Bucket": S3_BUCKET, "Key": key, "ContentType": content_type},
            ExpiresIn=expiration,
        )
        return url
    except ClientError as e:
        print(f"Error generating presigned URL: {e}")
        return None

def save_bumper_to_efs(file, target_filename: str) -> str:
    os.makedirs(BUMPER_PATH, exist_ok=True)
    full_path = os.path.join(BUMPER_PATH, target_filename)

    with open(full_path, "wb") as f:
        f.write(file.file.read())
    print(f"Bumper saved to {full_path}")
    return full_path

def save_to_efs(file, file_name: str, mdata: 'dict[str, Any]') -> str:
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
