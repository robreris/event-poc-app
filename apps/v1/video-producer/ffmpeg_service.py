import os
import subprocess
import shutil
from celery import Celery
from pathlib import Path
import asyncio, aio_pika, traceback, json

# Environment-based configuration
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_USER = os.getenv("RABBIT_USERNAME", "guest")
RABBITMQ_PASS = os.getenv("RABBIT_PASSWORD", "guest")
RABBITMQ_PORT = os.getenv("RABBITMQ_PORT", "5672")
RABBITMQ_VHOST = os.getenv("RABBITMQ_VHOST", "/")

CELERY_BROKER_URL = f"amqp://{RABBITMQ_USER}:{RABBITMQ_PASS}@{RABBITMQ_HOST}:{RABBITMQ_PORT}{RABBITMQ_VHOST}"
celery_app = Celery('video_producer', broker=CELERY_BROKER_URL)

OUTPUT_BASE = Path(os.getenv("VIDEO_OUT_DIR", "/artifacts/video-output/"))
OUTPUT_BASE.mkdir(parents=True, exist_ok=True)

@celery_app.task(queue='video_producer', name="ffmpeg_service.produce_video")
def produce_video(job_id, file_id):
    print(f"Received task for job id: {job_id}")
    image_dir = Path(f"/artifacts/slides/{job_id}")
    audio_dir = Path(f"/artifacts/tts_output/{job_id}")
    output_dir = OUTPUT_BASE / job_id
    output_dir.mkdir(parents=True, exist_ok=True)

    temp_dir = output_dir / "temp"
    temp_adj_dir = output_dir / "temp_adj"
    final_output_dir = output_dir / "outputs"
    final_output_dir.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_adj_dir.mkdir(parents=True, exist_ok=True)

    bumper_path_in = Path(f"/artifacts/bumpers/{job_id}-bumper1.mp4").resolve()
    bumper_path_out = Path(f"/artifacts/bumpers/{job_id}-bumper2.mp4").resolve()
    final_output = final_output_dir / f"{job_id}.mp4"

    def get_audio_duration(audio_path):
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', str(audio_path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        return float(result.stdout.strip())

    def reencode_clip(input_path, output_path):
        subprocess.run([
            'ffmpeg', '-y', '-i', str(input_path),
            '-c:v', 'libx264', '-preset', 'fast',
            '-pix_fmt', 'yuv420p', '-c:a', 'aac',
            '-ar', '48000', '-ac', '2', '-b:a', '192k',
            str(output_path)
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def is_cbr(audio_file):
        ffprobe_command = [
            'ffprobe', '-v', 'error', '-select_streams', 'a:0',
            '-show_entries', 'format=bit_rate',
            '-of', 'default=noprint_wrappers=1:nokey=1', str(audio_file)
        ]
        result = subprocess.run(ffprobe_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        bitrate_info = result.stdout.decode('utf-8').strip()
    
        if bitrate_info:
            print(f"🔍 {audio_file.name} is CBR with bitrate {bitrate_info}")
            return True
        else:
            print(f"⚠️ {audio_file.name} may be VBR or bitrate info unavailable.")
            return False

    def convert_to_cbr(input_audio, output_audio):
        if is_cbr(input_audio):
            print(f"✅ Skipping conversion for {input_audio.name}, already CBR.")
            shutil.copy(input_audio, output_audio)
        else:
            print(f"🔄 Converting {input_audio.name} to CBR → {output_audio.name}")
            subprocess.run([
                'ffmpeg', '-y', '-i', str(input_audio),
                '-ar', '48000',
                '-ac', '2',
                '-b:a', '192k',
                '-c:a', 'aac',
                '-fflags', '+bitexact',
                '-avoid_negative_ts', 'make_zero',
                str(output_audio)
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    image_files = {img.stem: img for img in image_dir.glob("*") if img.suffix.lower() in [".png", ".jpg", ".jpeg"]}
    audio_files = {aud.stem: aud for aud in audio_dir.glob("*") if aud.suffix.lower() in [".mp3", ".mp4", ".wav"]}
    common_keys = sorted(set(image_files.keys()) & set(audio_files.keys()))

    if not common_keys:
        raise RuntimeError("❌ No matching images or audios found")

    for idx, key in enumerate(common_keys, 1):
        image = image_files[key]
        audio = audio_files[key]
        print(f"Processing image file: {image}")
        print(f"Processing audio file: {audio}")

        #Output file paths
        cbr_audio = output_dir / f"audio_cbr_{idx:03d}.mp3"
        video_path = temp_dir / f"output_{idx:03d}.mp4"

        #Convert to CBR
        convert_to_cbr(audio, cbr_audio)

        print(f"Getting audio duration...")
        duration = get_audio_duration(cbr_audio)

        print(f"Running subprocess...")
        subprocess.run([
            'ffmpeg', '-y', '-loop', '1', '-i', str(image),
            '-i', str(cbr_audio),
            '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2',
            '-c:v', 'libx264', '-tune', 'stillimage', '-shortest',
            '-c:a', 'aac', '-b:a', '192k',
            '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
            '-t', str(duration), str(video_path)
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # Re-encode
        print(f"Re-encoding...")
        reencode_clip(video_path, temp_adj_dir / video_path.name)

    # File list for ffmpeg concat
    print(f"Writing filelist.txt...")
    filelist_path = temp_adj_dir / 'filelist.txt'
    with filelist_path.open('w') as f:
        if bumper_path_in.exists():
            f.write(f"file '{bumper_path_in}'\n")
        for idx in range(1, len(image_files) + 1):
            adj_path = temp_adj_dir / f"output_{idx:03d}.mp4"
            if adj_path.exists():
                f.write(f"file '{adj_path}'\n")
        if bumper_path_out.exists():
            f.write(f"file '{bumper_path_out}'\n")

    print(f"Starting concatenation...")
    subprocess.run([
        'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(filelist_path),
        '-c:v', 'libx264', '-preset', 'fast',
        '-c:a', 'aac', '-b:a', '192k', str(final_output)
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)


    async def send_download_ready_message(file_path, job_id, file_id):
        try:
            connection = await aio_pika.connect_robust(CELERY_BROKER_URL)
            channel = await connection.channel()
            await channel.declare_queue("download_ready", durable=True)
            message = {
                "event": "artifact-ready",
                "file_path": str(file_path),
                "job_id": job_id,
                "file_id": file_id
            }
            await channel.default_exchange.publish(
                aio_pika.Message(
                    body=json.dumps(message).encode(),
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT
                ),
                routing_key="download_ready"
            )
            await connection.close()
            print(f"Sent 'artifact-ready' message to 'download_ready' queue: {message}")
        except Exception as e:
            print("Failed to send artifact-ready message")
            traceback.print_exc()

    if final_output.exists():
        print(f"✅ Final output video written to: {final_output}")
        shutil.rmtree(temp_dir, ignore_errors=True)
        shutil.rmtree(temp_adj_dir, ignore_errors=True)

        print(f"Calling send_download_ready_message with file_id: {file_id}") 
        asyncio.run(send_download_ready_message(
            file_path=final_output,
            job_id=job_id,
            file_id=file_id
        ))
        print("Message send attempted.")
        
        return str(final_output)
    else:
        raise RuntimeError("❌ Final video creation failed.")

