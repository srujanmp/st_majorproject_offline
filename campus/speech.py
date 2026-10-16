"""Speech to text with Vosk, fully offline.

The browser records the microphone and sends a WAV file (16 kHz, mono,
16-bit). Vosk turns it into text on this computer. Nothing leaves the machine.
"""
import io
import json
import wave
from functools import lru_cache

from . import config

MAX_SECONDS = 60


class SpeechError(Exception):
    pass


def model_dir():
    return config.MODELS_DIR / "vosk"


@lru_cache(maxsize=1)
def _model():
    from vosk import Model, SetLogLevel

    SetLogLevel(-1)  # keep the console quiet
    if not (model_dir() / "am").exists():
        raise SpeechError("The speech model is missing. See README: Get the models.")
    return Model(str(model_dir()))


def transcribe(wav_bytes: bytes) -> str:
    from vosk import KaldiRecognizer

    try:
        with wave.open(io.BytesIO(wav_bytes)) as wav:
            if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
                raise SpeechError("Audio must be mono 16-bit WAV.")
            rate, frames = wav.getframerate(), wav.getnframes()
            if frames > rate * MAX_SECONDS:
                raise SpeechError(f"Recordings can be at most {MAX_SECONDS} seconds long.")
            audio = wav.readframes(frames)
    except (wave.Error, EOFError):
        raise SpeechError("That is not a WAV recording we can read.")

    recognizer = KaldiRecognizer(_model(), rate)
    step = 8000  # feed about a quarter second at a time
    for start in range(0, len(audio), step):
        recognizer.AcceptWaveform(audio[start : start + step])
    return json.loads(recognizer.FinalResult()).get("text", "").strip()
