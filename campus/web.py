"""The web app: pages and JSON API (Flask)."""
import logging
import sqlite3
from datetime import timedelta
from functools import wraps
from urllib.parse import urlparse

from flask import Flask, jsonify, redirect, request, send_from_directory, session

from . import config, db, face, ingest, search, security, speech

log = logging.getLogger(__name__)

PAGES = config.WEB_DIR / "pages"
ROLES = ("admin", "student")

app = Flask(__name__, static_folder=str(config.WEB_DIR / "static"), static_url_path="/static")
app.secret_key = security.load_secret_key()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    MAX_CONTENT_LENGTH=8 * 1024 * 1024,
)


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


@app.errorhandler(ApiError)
def _api_error(e: ApiError):
    return jsonify(error=e.message), e.status


@app.errorhandler(413)
def _too_big(_e):
    return jsonify(error="That file is too big (limit 8 MB)."), 413


@app.errorhandler(Exception)
def _unexpected(e):
    if hasattr(e, "code") and hasattr(e, "description"):  # normal HTTP errors such as 404
        return jsonify(error=e.description), e.code
    log.exception("Unexpected error")
    return jsonify(error="Something went wrong on the server. Please try again."), 500


@app.before_request
def _block_cross_site():
    # Only pages from this app may change things (CSRF protection).
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("Origin")
        if origin and urlparse(origin).netloc != request.host:
            raise ApiError(403, "Cross-site request blocked.")


@app.after_request
def _headers(response):
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(self), microphone=(self)"
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


# --- Who is signed in --------------------------------------------------------------

def current_user() -> dict | None:
    user_id = session.get("uid")
    if not user_id:
        return None
    user = db.get_user(user_id)
    if not user:  # deleted while signed in
        session.clear()
    return user


def needs(level: str):
    """Decorator: 'signed_in', 'verified' (password + face) or 'admin'."""

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            user = current_user()
            if not user:
                raise ApiError(401, "Please sign in.")
            if level in ("verified", "admin") and not session.get("face_ok"):
                raise ApiError(403, "Face check required.")
            if level == "admin" and user["role"] != "admin":
                raise ApiError(403, "Admins only.")
            return view(user, *args, **kwargs)

        return wrapper

    return decorator


def body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError(400, "Expected a JSON body.")
    return data


def text_field(data: dict, name: str, label: str, max_len: int, required: bool = True) -> str:
    value = data.get(name, "")
    value = value.strip() if isinstance(value, str) else ""
    if required and not value:
        raise ApiError(422, f"{label} is required.")
    if len(value) > max_len:
        raise ApiError(422, f"{label} is too long (max {max_len} characters).")
    return value


def check_password_rules(password: str) -> None:
    if not isinstance(password, str) or len(password) < 6:
        raise ApiError(422, "Password must be at least 6 characters.")
    if len(password) > 200:
        raise ApiError(422, "Password is too long.")


def face_from_request():
    """Face embedding from the raw RGB pixels the browser sent (size in headers)."""
    try:
        width, height = int(request.headers["X-Width"]), int(request.headers["X-Height"])
        rgb = face.pixels_to_image(request.get_data(), width, height)
        return face.embedding(rgb)
    except (KeyError, ValueError):
        raise ApiError(400, "The picture was not sent correctly. Please try again.")
    except face.FaceError as e:
        raise ApiError(400, str(e))


# --- Pages ---------------------------------------------------------------------------

def page(name: str):
    response = send_from_directory(PAGES, name)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/")
def home():
    if db.count_users() == 0:
        return redirect("/setup")
    user = current_user()
    if not user:
        return page("login.html")
    if not session.get("face_ok"):
        return redirect("/face")
    return page("chat.html")


@app.get("/setup")
def setup_page():
    return page("setup.html") if db.count_users() == 0 else redirect("/")


@app.get("/face")
def face_page():
    if not current_user():
        return redirect("/")
    return redirect("/") if session.get("face_ok") else page("face.html")


@app.get("/admin")
def admin_page():
    user = current_user()
    if not user or not session.get("face_ok") or user["role"] != "admin":
        return redirect("/")
    return page("admin.html")


@app.get("/logout")
def logout():
    session.clear()
    return redirect("/")


@app.get("/favicon.ico")
def favicon():
    return send_from_directory(app.static_folder, "favicon.svg", mimetype="image/svg+xml")


# --- Setup, sign-in and face check ---------------------------------------------------------

@app.get("/api/status")
def status():
    models = config.MODELS_DIR
    return jsonify(
        setup_needed=db.count_users() == 0,
        models={
            "speech": (models / "vosk" / "am").exists(),
            "search": (models / "minilm" / "model.onnx").exists(),
            "face": (models / "face" / face.RECOGNIZER_FILE).exists(),
        },
        answers="local AI model" if config.LLM_URL else "knowledge base",
    )


@app.post("/api/setup")
def setup():
    data = body()
    login = text_field(data, "login", "ID", 64)
    name = text_field(data, "name", "Name", 100)
    password = data.get("password", "")
    check_password_rules(password)
    user_id = db.create_first_admin(login, name, security.hash_password(password))
    if not user_id:
        raise ApiError(409, "Setup has already been done. Please sign in.")
    session.clear()
    session.permanent = True
    session.update(uid=user_id, face_ok=False, may_enroll=True)
    log.info("First admin %s created", login)
    return jsonify(ok=True)


@app.post("/api/login")
def login():
    data = body()
    login_id = text_field(data, "login", "ID", 64).lower()
    password = data.get("password", "") if isinstance(data.get("password"), str) else ""
    wait = security.login_lockout.seconds_left(login_id)
    if wait:
        raise ApiError(429, f"Too many failed sign-ins. Try again in {wait // 60 + 1} minutes.")

    row = db.get_login(login_id)
    ok = security.verify_password(password, row["password_hash"] if row else security.DUMMY_HASH)
    if not (row and ok):
        security.login_lockout.fail(login_id)
        raise ApiError(401, "Wrong ID or password.")

    security.login_lockout.reset(login_id)
    session.clear()
    session.permanent = True
    session.update(uid=row["id"], face_ok=False)
    return jsonify(ok=True)


@app.get("/api/me")
@needs("signed_in")
def me(user):
    return jsonify(
        login=user["login"],
        name=user["name"],
        role=user["role"],
        face_ok=bool(session.get("face_ok")),
        face_enrolled=bool(user["has_face"]),
        may_enroll=bool(session.get("may_enroll")) and not user["has_face"],
    )


@app.post("/api/face/verify")
@needs("signed_in")
def verify_face(user):
    key = user["login"].lower()
    wait = security.face_lockout.seconds_left(key)
    if wait:
        raise ApiError(429, f"Too many failed face checks. Try again in {wait // 60 + 1} minutes.")
    stored = db.get_face(user["id"])
    if stored is None:
        raise ApiError(404, "Your face is not registered yet. Ask an admin to add your photo.")

    live = face_from_request()  # a blurry or empty frame doesn't count as a failed try
    ok, score = face.is_match(live, face.from_bytes(stored))
    log.info("Face check for %s: score=%.3f match=%s", user["login"], score, ok)
    if not ok:
        security.face_lockout.fail(key)
        raise ApiError(403, f"Face did not match. {security.face_lockout.tries_left(key)} tries left.")
    security.face_lockout.reset(key)
    session["face_ok"] = True
    return jsonify(ok=True)


@app.post("/api/face/enroll")
@needs("signed_in")
def enroll_own_face(user):
    """Only the first admin, right after setup, registers their own face here."""
    if not session.get("may_enroll") or user["has_face"]:
        raise ApiError(403, "Ask an admin to register your face.")
    vec = face_from_request()
    db.set_face(user["id"], face.to_bytes(vec))
    session.pop("may_enroll", None)
    session["face_ok"] = True
    return jsonify(ok=True)


# --- Voice and questions -------------------------------------------------------------------

@app.post("/api/transcribe")
@needs("verified")
def transcribe(user):
    if not security.voice_limit.allow(f"stt:{user['id']}"):
        raise ApiError(429, "You're going very fast. Wait a minute and try again.")
    try:
        text = speech.transcribe(request.get_data())
    except speech.SpeechError as e:
        raise ApiError(400, str(e))
    return jsonify(text=text)


@app.post("/api/ask")
@needs("verified")
def ask(user):
    question = text_field(body(), "question", "Question", 500)
    if not security.voice_limit.allow(f"ask:{user['id']}"):
        raise ApiError(429, "You're asking very fast. Wait a minute and try again.")
    return jsonify(search.answer(question))


# --- Admin: knowledge ---------------------------------------------------------------------

@app.get("/api/admin/modules")
@needs("admin")
def list_modules(_user):
    return jsonify(db.list_modules())


def _module_fields() -> tuple[str, str]:
    data = body()
    return text_field(data, "title", "Title", 200), text_field(data, "content", "Content", 20000)


@app.post("/api/admin/modules")
@needs("admin")
def create_module(user):
    title, content = _module_fields()
    module = db.create_module(title, content, "manual", user["login"])
    search.index_module(module)
    return jsonify(module), 201


@app.put("/api/admin/modules/<int:module_id>")
@needs("admin")
def update_module(user, module_id):
    title, content = _module_fields()
    module = db.update_module(module_id, title, content, user["login"])
    if not module:
        raise ApiError(404, "Entry not found.")
    search.index_module(module)
    return jsonify(module)


@app.delete("/api/admin/modules/<int:module_id>")
@needs("admin")
def delete_module(_user, module_id):
    if not db.delete_module(module_id):
        raise ApiError(404, "Entry not found.")
    search.refresh()
    return "", 204


@app.post("/api/admin/modules/import")
@needs("admin")
def import_file(user):
    upload = request.files.get("file")
    if not upload:
        raise ApiError(400, "Choose a file to import.")
    try:
        entries = ingest.parse_file(upload.read(), upload.filename or "")
    except ingest.IngestError as e:
        raise ApiError(400, str(e))
    source = "csv" if (upload.filename or "").lower().endswith(".csv") else "file"
    for entry in entries:
        search.index_module(db.create_module(entry["title"], entry["content"], source, user["login"]))
    return jsonify(added=len(entries)), 201


@app.post("/api/admin/reindex")
@needs("admin")
def reindex(_user):
    return jsonify(chunks=search.rebuild())


# --- Admin: users ----------------------------------------------------------------------

@app.get("/api/admin/users")
@needs("admin")
def list_users(_user):
    return jsonify(db.list_users())


@app.post("/api/admin/users")
@needs("admin")
def create_user(_user):
    data = body()
    login_id = text_field(data, "login", "ID", 64)
    name = text_field(data, "name", "Name", 100)
    role = data.get("role")
    if role not in ROLES:
        raise ApiError(422, "Role must be admin or student.")
    check_password_rules(data.get("password", ""))
    try:
        user = db.create_user(login_id, name, role, security.hash_password(data["password"]))
    except sqlite3.IntegrityError:
        raise ApiError(409, "A user with that ID already exists.")
    return jsonify(user), 201


def _target(user_id: int) -> dict:
    target = db.get_user(user_id)
    if not target:
        raise ApiError(404, "User not found.")
    return target


@app.put("/api/admin/users/<int:user_id>")
@needs("admin")
def update_user(user, user_id):
    target = _target(user_id)
    data = body()
    name = text_field(data, "name", "Name", 100)
    role = data.get("role")
    if role not in ROLES:
        raise ApiError(422, "Role must be admin or student.")
    if target["role"] == "admin" and role != "admin" and db.count_admins() == 1:
        raise ApiError(409, "There must be at least one admin.")
    db.update_user(user_id, name, role)
    if data.get("password"):
        check_password_rules(data["password"])
        db.set_password(user_id, security.hash_password(data["password"]))
    return jsonify(db.get_user(user_id))


@app.delete("/api/admin/users/<int:user_id>")
@needs("admin")
def delete_user(user, user_id):
    target = _target(user_id)
    if target["id"] == user["id"]:
        raise ApiError(409, "You can't delete your own account.")
    if target["role"] == "admin" and db.count_admins() == 1:
        raise ApiError(409, "There must be at least one admin.")
    db.delete_user(user_id)
    return "", 204


@app.post("/api/admin/users/<int:user_id>/face")
@needs("admin")
def register_face(_user, user_id):
    _target(user_id)
    db.set_face(user_id, face.to_bytes(face_from_request()))
    return jsonify(db.get_user(user_id))


@app.delete("/api/admin/users/<int:user_id>/face")
@needs("admin")
def remove_face(_user, user_id):
    _target(user_id)
    db.set_face(user_id, None)
    return "", 204
