"""Start the app: check models, prepare the database, serve, open the browser."""
import logging
import sys
import threading
import time
import webbrowser

from . import __version__, config, db

log = logging.getLogger("campus")

REQUIRED_MODELS = {
    "speech (Vosk)": config.MODELS_DIR / "vosk" / "am",
    "search (MiniLM)": config.MODELS_DIR / "minilm" / "model.onnx",
    "face detector (YuNet)": config.MODELS_DIR / "face" / "face_detection_yunet_2023mar.onnx",
    "face recogniser (SFace)": config.MODELS_DIR / "face" / "face_recognition_sface_2021dec_int8.onnx",
}


def _warm_up() -> None:
    """Load the models in the background so the first question is quick."""
    from . import embed, face, speech

    started = time.time()
    for name, load in (("search", lambda: embed.embed(["warm up"])), ("face", face._sessions), ("speech", speech._model)):
        try:
            load()
        except Exception as e:
            log.warning("Could not load the %s model: %s", name, e)
    log.info("Models ready in %.1f s", time.time() - started)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("waitress").setLevel(logging.WARNING)

    missing = [name for name, path in REQUIRED_MODELS.items() if not path.exists()]
    for name in missing:
        log.warning("Missing model: %s (looked in %s)", name, config.MODELS_DIR)
    if missing:
        log.warning("Run `python scripts/get_models.py` once (needs internet), or use the packaged zip.")

    db.init()
    from waitress import serve

    from .web import app

    threading.Thread(target=_warm_up, daemon=True).start()

    browser_host = "localhost" if config.HOST in ("127.0.0.1", "0.0.0.0", "::") else config.HOST
    url = f"http://{browser_host}:{config.PORT}"
    print(
        f"\n  Campus Assistant {__version__} (offline)\n"
        f"  Open {url} in Chrome, Edge or Firefox.\n"
        f"  Data folder: {config.DATA_DIR}\n"
        f"  Close this window (or press Ctrl+C) to stop.\n",
        flush=True,
    )
    if config.OPEN_BROWSER:
        threading.Timer(1.5, webbrowser.open, [url]).start()
    try:
        serve(app, host=config.HOST, port=config.PORT, threads=8)
    except OSError as e:
        log.error("Could not start on port %s: %s. Is the app already running? "
                  "You can change the port in settings.ini.", config.PORT, e)
        sys.exit(1)
