# Campus Assistant: offline edition

A voice assistant for NMAMIT that runs **entirely on one computer, with no internet**. A student signs in with their ID and password, passes a face check, taps the microphone, asks a question and hears the answer. Answers come only from information the admins have added.

It ships as a **single zip**: unzip, double-click, and the browser opens. No Python, no installation, no internet.

```
                 everything below runs on this computer
┌──────────────────────────────────────────────────────────────────────┐
│ Browser                      Campus Assistant (local server)         │
│                                                                      │
│ ID + password  ───────────►  checks the password (scrypt hash)       │
│ webcam picture ───────────►  face check: YuNet finds the face,       │
│                              SFace compares it with the registered   │
│                              one (ONNX Runtime)                      │
│ tap, speak, tap                                                      │
│   records 16 kHz WAV ─────►  speech to text: Vosk                    │
│                              search: MiniLM embeddings + numpy       │
│   reads answer aloud ◄─────  answer: best-matching sentences         │
│   (computer's own voice)     (or a local AI model, optional)         │
└──────────────────────────────────────────────────────────────────────┘
```

## For users: run it

1. Download the zip for your computer from the repository's **Releases** page (or from the **Actions** tab, latest "Build packages" run):

   | Computer | File |
   |---|---|
   | Windows 10/11 | `CampusAssistant-windows-x64.zip` |
   | Mac with Apple Silicon (M1 to M4) | `CampusAssistant-macos-arm64.zip` |
   | Linux PC | `CampusAssistant-linux-x64.zip` |
   | Raspberry Pi 4/5 (64-bit Raspberry Pi OS) | `CampusAssistant-linux-arm64.zip` |

2. Unzip it anywhere, even on a USB stick, and start **CampusAssistant** (`CampusAssistant.exe` on Windows). On a Mac the first time: right-click it, then **Open**.
3. The browser opens **http://localhost:8765**. On the first run, create the admin account and register your face.
4. In **Admin**, add knowledge (try importing the files in `sample_data/`) and add student accounts under **Users**.

Close the console window to stop the app. Your users and knowledge live in the `data/` folder next to the program; back that folder up.

## What changed from the online version, and why

| Online version | Offline version | Why |
|---|---|---|
| Google sign-in (@nmamit.in) | ID + password set by an admin, then face check | Google sign-in needs the internet |
| Groq cloud AI writes answers | Reads back the best-matching sentences (no AI model). A local AI model is optional | No internet; instant on a Raspberry Pi; never makes things up |
| Browser speech recognition (Google servers) | Vosk speech recognition on this computer | Chrome's speech recognition needs Google's servers |
| ChromaDB vector database | Vectors stored in SQLite, searched with numpy | ChromaDB is about 64 MB plus its dependencies. A college-sized knowledge base searches in about a millisecond with numpy |
| OpenCV library for faces | Same OpenCV face models (YuNet, SFace) run directly with ONNX Runtime | OpenCV is about 150 MB installed. Face detection gives exactly OpenCV's results |
| FastAPI + Uvicorn | Flask + Waitress | Pure-Python, works the same on Windows, macOS, Linux and the Pi |
| Text from images (OCR) | Removed. Import CSV, .txt or .md files instead | OCR would bring back OpenCV plus 31 MB of OCR models |

### How small it is

| Part | Size |
|---|---|
| Speech model (Vosk small English) | 68 MB unpacked |
| Search model (all-MiniLM-L6-v2, shrunk to 8-bit) | 23 MB (the full one is 90 MB) |
| Face models (YuNet + SFace 8-bit) | 10 MB |
| Program (Python, ONNX Runtime, numpy, Flask, Vosk) | about 120 MB unpacked |
| **The zip** | **about 120 MB** |

On a normal laptop: a face check takes about 0.1 s, a search about 2 ms, and an 11-second recording is transcribed in about 1.5 s.

## Admin guide

- **Knowledge → Add**: write short, plain sentences. The assistant reads back the 1–2 sentences that best match the question, so "The library is open from 8:30 AM to 8 PM on weekdays." works better than a table.
- **Import a file**:
  - A CSV with `title,content` columns gives one entry per row.
  - Any other CSV (timetable, staff list) also works: each row becomes "Column: value. Column: value."
  - A `.txt` or `.md` file becomes one entry.
- **Changes apply immediately.** The next question uses the new information.
- **Users**: add each student with an ID (e.g. USN) and a starting password, then press **Face** and either take a webcam picture or upload a photo. Only a 128-number face signature is stored, never the picture. There must always be at least one admin.

## Settings (`settings.ini`, next to the program)

Created on first run, with comments. Restart the app after editing.

| Setting | Default | Meaning |
|---|---|---|
| `[server] port` | `8765` | Change it if another program uses this port |
| `[server] host` | `127.0.0.1` | Only this computer can open the app (see "Using it from other devices" below) |
| `[face] match_threshold` | `0.363` | How similar the face must be (0–1). Higher is stricter |
| `[face] max_failures`, `lock_minutes` | `5`, `10` | Failed face checks before a temporary lock |
| `[search] min_score` | `0.3` | How closely knowledge must match a question to be used |
| `[llm] url`, `model` | empty | Optional local AI model (next section) |

### Optional: let a local AI model write the answers

By default answers are read straight from the knowledge base: fast, light, and never invented. If the computer is powerful enough, a small local AI model can phrase the answers more naturally, still fully offline:

1. Install [Ollama](https://ollama.com) and run `ollama pull qwen2.5:0.5b` (once, needs internet).
2. In `settings.ini`:
   ```ini
   [llm]
   url = http://127.0.0.1:11434/v1
   model = qwen2.5:0.5b
   ```
3. Restart. If the model is not running, the app automatically falls back to the knowledge-base answers.

Any OpenAI-compatible local server works (llamafile, LM Studio, llama.cpp server).

## Raspberry Pi notes

- Use a **Pi 4 or Pi 5** with at least 4 GB RAM and **64-bit** Raspberry Pi OS.
- Use the `linux-arm64` zip, or run `python build.py` on the Pi itself.
- Spoken answers use the system's voice. If the Pi stays silent, install a voice once: `sudo apt install speech-dispatcher espeak-ng`.
- For a kiosk, start Chromium in full screen: `chromium-browser --kiosk http://localhost:8765`.

## Using it from other devices

Browsers only allow the camera and microphone on `localhost` or HTTPS sites. To let other devices on the network use it, set `host = 0.0.0.0` and put it behind HTTPS (for example with Caddy). Without HTTPS, other devices can sign in and type questions, but voice and the face check won't work, so they can't pass the face check. The intended setup is one computer or kiosk.

## For developers

```bash
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python scripts/get_models.py          # once; add --speech en-in for the Indian English model
python run.py                         # or: python -m campus
python -m pytest                      # 35 tests
python build.py                       # makes dist/CampusAssistant-<system>-<cpu>.zip
```

PyInstaller builds for the system it runs on. To build every zip, run **Actions → Build packages → Run workflow**. Pushing a tag such as `v1.0.0` also attaches the zips to a GitHub Release.

| Folder / file | What it does |
|---|---|
| `campus/web.py` | Pages and JSON API (Flask) |
| `campus/server.py` | Starts the server (Waitress), loads models, opens the browser |
| `campus/config.py` | Paths and `settings.ini` |
| `campus/db.py` | SQLite: users, knowledge, search vectors |
| `campus/security.py` | Password hashing, lockouts, rate limits |
| `campus/face.py` | Face detection and matching (YuNet + SFace via ONNX Runtime) |
| `campus/embed.py` | Text embeddings (MiniLM) with a small built-in WordPiece tokenizer |
| `campus/search.py` | Chunking, vector search, answers (extractive or local AI) |
| `campus/speech.py` | Speech to text (Vosk) |
| `campus/ingest.py` | CSV / text file import |
| `campus/web/` | HTML, CSS, JavaScript (no framework) |
| `scripts/get_models.py` | Downloads and shrinks the models |
| `build.py` | Packages the app into a zip |

## Security notes and known limits

- **Two checks:** a password (stored as a salted scrypt hash) and then the face. 5 wrong passwords or 5 failed face checks lock that account for 10 minutes.
- **Setup is first-come.** Whoever opens a fresh install first becomes the admin. Set it up before handing the computer over.
- **One photo, no liveness check.** A good printed photo of a student could pass the face check, but the person would still need that student's password.
- **Session cookies are signed** with a random key created on first run (`data/secret.key`). Deleting that file signs everyone out.
- **Speech accuracy:** the small Vosk model handles clear questions well. Background noise and strong accents lower accuracy. Try the Indian English model (`get_models.py --speech en-in`). The text box always works.
- **Spoken answers** use the voices installed on the computer, which work offline on Windows, macOS and Android. On Linux, install `espeak-ng`.

## Model licences

YuNet (MIT) and SFace (Apache 2.0) from the OpenCV model zoo; all-MiniLM-L6-v2 (Apache 2.0); Vosk small English model (Apache 2.0). See `models/LICENSES.txt` in the zip. The test recording `tests/data/jfk.wav` is a public-domain speech excerpt.
