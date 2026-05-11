import os
import numpy as np
from utils.logger import log

_whisper_model = None


def _get_local_model():
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        model_size = os.getenv("WHISPER_MODEL", "base.en")
        log(f"Loading Whisper model: {model_size}")
        _whisper_model = WhisperModel(model_size, device="cpu", compute_type="int8")
        log("Whisper model ready.")
    return _whisper_model


def transcribe_audio(audio_np: np.ndarray) -> str:
    backend = os.getenv("STT_BACKEND", "local")

    if backend == "local":
        model = _get_local_model()
        segments, _ = model.transcribe(audio_np, language="en")
        result = " ".join(seg.text.strip() for seg in segments)
        log(f"Transcribed: '{result}'")
        return result

    elif backend == "openai":
        import tempfile
        import soundfile as sf
        import openai

        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            sf.write(tmp.name, audio_np, 16000)
            tmp_path = tmp.name

        with open(tmp_path, "rb") as f:
            result = client.audio.transcriptions.create(model="whisper-1", file=f)

        os.unlink(tmp_path)
        return result.text

    return ""
