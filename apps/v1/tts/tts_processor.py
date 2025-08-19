import os, re
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

    def insert_pauses_after_period(text, pause_ms=250):
        # Adds [pause=250] after every period (optionally, only at sentence ends)
        pause_token = f"[pause={pause_ms}]"
        # This regex adds a pause after any period (.), question mark (?), or exclamation (!)
        # followed by space/newline and a capital letter or end of string.
        return re.sub(r'([.?!])(\s+)', r'\1' + pause_token + r'\2', text)


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
                # treat each period as a pause
                text = insert_pauses_after_period(text, pause_ms=250)

                # Split text on [pause=NNN] tokens
                parts = re.split(r'(\[pause=\d+\])', text)
                part_files = []

                for i, part in enumerate(parts):
                    match = re.match(r'\[pause=(\d+)\]', part)
                    if match:
                        # Generate silence for the pause
                        ms = int(match.group(1)) / 1000.0  # Convert ms to seconds
                        pause_wav = OUTPUT_JOB_DIR / f"{filename}_pause_{i}.wav"
                        subprocess.run([
                            "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=22050:cl=mono",
                            "-t", str(ms), str(pause_wav)
                        ], check=True)
                        part_files.append(str(pause_wav))
                    elif part.strip():
                        # Generate TTS for this chunk
                        part_wav = OUTPUT_JOB_DIR / f"{filename}_part_{i}.wav"
                        piper_cmd = [
                            PIPER_BINARY,
                            "--model", f"/models/{voice}.onnx",
                            "--output_file", str(part_wav),
                            "--length_scale", str(piper_args[0]),
                            "--noise_scale", str(piper_args[1]),
                            "--noise_w", str(piper_args[2])
                        ]
                        print(f"[DEBUG] Running Piper for chunk {i}: {' '.join(piper_cmd)}")
                        proc = subprocess.run(
                            piper_cmd,
                            input=part.encode("utf-8"),
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE
                        )
                        if proc.returncode != 0:
                            print(proc.stderr.decode())
                            raise RuntimeError(f"Piper TTS failed for {filename}, chunk {i}")
                        part_files.append(str(part_wav))

                # Write concat list file
                concat_file = OUTPUT_JOB_DIR / f"{filename}_concat.txt"
                with open(concat_file, "w") as f:
                    for wav in part_files:
                        f.write(f"file '{wav}'\n")

                # Concatenate all .wav parts
                final_wav = OUTPUT_JOB_DIR / f"{filename}_final.wav"
                subprocess.run([
                    "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                    "-i", str(concat_file),
                    "-c", "copy", str(final_wav)
                ], check=True)

                # Convert final wav to mp3
                subprocess.run([
                    "ffmpeg", "-y", "-i", str(final_wav), str(output_file)
                ], check=True)

                # Optionally, cleanup temp files
                for f in part_files + [str(final_wav), str(concat_file)]:
                    try:
                        os.remove(f)
                    except Exception:
                        pass

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
