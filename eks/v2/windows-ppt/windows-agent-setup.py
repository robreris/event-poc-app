import os
import json
import time
import pika
import win32com.client
from pathlib import Path

NFS_MOUNT = "Z:\\"
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
QUEUE_NAME = "render_jobs"

def render_pptx(ppt_path: str, output_path: str):
    print(f"[INFO] Starting rendering: {ppt_path}")
    ppt_app = win32com.client.Dispatch("PowerPoint.Application")
    ppt_app.Visible = True
    presentation = ppt_app.Presentations.Open(ppt_path, WithWindow=False)

    try:
        # Check if animations exist
        animated = any(slide.TimeLine.MainSequence.Count > 0 for slide in presentation.Slides)
        if animated:
            presentation.CreateVideo(output_path, -1, 60)
            while presentation.CreateVideoStatus != 3:  # ppMediaTaskStatusDone
                print("[INFO] Waiting for CreateVideo...")
                time.sleep(2)
        else:
            slide = presentation.Slides(1)
            slide.Export(output_path.replace(".mp4", ".png"), "PNG")
            print("[INFO] No animation found, exported as PNG.")
    finally:
        presentation.Close()
        ppt_app.Quit()

def callback(ch, method, properties, body):
    try:
        job = json.loads(body)
        pptx_file = os.path.join(NFS_MOUNT, job["input"])
        output_file = os.path.join(NFS_MOUNT, job["output"])
        render_pptx(pptx_file, output_file)
        status = {"status": "completed", "output": job["output"]}
        ch.basic_publish(exchange='', routing_key="render_status", body=json.dumps(status))
    except Exception as e:
        print(f"[ERROR] {e}")
        ch.basic_publish(exchange='', routing_key="render_status", body=json.dumps({"status": "failed", "error": str(e)}))

    ch.basic_ack(delivery_tag=method.delivery_tag)

def main():
    connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
    channel = connection.channel()
    channel.queue_declare(queue=QUEUE_NAME)
    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=QUEUE_NAME, on_message_callback=callback)
    print("[INFO] Awaiting render jobs...")
    channel.start_consuming()

if __name__ == "__main__":
    main()
