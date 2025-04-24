import os
import subprocess
import shutil
from celery import Celery
from pathlib import Path

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
def produce_video(job_id):

    print(f"Received task for job id: {job_id}")
    image_dir = Path(f"/artifacts/slides/{job_id}")
    audio_dir = Path(f"/artifacts/tts_output/{job_id}")
    output_dir = OUTPUT_BASE / job_id
    output_dir.mkdir(parents=True, exist_ok=True)

    output_final_dir = output_dir / "outputs"
    output_final_dir.mkdir(parents=True, exist_ok=True)

    bumper_path_in = Path(f"assets/bumpers/{job_id}-bumper1.mp4").resolve()
    bumper_path_out = Path(f"assets/bumpers/{job_id}-bumper2.mp4").resolve()
    final_output = output_final_dir / f"{job_id}.mp4"

    def get_audio_duration(audio_path):
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', str(audio_path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        try:
            return float(result.stdout.strip())
        except ValueError:
            raise RuntimeError(f"Failed to get duration for: {audio_path}")

    images = sorted(image_dir.glob("*.png")) + sorted(image_dir.glob("*.jpg")) + sorted(image_dir.glob("*.jpeg"))
    audios = sorted(audio_dir.glob("*.mp3")) + sorted(audio_dir.glob("*.wav"))

    if not images or not audios:
        raise RuntimeError("❌ No matching images or audios found")

    for idx, (image, audio) in enumerate(zip(images, audios), 1):
        print(f"Processing image: {image}, Audio: {audio}")
        stereo_path = output_dir / f"stereo_{idx:03d}.mp3"
        output_video = output_dir / f"output_{idx:03d}.mp4"

        subprocess.run([
            'ffmpeg', '-y', '-i', str(audio),
            '-ac', '2', '-ar', '48000', '-b:a', '192k',
            str(stereo_path)
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        duration = get_audio_duration(stereo_path)

        subprocess.run([
            'ffmpeg', '-y', '-loop', '1', '-i', str(image),
            '-i', str(stereo_path),
            '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2',
            '-c:v', 'libx264', '-tune', 'stillimage', '-shortest',
            '-c:a', 'aac', '-b:a', '192k',
            '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
            '-t', str(duration), str(output_video)
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    filelist_path = output_dir / 'filelist.txt'
    with filelist_path.open('w') as f:
        if bumper_path_in.exists():
            f.write(f"file '{bumper_path_in}'\n")
        for idx in range(1, len(images) + 1):
            video_path = output_dir / f"output_{idx:03d}.mp4"
            if video_path.exists():
                f.write(f"file '{video_path.resolve()}'\n")
        if bumper_path_out.exists():
            f.write(f"file '{bumper_path_out}'\n")

    subprocess.run([
        'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(filelist_path),
        '-c', 'copy', str(final_output)
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if final_output.exists():
        print(f"Final output video written to: {final_output}")
        shutil.rmtree(output_dir, ignore_errors=True)
        return str(final_output)
    else:
        raise RuntimeError("❌ Final video creation failed.")
