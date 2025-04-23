import os
import subprocess
import shutil
from celery import Celery
from pathlib import Path
import os

# Environment-based configuration
RABBITMQ_HOST = os.environ.get("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_USER = os.environ.get("RABBIT_USERNAME", "guest")
RABBITMQ_PASS = os.environ.get("RABBIT_PASSWORD", "guest")
RABBITMQ_PORT = os.environ.get("RABBITMQ_PORT", "5672")
RABBITMQ_VHOST = os.environ.get("RABBITMQ_VHOST", "/")

# Full AMQP broker URL
CELERY_BROKER_URL = (
    f"amqp://{RABBITMQ_USER}:{RABBITMQ_PASS}@{RABBITMQ_HOST}:{RABBITMQ_PORT}{RABBITMQ_VHOST}"
)

celery_app = Celery(
    'video_producer',
     broker=CELERY_BROKER_URL
)

OUTPUT_DIR = Path(os.getenv("VIDEO_OUT_DIR", "/artifacts/video-output/"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

@celery_app.task(queue='video_producer', name="ffmpeg_service.produce_video")
def produce_video(job_id):
    image_dir = "artifacts/slides/" + job_id
    audio_dir = "artifacs/tts_output/" + job_id

    output_dir = OUTPUT_DIR / job_id
    output_dir.mkdir(parents=True, exist_ok=True)

    output_final_dir = output_dir / "outputs"
    output_final_dir.mkdir(parents=True, exist_ok=True)    

    bumper_path_in = os.path.abspath("assets/bumpers/bumper_in.mp4")
    bumper_path_out = os.path.abspath("assets/bumpers/bumper_out.mp4")
    final_output = Path(output_final_dir + f"{output_name}.mp4")

    def get_audio_duration(audio_path):
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', audio_path],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        return float(result.stdout)

    images = sorted([f for f in os.listdir(image_dir) if f.endswith(('.png', '.jpg', '.jpeg'))])
    audios = sorted([f for f in os.listdir(audio_dir) if f.endswith(('.mp3', '.wav'))])

    for idx, (image, audio) in enumerate(zip(images, audios)):
        image_path = os.path.join(image_dir, image)
        audio_path = os.path.join(audio_dir, audio)
        stereo_path = os.path.join(output_dir, f"stereo_{idx+1:03d}.mp3")
        output_video = os.path.join(output_dir, f"output_{idx+1:03d}.mp4")

        # Convert to stereo MP3
        subprocess.run([
            'ffmpeg', '-y', '-i', audio_path,
            '-ac', '2', '-ar', '48000', '-b:a', '192k',
            stereo_path
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # Use stereo audio for duration and muxing
        audio_duration = get_audio_duration(stereo_path)

        ffmpeg_command = [
            'ffmpeg', '-y', '-i', image_path,
            '-i', stereo_path,
            '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2',
            '-c:v', 'libx264', '-tune', 'stillimage',
            '-c:a', 'aac', '-b:a', '192k',
            '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
            '-t', str(audio_duration),
            output_video
        ]
        subprocess.run(ffmpeg_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    filelist_path = os.path.join(output_dir, 'filelist.txt')
    with open(filelist_path, 'w') as f:
        if os.path.exists(bumper_path_in):
            f.write(f"file '{bumper_path_in}'\n")
        for idx in range(len(images)):
            part = os.path.abspath(os.path.join(output_dir, f"output_{idx+1:03d}.mp4"))
            if os.path.exists(part):
                f.write(f"file '{part}'\n")
        if os.path.exists(bumper_path_out):
            f.write(f"file '{bumper_path_out}'\n")

    concat_command = [
        'ffmpeg', '-loglevel', 'verbose', '-y', '-f', 'concat', '-safe', '0',
        '-i', filelist_path, '-c', 'copy', final_output
    ]
    subprocess.run(concat_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if os.path.exists(final_output):
        shutil.rmtree(output_dir, ignore_errors=True)
        return final_output
    else:
        raise RuntimeError("❌ Failed to create final video.")
