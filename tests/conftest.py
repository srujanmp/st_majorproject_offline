import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_tmp = Path(tempfile.mkdtemp(prefix="campus-test-"))
os.environ.update(
    CAMPUS_DATA=str(_tmp / "data"),
    CAMPUS_SETTINGS=str(_tmp / "settings.ini"),
    CAMPUS_MODELS=os.environ.get("CAMPUS_MODELS", str(ROOT / "models")),
)
sys.path.insert(0, str(ROOT))

from campus import config, db, search, security  # noqa: E402
from campus.web import app  # noqa: E402

HAVE_SEARCH_MODEL = (config.MODELS_DIR / "minilm" / "model.onnx").exists()
HAVE_FACE_MODELS = (config.MODELS_DIR / "face" / "face_recognition_sface_2021dec_int8.onnx").exists()
HAVE_SPEECH_MODEL = (config.MODELS_DIR / "vosk" / "am").exists()

needs_search = pytest.mark.skipif(not HAVE_SEARCH_MODEL, reason="run scripts/get_models.py first")
needs_face = pytest.mark.skipif(not HAVE_FACE_MODELS, reason="run scripts/get_models.py first")
needs_speech = pytest.mark.skipif(not HAVE_SPEECH_MODEL, reason="run scripts/get_models.py first")


@pytest.fixture
def client():
    db.init()
    with db.connect() as conn:
        for table in ("chunks", "modules", "users"):
            conn.execute(f"DELETE FROM {table}")
    search.refresh()
    for limiter in (security.login_lockout, security.face_lockout):
        limiter._fails.clear()
    security.voice_limit._hits.clear()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def make_user(login="student1", role="student", password="secret123", name="Test Student"):
    return db.create_user(login, name, role, security.hash_password(password))


def sign_in(client, user, face_ok=True):
    """Pretend the user has signed in (and passed the face check)."""
    with client.session_transaction() as s:
        s["uid"] = user["id"]
        s["face_ok"] = face_ok
