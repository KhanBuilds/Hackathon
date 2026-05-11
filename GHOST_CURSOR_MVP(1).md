# 👻 Ghost Cursor — MVP Build Doc
**6-Hour Sprint | Python + PyQt6 + Claude Vision**

---

## What We're Building

Press **F9** → speak your question → Ghost Cursor animates to the exact UI element on screen → tooltip explains it.

```
[F9 held] → mic records → Faster-Whisper transcribes
        → pyautogui screenshots → Claude vision returns (x,y) + explanation
        → PyQt6 overlay animates ghost cursor → tooltip appears
```

**Three apps supported at launch:** VS Code, Premiere Pro, Photoshop
**Platform:** Windows (primary). macOS notes included where different.

---

## Directory Structure

```
ghost-cursor/
├── main.py                  # Entry point
├── .env                     # Keys + config (never commit)
├── .env.example             # Safe to commit
├── requirements.txt
├── .gitignore
│
├── core/
│   ├── __init__.py
│   ├── listener.py          # F9 hotkey + mic recording thread
│   ├── stt.py               # Faster-Whisper local transcription
│   ├── vision.py            # Screenshot + Claude VLM → (x, y, explanation)
│   └── app_detector.py      # Gets active process name
│
├── overlay/
│   ├── __init__.py
│   ├── canvas.py            # Full-screen click-through PyQt6 window (draw layer)
│   ├── cursor_widget.py     # Animated ghost cursor drawn on canvas
│   └── tooltip_window.py    # Separate always-on-top window (NOT child of canvas)
│
├── prompts/
│   ├── system_prompt.txt    # Core VLM instruction
│   └── profiles/
│       ├── vscode.txt
│       ├── premiere_pro.txt
│       └── photoshop.txt
│
└── utils/
    ├── __init__.py
    └── logger.py
```

> **Why tooltip is a separate window, not a child of canvas:**
> The canvas is click-through (`WS_EX_TRANSPARENT` via win32). If tooltip is a child widget,
> it inherits transparency and becomes unclickable/invisible to the OS. It must be its own
> `QWidget` with `WindowStaysOnTopHint` — separate from the canvas entirely.

---

## `.env.example`

```env
# ─────────────────────────────────────────────
#  GHOST CURSOR — copy to .env, fill real keys
# ─────────────────────────────────────────────

# Anthropic — Vision + coordinate extraction
ANTHROPIC_API_KEY=sk-ant-api03-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX-XXXXXXXX

# OpenAI — Whisper API fallback (optional, local STT preferred)
OPENAI_API_KEY=sk-proj-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX

# ── Hotkey ───────────────────────────────────
HOTKEY=f9

# ── Overlay ──────────────────────────────────
CURSOR_ANIMATION_MS=650
TOOLTIP_DURATION_MS=7000

# ── STT ──────────────────────────────────────
# 'local' = Faster-Whisper on CPU (recommended)
# 'openai' = Whisper API (fallback, needs OPENAI_API_KEY)
STT_BACKEND=local
WHISPER_MODEL=base.en
RECORD_SECONDS=5

# ── VLM ──────────────────────────────────────
VLM_MODEL=claude-sonnet-4-20250514
VLM_MAX_TOKENS=400

# ── Debug ────────────────────────────────────
LOG_LEVEL=DEBUG
```

---

## `requirements.txt`

```txt
# Core
anthropic>=0.25.0
python-dotenv>=1.0.1

# STT
faster-whisper>=1.0.0
sounddevice>=0.4.6
numpy>=1.26.0

# Screen
pyautogui>=0.9.54
Pillow>=10.3.0

# Overlay
PyQt6>=6.7.0

# Hotkey
keyboard>=0.13.5

# Audio file I/O (Whisper API fallback)
soundfile>=0.12.1

# Process detection
psutil>=5.9.8

# Windows only — remove on macOS/Linux
pywin32>=306
```

---

## `main.py`

```python
import sys
import os
from dotenv import load_dotenv

# Load .env BEFORE importing anything that reads env vars
load_dotenv()

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
from overlay.canvas import GhostCanvas
from overlay.tooltip_window import TooltipWindow
from core.listener import HotkeyListener
from utils.logger import log


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # Two separate windows: click-through draw layer + tooltip
    canvas = GhostCanvas()
    tooltip = TooltipWindow()

    canvas.show()

    def on_result(x: int, y: int, element: str, explanation: str):
        """Called from worker thread via Qt signal — runs on main thread."""
        canvas.animate_cursor_to(x, y)
        tooltip.show_at(x, y, element, explanation)

    def on_query(query: str):
        log(f"Query received: {query}")
        canvas.set_thinking(True)
        tooltip.hide()
        canvas.dispatch_vlm(query, callback=on_result)

    listener = HotkeyListener(callback=on_query)
    listener.start()

    log("Ghost Cursor running. Hold F9 and speak.")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
```

---

## `core/listener.py`

```python
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
```

---

## `core/stt.py`

```python
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
```

---

## `core/app_detector.py`

```python
import platform
import psutil
from utils.logger import log


def get_active_app() -> str:
    """Returns lowercase process name of the focused window."""
    system = platform.system()

    try:
        if system == "Windows":
            import win32gui
            import win32process
            hwnd = win32gui.GetForegroundWindow()
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            name = psutil.Process(pid).name().lower()
            log(f"Active app (Windows): {name}")
            return name

        elif system == "Darwin":
            from AppKit import NSWorkspace
            name = NSWorkspace.sharedWorkspace().frontmostApplication().localizedName().lower()
            log(f"Active app (macOS): {name}")
            return name

        elif system == "Linux":
            import subprocess
            pid = subprocess.check_output(
                ["xdotool", "getactivewindow", "getwindowpid"]
            ).decode().strip()
            name = subprocess.check_output(
                ["ps", "-p", pid, "-o", "comm="]
            ).decode().strip().lower()
            log(f"Active app (Linux): {name}")
            return name

    except Exception as e:
        log(f"App detection failed: {e}", level="WARNING")

    return "unknown"
```

---

## `core/vision.py`

```python
import os
import base64
import json
from io import BytesIO

import pyautogui
import anthropic
from utils.logger import log
from core.app_detector import get_active_app

# Client initialized at call time (after .env loaded via main.py)
_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _client


SYSTEM_PROMPT = """You are a UI Vision Agent for desktop applications.

Given a screenshot and a user query, locate the EXACT UI element they need.

Rules:
- Analyze the screenshot carefully before responding
- Coordinates must be pixel-accurate to the visible element center
- The screen resolution is provided in the query — use it to calibrate
- Return ONLY raw JSON. No markdown. No explanation outside the JSON.

Response format:
{
  "x": <integer>,
  "y": <integer>,
  "element_name": "<concise name>",
  "explanation": "<1-2 sentences: what this element does and how to use it>"
}

If the element is not visible in the screenshot:
{"x": -1, "y": -1, "element_name": "not_found", "explanation": "That element isn't visible in the current view. Try opening the relevant panel first."}"""


def _load_app_profile(app_name: str) -> str:
    profiles = {
        "code": "vscode.txt",
        "premiere": "premiere_pro.txt",
        "photoshop": "photoshop.txt",
        "adobe premiere": "premiere_pro.txt",
    }
    for key, filename in profiles.items():
        if key in app_name:
            path = os.path.join("prompts", "profiles", filename)
            try:
                with open(path) as f:
                    return f.read().strip()
            except FileNotFoundError:
                log(f"Profile not found: {path}", level="WARNING")
    return ""


def capture_screenshot() -> str:
    """Returns base64-encoded PNG of the primary screen."""
    shot = pyautogui.screenshot()
    buf = BytesIO()
    shot.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def query_vlm(query: str) -> dict:
    """
    Sends screenshot + query to Claude.
    Returns dict: {x, y, element_name, explanation}
    """
    app_name = get_active_app()
    screen_w, screen_h = pyautogui.size()
    app_profile = _load_app_profile(app_name)

    user_content = (
        f"Screen resolution: {screen_w}x{screen_h}\n"
        f"Active application: {app_name}\n"
    )
    if app_profile:
        user_content += f"App context:\n{app_profile}\n"
    user_content += f"\nUser query: {query}"

    log(f"Querying VLM | app={app_name} | query='{query}'")

    screenshot_b64 = capture_screenshot()

    response = _get_client().messages.create(
        model=os.getenv("VLM_MODEL", "claude-sonnet-4-20250514"),
        max_tokens=int(os.getenv("VLM_MAX_TOKENS", 400)),
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": screenshot_b64,
                        },
                    },
                    {"type": "text", "text": user_content},
                ],
            }
        ],
    )

    raw = response.content[0].text.strip()
    log(f"VLM raw: {raw}")

    try:
        result = json.loads(raw)
        # Clamp coordinates to screen bounds
        result["x"] = max(0, min(int(result.get("x", -1)), screen_w))
        result["y"] = max(0, min(int(result.get("y", -1)), screen_h))
        return result
    except (json.JSONDecodeError, ValueError) as e:
        log(f"JSON parse error: {e}", level="ERROR")
        return {
            "x": -1, "y": -1,
            "element_name": "parse_error",
            "explanation": "Failed to parse model response."
        }
```

---

## `overlay/canvas.py`

```python
import os
import ctypes
import platform

from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtCore import Qt, QPoint, QPropertyAnimation, QEasingCurve, QTimer, QThread, pyqtSignal, pyqtProperty
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush

from utils.logger import log


class VLMWorker(QThread):
    """Runs VLM call off main thread. Emits result when done."""
    finished = pyqtSignal(int, int, str, str)  # x, y, element, explanation

    def __init__(self, query: str):
        super().__init__()
        self.query = query

    def run(self):
        from core.vision import query_vlm
        result = query_vlm(self.query)
        self.finished.emit(
            result["x"],
            result["y"],
            result.get("element_name", "unknown"),
            result.get("explanation", "")
        )


class GhostCanvas(QWidget):
    """
    Full-screen transparent window that draws the ghost cursor.
    Made click-through via win32 WS_EX_TRANSPARENT after show().

    IMPORTANT: Tooltip must be a SEPARATE window, not a child of this.
    Children inherit click-through and become inert.
    """

    def __init__(self):
        super().__init__()
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

        # Cursor state
        self._cursor_pos = QPoint(-100, -100)
        self._thinking = False
        self._visible = False
        self._animation = None
        self._worker = None
        self._callback = None

        # Pulse timer for "thinking" animation
        self._pulse_timer = QTimer()
        self._pulse_timer.setInterval(80)
        self._pulse_timer.timeout.connect(self._pulse_tick)
        self._pulse_alpha = 255
        self._pulse_dir = -1

    def showEvent(self, event):
        super().showEvent(event)
        if platform.system() == "Windows":
            self._apply_click_through_windows()

    def _apply_click_through_windows(self):
        """Sets WS_EX_TRANSPARENT | WS_EX_LAYERED on Windows so mouse events pass through."""
        GWL_EXSTYLE = -20
        WS_EX_TRANSPARENT = 0x00000020
        WS_EX_LAYERED = 0x00080000

        hwnd = int(self.winId())
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        ctypes.windll.user32.SetWindowLongW(
            hwnd, GWL_EXSTYLE, style | WS_EX_TRANSPARENT | WS_EX_LAYERED
        )
        log("Click-through applied (Windows)")

    # ── VLM dispatch ─────────────────────────────────────────────────

    def dispatch_vlm(self, query: str, callback):
        """Spawns VLM worker thread. callback(x, y, element, explanation) on main thread."""
        self._callback = callback
        self._worker = VLMWorker(query)
        self._worker.finished.connect(self._on_vlm_done)
        self._worker.start()

    def _on_vlm_done(self, x: int, y: int, element: str, explanation: str):
        self.set_thinking(False)
        if x == -1:
            log("Element not found — hiding cursor")
            self._visible = False
            self.update()
        if self._callback:
            self._callback(x, y, element, explanation)

    # ── Cursor animation ──────────────────────────────────────────────

    def animate_cursor_to(self, x: int, y: int):
        duration = int(os.getenv("CURSOR_ANIMATION_MS", 650))
        self._visible = True

        self._animation = QPropertyAnimation(self, b"cursor_pos")
        self._animation.setDuration(duration)
        self._animation.setStartValue(self._cursor_pos)
        self._animation.setEndValue(QPoint(x, y))
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.start()

        # Auto-hide cursor after tooltip expires
        total = duration + int(os.getenv("TOOLTIP_DURATION_MS", 7000)) + 500
        QTimer.singleShot(total, self._hide_cursor)

    def _hide_cursor(self):
        self._visible = False
        self._thinking = False
        self.update()

    # ── Thinking pulse ────────────────────────────────────────────────

    def set_thinking(self, thinking: bool):
        self._thinking = thinking
        self._visible = thinking
        if thinking:
            screen = QApplication.primaryScreen().geometry()
            self._cursor_pos = QPoint(screen.width() // 2, screen.height() // 2)
            self._pulse_timer.start()
        else:
            self._pulse_timer.stop()
        self.update()

    def _pulse_tick(self):
        self._pulse_alpha += self._pulse_dir * 15
        if self._pulse_alpha <= 60:
            self._pulse_dir = 1
        elif self._pulse_alpha >= 240:
            self._pulse_dir = -1
        self._pulse_alpha = max(60, min(255, self._pulse_alpha))
        self.update()

    # ── Qt property for animation ─────────────────────────────────────

    def get_cursor_pos(self):
        return self._cursor_pos

    def set_cursor_pos(self, pos: QPoint):
        self._cursor_pos = pos
        self.update()

    cursor_pos = pyqtProperty(QPoint, fget=get_cursor_pos, fset=set_cursor_pos)

    # ── Paint ─────────────────────────────────────────────────────────

    def paintEvent(self, event):
        if not self._visible:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        x, y = self._cursor_pos.x(), self._cursor_pos.y()
        alpha = self._pulse_alpha if self._thinking else 200

        # Outer glow ring
        glow_color = QColor(0, 212, 255, alpha // 3)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(glow_color))
        painter.drawEllipse(x - 22, y - 22, 44, 44)

        # Main cursor circle
        main_color = QColor(0, 212, 255, alpha)
        border_color = QColor(255, 255, 255, min(alpha + 40, 255))

        painter.setPen(QPen(border_color, 2))
        painter.setBrush(QBrush(main_color))
        painter.drawEllipse(x - 12, y - 12, 24, 24)

        # Crosshair lines
        pen = QPen(QColor(255, 255, 255, alpha), 1)
        painter.setPen(pen)
        painter.drawLine(x - 20, y, x - 14, y)
        painter.drawLine(x + 14, y, x + 20, y)
        painter.drawLine(x, y - 20, x, y - 14)
        painter.drawLine(x, y + 14, x, y + 20)

        painter.end()
```

---

## `overlay/tooltip_window.py`

```python
import os
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QApplication
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont


class TooltipWindow(QWidget):
    """
    Standalone always-on-top window for the explanation tooltip.
    Must NOT be a child of GhostCanvas — canvas is click-through,
    which would make this invisible/inert if parented to it.
    """

    MAX_WIDTH = 340

    def __init__(self):
        super().__init__(parent=None)  # Explicit: no parent
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMaximumWidth(self.MAX_WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(4)

        self._title = QLabel()
        self._title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._title.setStyleSheet("color: #00D4FF; background: transparent;")

        self._body = QLabel()
        self._body.setFont(QFont("Segoe UI", 9))
        self._body.setStyleSheet("color: #E8E8E8; background: transparent;")
        self._body.setWordWrap(True)

        layout.addWidget(self._title)
        layout.addWidget(self._body)

        self.setStyleSheet("""
            QWidget {
                background-color: rgba(15, 18, 28, 225);
                border: 1px solid rgba(0, 212, 255, 180);
                border-radius: 10px;
            }
        """)

        self._hide_timer = QTimer()
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

        self.hide()

    def show_at(self, x: int, y: int, element: str, explanation: str):
        if x == -1:
            self.hide()
            return

        self._title.setText(f"⬤  {element.replace('_', ' ').title()}")
        self._body.setText(explanation)
        self.adjustSize()

        screen = QApplication.primaryScreen().geometry()
        sw, sh = screen.width(), screen.height()

        # Prefer right of cursor, flip left if near edge
        tx = x + 70
        if tx + self.MAX_WIDTH > sw - 20:
            tx = x - self.width() - 30

        # Prefer above cursor center, clamp to screen
        ty = y - self.height() // 2
        ty = max(20, min(ty, sh - self.height() - 20))

        self.move(tx, ty)
        self.show()
        self.raise_()

        duration = int(os.getenv("TOOLTIP_DURATION_MS", 7000))
        self._hide_timer.start(duration)
```

---

## `utils/logger.py`

```python
import os
from datetime import datetime

_LEVELS = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3}


def log(message: str, level: str = "DEBUG"):
    threshold = _LEVELS.get(os.getenv("LOG_LEVEL", "DEBUG").upper(), 0)
    if _LEVELS.get(level.upper(), 0) >= threshold:
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{ts}] [{level:>7}] {message}")
```

---

## `prompts/system_prompt.txt`

```
You are a UI Vision Agent for desktop software.
Given a screenshot and user query, locate the exact pixel coordinates of the requested UI element.
Return ONLY raw JSON — no markdown fences, no prose, no explanation outside the JSON.
The user's screen resolution is in the query. Use it to produce accurate coordinates.
```

---

## `prompts/profiles/vscode.txt`

```
VS Code layout:
- Activity bar: far-left vertical strip (Explorer, Search, Source Control, Run, Extensions icons)
- Sidebar: opens to the right of activity bar (file tree, search results, etc.)
- Editor: center area with tabs at top
- Terminal: bottom panel (toggle with Ctrl+`)
- Status bar: very bottom strip (branch name, errors, language mode)
- Command palette: triggered by Ctrl+Shift+P — appears as top-center dropdown
- Settings gear icon: bottom-left of activity bar
```

---

## `prompts/profiles/premiere_pro.txt`

```
Premiere Pro layout:
- Tools panel: left side, vertical strip (Selection V, Razor C, Pen P, Text T, etc.)
- Project panel: bottom-left (media bins, sequences)
- Source Monitor: top-left (preview imported clips)
- Program Monitor: top-right (preview timeline output)
- Timeline: bottom-center (tracks, clips, audio waveforms)
- Effects panel: right side (Video Effects, Audio Effects)
- Effect Controls: top-left area or floating (keyframes, transform, opacity, masks)
- Lumetri Color: right panel (color grading scopes and wheels)
- Essential Graphics: right panel (text/motion graphics)
- Export: File > Export > Media (shortcut Ctrl+M)
```

---

## `prompts/profiles/photoshop.txt`

```
Photoshop layout:
- Toolbar: far-left vertical strip (Move V, Marquee M, Lasso L, Crop C, Brush B, etc.)
- Options bar: horizontal bar at top below menu (tool-specific settings)
- Layers panel: bottom-right (layer stack, blending modes, opacity)
- Properties panel: right side (layer-specific adjustments)
- Adjustments panel: right side (Curves, Levels, Hue/Saturation, etc.)
- History panel: right side (undo states)
- Color panel: right side (foreground/background color)
- Menu bar: top (File, Edit, Image, Layer, Type, Select, Filter, View, Window, Help)
- Document canvas: center area
```

---

## `.gitignore`

```
.env
__pycache__/
*.pyc
*.pyo
.venv/
venv/
*.log
dist/
build/
```

---

## 6-Hour Sprint Plan

| Time | Task | Done When |
|------|------|-----------|
| **0:00 – 0:20** | Create folder structure, paste all files, install deps | `python main.py` doesn't crash on import |
| **0:20 – 1:00** | Test `core/vision.py` standalone with a hardcoded query | Claude returns valid JSON with real coordinates |
| **1:00 – 1:45** | Test overlay: `canvas.py` shows full-screen, cursor draws and animates | You see the blue circle move on screen |
| **1:45 – 2:15** | Test `tooltip_window.py` in isolation | Dark tooltip appears at correct screen position |
| **2:15 – 2:50** | Wire STT: run `stt.py` standalone, record, transcribe | Terminal prints what you said |
| **2:50 – 3:20** | Wire `listener.py`: F9 → record → transcribe → print query | Full STT chain works end-to-end |
| **3:20 – 4:15** | Full integration: F9 → query → Claude → cursor + tooltip | Ghost cursor navigates to element |
| **4:15 – 5:00** | Test across VS Code, Premiere, Photoshop | 3 different apps respond correctly |
| **5:00 – 5:30** | Prompt tuning — fix coordinate drift, improve explanations | Accuracy feels reliable |
| **5:30 – 6:00** | Buffer: edge cases, screen-edge tooltip clipping, demo record | Ship it |

---

## Standalone Test Scripts

Run these in order before wiring everything together.

### `test_vision.py`
```python
from dotenv import load_dotenv
load_dotenv()
from core.vision import query_vlm
result = query_vlm("Where is the terminal toggle button?")
print(result)
```

### `test_stt.py`
```python
from dotenv import load_dotenv
load_dotenv()
import sounddevice as sd
import numpy as np
from core.stt import transcribe_audio
print("Recording 5s — say something...")
audio = sd.rec(int(5 * 16000), samplerate=16000, channels=1, dtype=np.float32)
sd.wait()
print(transcribe_audio(audio.flatten()))
```

### `test_overlay.py`
```python
import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
from overlay.canvas import GhostCanvas
from overlay.tooltip_window import TooltipWindow

app = QApplication(sys.argv)
canvas = GhostCanvas()
tooltip = TooltipWindow()
canvas.show()

def demo():
    canvas.animate_cursor_to(800, 450)
    tooltip.show_at(800, 450, "test_element", "This is a test tooltip. Cursor should be at 800,450 with a blue crosshair.")

QTimer.singleShot(1000, demo)
sys.exit(app.exec())
```

---

## Install & Run

```bash
# Setup
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux

pip install -r requirements.txt

# Configure
copy .env.example .env          # Windows
# cp .env.example .env          # macOS/Linux
# → Add your ANTHROPIC_API_KEY to .env

# Test pieces first (in order)
python test_vision.py
python test_stt.py
python test_overlay.py

# Run
python main.py
```

---

## Known Constraints

| Issue | Impact | Fix |
|-------|--------|-----|
| VLM latency 1.5–3s | User waits after F9 | Thinking pulse shows immediately — feels responsive |
| Coordinate accuracy ±20px | Cursor slightly off-center | Still points at the right element; acceptable for MVP |
| Fixed 5s recording | Short queries get silence | Fine for demo; silence detection (`webrtcvad`) is v0.2 |
| Primary screen only | Multi-monitor misses | Ship on single screen, note as known limit |
| Windows primary target | macOS needs `NSWindow` level tweaks | `_apply_click_through_windows` is gated behind `platform.system()` check |

---

*Ghost Cursor v0.1 — Press F9. Speak. Watch it move.*
