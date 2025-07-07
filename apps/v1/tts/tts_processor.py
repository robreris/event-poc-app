import os
from pathlib import Path
from celery import Celery

# Import Azure if available
try:
    import azure.cognitiveservices.speech as speechsdk
except ImportError:
    speechsdk = None

# Try importing Piper (if you want to use the Python bindings, though subprocess is more common)
try:
    import piper
except ImportError:
    piper = None

import subprocess

# Environment-based configuration
RABBITMQ_HOST = os.environ.get("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_USER = os.environ.get("RABBIT_USERNAME", "guest")
RABBITMQ_PASS = os.environ.get("RABBIT_PASSWORD", "guest")
RABBITMQ_PORT = os.environ.get("RABBITMQ_PORT", "5672")
RABBITMQ_VHOST = os.environ.get("RABBITMQ_VHOST", "/")
SPEECH_KEY = os.environ.get("SPEECH_KEY", "")
SPEECH_REGION = os.environ.get("SPEECH_REGION", "canadacentral")

# New: TTS engine selection
TTS_ENGINE = os.environ.get("TTS_ENGINE", "azure").lower()

# For piper, specify the binary and model path via env
PIPER_BINARY = os.environ.get("PIPER_BINARY", "/usr/local/bin/piper")
#PIPER_MODEL = os.environ.get("PIPER_MODEL", "/models/en_US-amy-low.onnx")
#PIPER_SPEAKER = os.environ.get("PIPER_SPEAKER", "")

OUTPUT_DIR = Path(os.getenv("TTS_DIR", "/artifacts/tts_output/"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CELERY_BROKER_URL = (
    f"amqp://{RABBITMQ_USER}:{RABBITMQ_PASS}@{RABBITMQ_HOST}:{RABBITMQ_PORT}{RABBITMQ_VHOST}"
)

celery_app = Celery(
    'tts_processor',
    broker=CELERY_BROKER_URL
)

@celery_app.task(queue='tts_tasks', name='tts_processor.synthesize')
def synthesize(input_dir: str, job_id: str, voice: str, tts_engine: str, piper_args: list[float], file_id: str) -> str:
    input_path = Path(input_dir)
    if not input_path.exists() or not input_path.is_dir():
        raise ValueError(f"{input_dir} is not a valid directory")

    audio_files = []
    OUTPUT_JOB_DIR = OUTPUT_DIR / job_id
    OUTPUT_JOB_DIR.mkdir(parents=True, exist_ok=True)

    for text_file in sorted(input_path.glob("*.txt")):
        filename = text_file.stem
        with open(text_file, "r", encoding="utf-8") as f:
            text = f.read().strip()
            if not text:
                continue
        output_file = OUTPUT_JOB_DIR / f"{filename}.mp3"
        print(f"[DEBUG] Processing: {text_file}")
        print(f"[DEBUG] Saving to: {output_file}")

        try:
            if not os.access(OUTPUT_JOB_DIR, os.W_OK):
                raise PermissionError(f"Cannot write to output directory: {OUTPUT_JOB_DIR}")
            if tts_engine == "azure":
                # --- Azure TTS ---
                if not speechsdk:
                    raise ImportError("azure.cognitiveservices.speech not installed.")
                speech_config = speechsdk.SpeechConfig(subscription=SPEECH_KEY, region=SPEECH_REGION)
                speech_config.speech_synthesis_voice_name = voice
                speech_config.set_speech_synthesis_output_format(
                    speechsdk.SpeechSynthesisOutputFormat.Audio48Khz192KBitRateMonoMp3
                )
                audio_config = speechsdk.audio.AudioOutputConfig(filename=str(output_file))
                synthesizer = speechsdk.SpeechSynthesizer(speech_config, audio_config)
                result = synthesizer.speak_text_async(text).get()

                if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                    audio_files.append(str(output_file))
                elif result.reason == speechsdk.ResultReason.Canceled:
                    cancellation = result.cancellation_details
                    print(f"[ERROR] Cancelled: {cancellation.reason} - {cancellation.error_details}")
                    raise RuntimeError(f"TTS failed for {filename}")
            elif tts_engine == "piper":
                # --- Piper TTS via subprocess ---
                # Piper needs WAV output by default, so we'll generate a WAV and convert to MP3 if needed
                output_wav = OUTPUT_JOB_DIR / f"{filename}.wav"
                print(f"Running Piper with length scale {piper_args[0]}, noise scale {piper_args[1]}, and phoneme variability parameter {piper_args[2]}") 
                piper_cmd = [
                    PIPER_BINARY,
                    "--model", "/models/"+voice+".onnx",
                    "--output_file", str(output_wav),
                    "--length_scale", str(piper_args[0]),        # speed of speech; higher=slower
                    "--noise_scale", str(piper_args[1]),       # speech pattern variation; lower=flatter
                    "--noise_w", str(piper_args[2])            # duration/affects timing and rhythm
                ]
                print(f"[DEBUG] Running Piper: {' '.join(piper_cmd)}")

                proc = subprocess.run(
                    piper_cmd,
                    input=text.encode("utf-8"),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                if proc.returncode != 0:
                    print(proc.stderr.decode())
                    raise RuntimeError(f"Piper TTS failed for {filename}")
                # Convert WAV to MP3
                subprocess.run([
                    "ffmpeg", "-y", "-i", str(output_wav), str(output_file)
                ], check=True)
                os.remove(output_wav)
                audio_files.append(str(output_file))
            else:
                raise ValueError(f"Unknown TTS_ENGINE: {TTS_ENGINE}")

        except Exception as e:
            print(f"[ERROR] failed to synthesize {text_file.name}: {e}")

    task_name = "ffmpeg_service.produce_video"
    args = [job_id, file_id]
    result = celery_app.send_task(
        name=task_name,
        args=args,
        queue="video_producer"
    )
    result_str = str(result)
    print(f"Task sent from tts_tasks, result: {result_str}")    
    return audio_files
