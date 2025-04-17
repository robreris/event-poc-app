from config import SPEECH_KEY, SPEECH_REGION, VOICE, OUTPUT_DIR
import azure.cognitiveservices.speech as speechsdk
from celery import Celery

OUTPUT_DIR.mkdir(exist_ok=True)

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
    'tasks',
    broker=CELERY_BROKER_URL
)

@celery_app.task(queue='tts-process', name='tasks.synthesize')
def synthesize(text: str, filename: str = "output") -> str:
    audio_path = OUTPUT_DIR / f"{filename}.mp3"

    speech_config = speechsdk.SpeechConfig(subscription=SPEECH_KEY, region=SPEECH_REGION)
    speech_config.speech_synthesis_voice_name = VOICE
    speech_config.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Audio48Khz192KBitRateMonoMp3
    )
    audio_config = speechsdk.audio.AudioOutputConfig(filename=str(audio_path))
    synthesizer = speechsdk.SpeechSynthesizer(speech_config, audio_config)

    result = synthesizer.speak_text_async(text).get()
    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        return str(audio_path)
    elif result.reason == speechsdk.ResultReason.Canceled:
        cancellation = result.cancellation_details
        raise RuntimeError(f"TTS failed: {cancellation.reason} - {cancellation.error_details}")

