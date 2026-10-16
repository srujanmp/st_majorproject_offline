"""Where things live and the settings from settings.ini.

Everything sits next to the program, so the whole folder can be copied to a
USB stick or another computer and keeps working:

    CampusAssistant/
        CampusAssistant(.exe)   the program
        settings.ini            created on first run, safe to edit
        models/                 the AI models (speech, search, face)
        data/                   your database (users, knowledge)
"""
import configparser
import os
import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)  # True inside the packaged app
APP_DIR = Path(os.getenv("CAMPUS_HOME") or (Path(sys.executable).parent if FROZEN else Path(__file__).resolve().parent.parent))
MODELS_DIR = Path(os.getenv("CAMPUS_MODELS") or APP_DIR / "models")
DATA_DIR = Path(os.getenv("CAMPUS_DATA") or APP_DIR / "data")
SETTINGS_FILE = Path(os.getenv("CAMPUS_SETTINGS") or APP_DIR / "settings.ini")
WEB_DIR = Path(__file__).resolve().parent / "web"

DEFAULT_SETTINGS = """\
# Campus Assistant settings. Restart the app after changing this file.

[server]
# 127.0.0.1 means only this computer can open the app. Camera and microphone
# only work on this computer anyway (browsers block them on plain http from
# other devices).
host = 127.0.0.1
port = 8765
open_browser = yes

[face]
# How similar the live face must be to the registered photo (0 to 1).
# Higher is stricter. 0.363 is the value recommended for the SFace model.
match_threshold = 0.363
max_failures = 5
lock_minutes = 10

[search]
# How many knowledge pieces to look at, and how similar (0 to 1) a piece must
# be to the question to be used at all.
top_k = 3
min_score = 0.3

[llm]
# Optional. Leave url empty to answer straight from the knowledge base
# (fast, light, never makes things up).
# To have a local AI model write the answers instead, run Ollama or llamafile
# on this computer and fill these in, for example:
#   url = http://127.0.0.1:11434/v1
#   model = qwen2.5:0.5b
url =
model =
timeout_seconds = 60

[performance]
# CPU threads used by the AI models. 0 = choose automatically.
threads = 0
"""


def _load() -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    parser.read_string(DEFAULT_SETTINGS)
    if SETTINGS_FILE.exists():
        parser.read(SETTINGS_FILE, encoding="utf-8")
    else:
        try:
            SETTINGS_FILE.write_text(DEFAULT_SETTINGS, encoding="utf-8")
        except OSError:
            pass  # read-only folder: defaults still apply
    return parser


_s = _load()

HOST = _s.get("server", "host")
PORT = _s.getint("server", "port")
OPEN_BROWSER = _s.getboolean("server", "open_browser")

FACE_MATCH_THRESHOLD = _s.getfloat("face", "match_threshold")
FACE_MAX_FAILURES = _s.getint("face", "max_failures")
FACE_LOCK_MINUTES = _s.getint("face", "lock_minutes")

TOP_K = _s.getint("search", "top_k")
MIN_SCORE = _s.getfloat("search", "min_score")

LLM_URL = _s.get("llm", "url").strip().rstrip("/")
LLM_MODEL = _s.get("llm", "model").strip()
LLM_TIMEOUT = _s.getint("llm", "timeout_seconds")

THREADS = _s.getint("performance", "threads") or max(1, min(4, os.cpu_count() or 1))

DATA_DIR.mkdir(parents=True, exist_ok=True)
