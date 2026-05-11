from dotenv import load_dotenv
load_dotenv()
import sounddevice as sd
import numpy as np
from core.stt import transcribe_audio
print("Recording 5s — say something...")
audio = sd.rec(int(5 * 16000), samplerate=16000, channels=1, dtype=np.float32)
sd.wait()
print(transcribe_audio(audio.flatten()))
