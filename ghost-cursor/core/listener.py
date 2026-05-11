import os
import threading
import sounddevice as sd
import numpy as np
import keyboard
from core.stt import transcribe_audio
from utils.logger import log

SAMPLE_RATE = 16000


class HotkeyListener(threading.Thread):
    """
    Daemon thread. Blocks on keyboard.wait().
    On F9 press: records mic for RECORD_SECONDS, transcribes, calls callback.
    """

    def __init__(self, callback):
        super().__init__(daemon=True)
        self.callback = callback
        self._lock = threading.Lock()  # Prevent overlapping triggers

    def run(self):
        hotkey = os.getenv("HOTKEY", "f9")
        keyboard.add_hotkey(hotkey, self._handle)
        log(f"Listening for hotkey: {hotkey}")
        keyboard.wait()

    def _handle(self):
        # Drop duplicate triggers if already processing
        if not self._lock.acquire(blocking=False):
            log("Already processing — ignoring trigger")
            return
        try:
            audio = self._record()
            query = transcribe_audio(audio)
            if query and query.strip():
                self.callback(query.strip())
            else:
                log("Empty transcription — skipping")
        finally:
            self._lock.release()

    def _record(self) -> np.ndarray:
        seconds = int(os.getenv("RECORD_SECONDS", 5))
        log(f"Recording {seconds}s...")
        audio = sd.rec(
            int(seconds * SAMPLE_RATE),
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype=np.float32
        )
        sd.wait()
        log("Recording done.")
        return audio.flatten()
