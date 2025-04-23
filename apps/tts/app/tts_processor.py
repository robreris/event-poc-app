from config import SPEECH_KEY, SPEECH_REGION, VOICE, OUTPUT_DIR
import azure.cognitiveservices.speech as speechsdk
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

# Configure the Celery app.
# Replace 'RABBITMQ_HOST' with your actual RabbitMQ host name or IP.
celery_app = Celery(
    'tts_processor',
    broker=CELERY_BROKER_URL
)

OUTPUT_DIR = Path(os.getenv("TTS_DIR", "/artifacts/tts_output/"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

@celery_app.task(queue='tts_tasks', name='tts_processor.synthesize')
def synthesize(input_dir: str, job_id: str) -> str:
    input_path = Path(input_dir)
    if not input_path.exists() or not input_path.is_dir():
        raise ValueError(f"{input_dir} is not a valid directory")

    speech_config = speechsdk.SpeechConfig(subscription=SPEECH_KEY, region=SPEECH_REGION)
    speech_config.speech_synthesis_voice_name = VOICE
    speech_config.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Audio48Khz192KBitRateMonoMp3
    )

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
                raise PermissionError(f"Cannot write to output directory: {OUTPUT_DIR}")
                
            audio_config = speechsdk.audio.AudioOutputConfig(filename=str(output_file))
            synthesizer = speechsdk.SpeechSynthesizer(speech_config, audio_config)
            result = synthesizer.speak_text_async(text).get()

            if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                audio_files.append(str(output_file))
            elif result.reason == speechsdk.ResultReason.Canceled:
                cancellation = result.cancellation_details
                print(f"[ERROR] Cancelled: {cancellation.reason} - {cancellation.error_details}")
                raise RuntimeError(f"TTS failed for {filename}")
        except Exception as e:
            print(f"[ERROR] failed to synthesize {text_file.name}: {e}")
    return audio_files
