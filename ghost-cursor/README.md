# Ghost Cursor 👻

> *"Where do I click?"* — just say it out loud.

Ghost Cursor is a hands-free desktop assistant that listens to your voice, looks at your screen, and glides an animated cursor to exactly the UI element you described. No clicking through menus, no hunting for buttons — just hold a hotkey, say what you want, and watch it land.

---

## What it does

You hold **F9**, speak a command like *"where's the export button"* or *"find the layers panel"*, and release. Ghost Cursor will:

1. Record your voice and transcribe it locally using [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (runs entirely on your machine, no cloud needed).
2. Capture a screenshot of your screen overlaid with a calibration grid.
3. Send the screenshot + your query to **Gemini 2.5 Flash** (Google's vision model), which identifies the element and returns its exact pixel coordinates.
4. Animate a glowing crosshair cursor to that spot, smooth and precise.
5. Pop up a tooltip explaining what it found and why.

If Gemini isn't confident in its first answer, the app automatically zooms into the area of interest and asks again — a two-stage refinement pass that significantly improves accuracy on dense UIs.

The overlay is completely **click-through** — it sits above all your windows but never gets in the way of your mouse.

---

## Why we built this

Navigating unfamiliar software is slow. Whether you're a new user learning a complex tool like Premiere Pro or Photoshop, someone with motor difficulties, or just in a hurry — finding a specific UI element often takes longer than it should. Ghost Cursor makes that instant.

---

## Getting started

### Prerequisites

- Python 3.10+
- A [Google Gemini API key](https://aistudio.google.com/app/apikey) (free tier works)
- A working microphone
- Windows (the overlay uses Win32 APIs for click-through behavior)

### Installation

```bash
# Clone the repo
git clone https://github.com/KhanBuilds/Hackathon.git
cd Hackathon/ghost-cursor

# Create a virtual environment
python -m venv .venv
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Configuration

Copy the example env file and fill in your keys:

```bash
copy .env.example .env
```

Open `.env` and at minimum set your Gemini API key:

```env
GEMINI_API_KEY=your_key_here
```

Everything else has sensible defaults, but you can tune them:

| Variable | Default | What it does |
|---|---|---|
| `HOTKEY` | `f9` | Key to hold while speaking |
| `STT_BACKEND` | `local` | `local` (faster-whisper) or `openai` (Whisper API) |
| `WHISPER_MODEL` | `base.en` | Model size — `tiny.en` is faster, `small.en` is more accurate |
| `RECORD_SECONDS` | `5` | How long to record after you press the hotkey |
| `VLM_MODEL` | `gemini-2.5-flash` | Gemini model to use for vision |
| `CURSOR_ANIMATION_MS` | `650` | How long the cursor glide animation takes |
| `TOOLTIP_DURATION_MS` | `7000` | How long the tooltip stays visible |

### Running

```bash
python main.py
```

The first run will download the Whisper model weights (~150 MB for `base.en`). After that it's instant. You'll see a log line confirming it's ready:

```
Ghost Cursor running. Hold F9 and speak.
```

---

## Usage tips

- **Speak clearly and describe the element** — "where is the timeline zoom slider" works better than "the thing at the bottom".
- **Keep queries short** — one element per query. Ghost Cursor picks the best match, not a list.
- **App-aware prompting** — Ghost Cursor detects which app is in the foreground and loads context-specific hints for VS Code, Premiere Pro, and Photoshop automatically. More app profiles can be added in `prompts/profiles/`.
- **Low confidence = automatic retry** — if Gemini's first guess scores below 0.75 confidence, the app zooms into that region and asks again. You don't need to do anything.

---

## Project structure

```
ghost-cursor/
├── main.py               # Entry point — wires everything together
├── core/
│   ├── listener.py       # Hotkey detection + mic recording
│   ├── stt.py            # Speech-to-text (faster-whisper or OpenAI)
│   ├── vision.py         # Screenshot capture, grid overlay, Gemini VLM query
│   └── app_detector.py   # Detects the currently active foreground app
├── overlay/
│   ├── canvas.py         # Full-screen transparent PyQt6 draw layer (click-through)
│   └── tooltip_window.py # Floating tooltip window with element name + explanation
├── prompts/
│   ├── system_prompt.txt # Base system prompt for the vision model
│   └── profiles/         # App-specific context hints (vscode, premiere, photoshop)
├── utils/
│   └── logger.py         # Lightweight logging wrapper
├── requirements.txt
└── .env.example
```

---

## How the vision pipeline works

The magic happens in `core/vision.py`. Here's the flow:

1. **Screenshot** — `pyautogui` grabs the full screen as a Pillow image.
2. **Grid overlay** — a semi-transparent green calibration grid is drawn on top (every 100px, with coordinate labels). This gives Gemini a ruler to work with, dramatically improving coordinate accuracy.
3. **Stage 1 query** — the annotated screenshot + your query are sent to Gemini. The response is a JSON blob with the element's bounding box, center coordinates, confidence, and a short explanation.
4. **Bounding box to center** — if Gemini returns a bounding box (`x1, y1, x2, y2`), the center is calculated precisely from those corners rather than trusting the raw `x, y` directly.
5. **Stage 2 zoom** (if confidence < 0.75) — a 400×400 crop centered on the first guess is taken, a finer grid (50px spacing) is overlaid, and Gemini is asked again. The zoomed coordinates are then mapped back to full-screen space.
6. **Clamp** — final coordinates are clamped to screen bounds to prevent the cursor going off-screen.

---

## Tech stack

| Layer | Technology |
|---|---|
| UI / Overlay | PyQt6 |
| Speech-to-text | faster-whisper (local) / OpenAI Whisper API |
| Vision / LLM | Google Gemini 2.5 Flash |
| Screen capture | pyautogui + Pillow |
| Audio recording | sounddevice |
| Hotkeys | keyboard |
| Win32 click-through | ctypes (WS_EX_TRANSPARENT) |

---

## Known limitations

- **Windows only** for now — the click-through overlay relies on Win32 APIs. The rest of the code is cross-platform, but the overlay would need a platform-specific implementation on macOS/Linux.
- **One query at a time** — if you press the hotkey while a query is already processing, it's ignored. This is intentional to avoid overlapping VLM calls.
- **Gemini needs internet** — the STT can run fully offline with `local` backend, but the vision step always calls the Gemini API.
- **App profiles are limited** — out of the box only VS Code, Premiere Pro, and Photoshop have custom context. Generic apps still work, just without app-specific hints.

---

## Contributing

Pull requests are welcome. If you want to add an app profile, just drop a `.txt` file in `prompts/profiles/` with layout hints and register the filename in `core/vision.py`'s `_load_app_profile()` function.

---

## License

MIT
