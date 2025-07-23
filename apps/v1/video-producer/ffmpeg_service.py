import os, re
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
RES_HEIGHT = os.getenv("RES_HEIGHT", "360")
RES_WIDTH = os.getenv("RES_WIDTH", "640")
FPS = os.getenv("FPS", "30")

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
    temp_adj_final_dir = output_dir / "temp_adj_final"
    final_output_dir = output_dir / "outputs"
    final_output_dir.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_adj_dir.mkdir(parents=True, exist_ok=True)
    temp_adj_final_dir.mkdir(parents=True, exist_ok=True)

    bumper_path_in = Path(f"/artifacts/bumpers/{job_id}-bumper1.mp4").resolve()
    bumper_path_out = Path(f"/artifacts/bumpers/{job_id}-bumper2.mp4").resolve()
    bumper_path_in_processed = Path(f"/artifacts/bumpers/{job_id}-bumper1-proc.mp4").resolve()
    bumper_path_out_processed = Path(f"/artifacts/bumpers/{job_id}-bumper2-proc.mp4").resolve()
    final_output = final_output_dir / f"{job_id}.mp4"

    def get_slide_number(filename):
        """Extracts slide number from filename, e.g. slide_01, slide_02_animation"""
        m = re.search(r"slide_(\d+)", filename)
        return int(m.group(1)) if m else 9999  # fallback at end

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

    def reencode_bumper(input_path, output_path, width, height, fps):
        vf_filter = (
            f"scale='if(gt(a,{width}/{height}),{width},-1)':'if(gt(a,{width}/{height}),-1,{height})',"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1:1,format=yuv420p"
        )
        result = subprocess.run([
            'ffmpeg', '-y', '-i', str(input_path),
            '-vf', vf_filter,
            '-r', str(fps),
            '-c:v', 'libx264', '-preset', 'fast',
            '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2',
            str(output_path)
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode != 0:
            print(f"FFmpeg bumper re-encode failed for {input_path}!")
            print(result.stderr.decode())
    
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

    def trim_audio(input_audio, output_audio, duration):
        subprocess.run([
            'ffmpeg', '-y', '-i', str(input_audio),
            '-t', f"{duration:.3f}", str(output_audio)
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def check_segment_properties(segment_path):
        cmd = [
            "ffprobe",
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,r_frame_rate,pix_fmt",
            "-of", "compact=p=0:nk=1",
            str(segment_path)
        ]
        v_info = subprocess.check_output(cmd).decode().strip()
        cmd = [
            "ffprobe",
            "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=sample_rate,channels,sample_fmt",
            "-of", "compact=p=0:nk=1",
            str(segment_path)
        ]
        a_info = subprocess.check_output(cmd).decode().strip()
        print(f"{segment_path}:\n  Video: {v_info}\n  Audio: {a_info}")
    
    def check_segment_integrity(segment_path):
        info = subprocess.check_output([
            'ffprobe', '-v', 'error',
            '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1',
            str(segment_path)
        ]).decode().strip()
        print(f"{segment_path} duration: {info}")

        streams = subprocess.check_output([
            'ffprobe', '-v', 'error',
            '-show_entries', 'stream=index,codec_type', '-of', 'csv=p=0',
            str(segment_path)
        ]).decode().strip()
        print(f"{segment_path} streams:\n{streams}") 

    def concat_with_filter_complex(segment_paths, output_path):
        filter_complex = ''.join([f'[{i}:v][{i}:a]' for i in range(len(segment_paths))])
        filter_complex += f'concat=n={len(segment_paths)}:v=1:a=1[v][a]'
        cmd = ['ffmpeg', '-y']
        for seg in segment_paths:
            check_segment_properties(seg)
            check_segment_integrity(seg)
        for seg in segment_paths:
            cmd += ['-i', str(seg)]
        cmd += [
            '-filter_complex', filter_complex,
            '-map', '[v]', '-map', '[a]',
            '-c:v', 'libx264', '-preset', 'fast',
            '-c:a', 'aac', '-b:a', '192k',
            '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
            '-progress', 'pipe:1', '-nostats',
            str(output_path)
        ]
        print(f"Running ffmpeg concat with filter_complex...")
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for line in proc.stdout:
            print(line.strip())
        proc.wait()
        if proc.returncode != 0:
            print(f"ffmpeg exited with code {proc.returncode}")

    def ensure_audio(segment_path, output_path):
        # Check if audio stream exists
        info = subprocess.check_output([
            'ffprobe', '-v', 'error', '-select_streams', 'a:0',
            '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', str(segment_path)
        ]).decode().strip()
        if info:
            # Has audio
            shutil.copy(segment_path, output_path)
            return
        # No audio: add silent audio track of same duration
        duration = float(subprocess.check_output([
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1', str(segment_path)
        ]).decode().strip())
        subprocess.run([
            'ffmpeg', '-y', '-i', str(segment_path),
            '-f', 'lavfi', '-t', f"{duration}", '-i', 'anullsrc=channel_layout=stereo:sample_rate=48000',
            '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-shortest',
            str(output_path)
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def reencode_for_concat(input_path, output_path, width, height, fps):
        vf_filter = (
            f"scale='if(gt(a,{width}/{height}),{width},-1)':'if(gt(a,{width}/{height}),-1,{height})',"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1:1,format=yuv420p"
        )
        subprocess.run([
            'ffmpeg', '-y', '-i', str(input_path),
            '-vf', vf_filter,
            '-r', str(fps),
            '-c:v', 'libx264', '-preset', 'fast',
            '-c:a', 'aac', '-ar', '48000', '-ac', '2', '-b:a', '192k',
            str(output_path)
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
 
    #image_files = {img.stem: img for img in image_dir.glob("*") if img.suffix.lower() in [".png", ".jpg", ".jpeg"]}
    slide_files = [f for f in image_dir.iterdir() if f.suffix.lower() in [".png", ".mp4"]]
    slide_files_sorted = sorted(slide_files, key=lambda f: get_slide_number(f.name))

    audio_files = {aud.stem: aud for aud in audio_dir.glob("*") if aud.suffix.lower() in [".mp3", ".mp4", ".wav"]}

    segments = []
    for idx, slide_file in enumerate(slide_files_sorted, 1):
        basename = slide_file.stem
        # Try to find a matching audio file (by slide number)
        matching_audio = None
        for key in audio_files:
            if get_slide_number(key) == get_slide_number(basename):
                matching_audio = audio_files[key]
                break
    
        video_segment_path = temp_dir / f"output_{idx:03d}.mp4"
    
        if slide_file.suffix.lower() == ".png":
            # --- Process static image as before ---
            if not matching_audio:
                print(f"⚠️ No audio found for {slide_file.name}, skipping.")
                continue
            print(f"Combining image: {slide_file.name} with audio: {matching_audio.name}")
            cbr_audio = output_dir / f"audio_cbr_{idx:03d}.mp3"
            convert_to_cbr(matching_audio, cbr_audio)
            duration = get_audio_duration(cbr_audio)
            trimmed_audio = output_dir / f"audio_trimmed_{idx:03d}.mp3"
            trim_audio(cbr_audio, trimmed_audio, duration)
    
            vf_filter = (
                f"scale='if(gt(a,{RES_WIDTH}/{RES_HEIGHT}),{RES_WIDTH},-1)':'if(gt(a,{RES_WIDTH}/{RES_HEIGHT}),-1,{RES_HEIGHT})',"
                f"pad={RES_WIDTH}:{RES_HEIGHT}:(ow-iw)/2:(oh-ih)/2,setsar=1:1,format=yuv420p"
            )
            subprocess.run([
                'ffmpeg', '-y', '-loop', '1', '-i', str(slide_file),
                '-i', str(trimmed_audio),
                '-vf', vf_filter,
                '-r', str(FPS),
                '-c:v', 'libx264', '-preset', 'fast', '-tune', 'stillimage', '-shortest',
                '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2',
                '-t', f"{duration:.3f}", str(video_segment_path)
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        elif slide_file.suffix.lower() == ".mp4":
            # --- Process animation segment ---
            print(f"Handling animation video: {slide_file.name}")
            # If you want to use the TTS audio instead of animation audio:
            if matching_audio:
                cbr_audio = output_dir / f"audio_cbr_{idx:03d}.mp3"
                convert_to_cbr(matching_audio, cbr_audio)
                duration = get_audio_duration(cbr_audio)
                trimmed_audio = output_dir / f"audio_trimmed_{idx:03d}.mp3"
                trim_audio(cbr_audio, trimmed_audio, duration)
                # Replace original audio with TTS
                subprocess.run([
                    'ffmpeg', '-y', '-i', str(slide_file),
                    '-i', str(trimmed_audio),
                    '-map', '0:v:0', '-map', '1:a:0',
                    '-c:v', 'libx264', '-preset', 'fast',
                    '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2',
                    '-shortest', str(video_segment_path)
                ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            else:
                print(f"No matching TTS audio found for {slide_file.name}, using original audio.")
                reencode_clip(slide_file, video_segment_path)
        else:
            print(f"Unknown file type: {slide_file.name}")
            continue
        
        # If audio is missing, add it
        audio_safe_path = temp_adj_dir / video_segment_path.name
        ensure_audio(video_segment_path, audio_safe_path)
 
        # Always re-encode for concat compatibility
        final_segment_path = temp_adj_dir / f"{video_segment_path.stem}_final.mp4"
        reencode_clip(audio_safe_path, final_segment_path)
        segments.append(final_segment_path)
    
    print(f"Starting concatenation...")

    # First reencode bumpers
    reencode_bumper(bumper_path_in, bumper_path_in_processed, RES_WIDTH, RES_HEIGHT, FPS)
    reencode_bumper(bumper_path_out, bumper_path_out_processed, RES_WIDTH, RES_HEIGHT, FPS)

    # Gather list of segments to concatenate, in the right order
    segments_final = []
    if bumper_path_in.exists():
        segments_final.append(str(bumper_path_in_processed))
    segments_final.extend([str(seg) for seg in segments])
    if bumper_path_out.exists():
        segments_final.append(str(bumper_path_out_processed))

    concat_seg = []
    for seg in segments:
        final_seg_path = temp_adj_final_dir / f"{seg.stem}_postproc.mp4"
        reencode_for_concat(seg, final_seg_path, RES_WIDTH, RES_HEIGHT, FPS)
        concat_seg.append(final_seg_path)

    concat_with_filter_complex(concat_seg, final_output)

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

