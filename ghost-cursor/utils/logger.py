import os
from datetime import datetime

_LEVELS = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3}


def log(message: str, level: str = "DEBUG"):
    threshold = _LEVELS.get(os.getenv("LOG_LEVEL", "DEBUG").upper(), 0)
    if _LEVELS.get(level.upper(), 0) >= threshold:
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{ts}] [{level:>7}] {message}")
