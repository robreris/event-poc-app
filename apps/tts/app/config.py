import os
import json
from pathlib import Path

config = {}
CONFIG_PATH = Path(__file__).parent / "config.json"

if CONFIG_PATH.exists():
    with open(CONFIG_PATH) as f:
        config = json.load(f)

SPEECH_KEY = os.getenv("SPEECH_KEY") or config.get("speech_key")
SPEECH_REGION = os.getenv("SPEECH_REGION") or config.get("speech_region")
VOICE = os.getenv("VOICE") or config.get("voice", "en-US-AvaNeural")
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR") or config.get("output_dir", "audio"))
