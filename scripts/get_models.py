"""Download the AI models once. This is the only step that needs internet.

    python scripts/get_models.py                # US English speech model (default)
    python scripts/get_models.py --speech en-in # Indian English speech model

Puts everything in ./models (about 110 MB):
    models/face/    YuNet face detector + SFace face recogniser (OpenCV model zoo)
    models/minilm/  all-MiniLM-L6-v2 sentence embeddings, shrunk to 8-bit (~23 MB)
    models/vosk/    Vosk small English speech recogniser
"""
import argparse
import hashlib
import io
import shutil
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"

ZOO = "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models"
FACE_FILES = {
    "face_detection_yunet_2023mar.onnx": (
        f"{ZOO}/face_detection_yunet/face_detection_yunet_2023mar.onnx",
        "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    ),
    "face_recognition_sface_2021dec_int8.onnx": (
        f"{ZOO}/face_recognition_sface/face_recognition_sface_2021dec_int8.onnx",
        "2b0e941e6f16cc048c20aee0c8e31f569118f65d702914540f7bfdc14048d78a",
    ),
}
MINILM = (
    "https://chroma-onnx-models.s3.amazonaws.com/all-MiniLM-L6-v2/onnx.tar.gz",
    "913d7300ceae3b2dbc2c50d1de4baacab4be7b9380491c27fab7418616a16ec3",
)
VOSK = {
    "en-us": "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip",
    "en-in": "https://alphacephei.com/vosk/models/vosk-model-small-en-in-0.4.zip",
}
# The same US English small model, file by file, in case alphacephei.com is unreachable.
VOSK_EN_US_MIRROR = "https://raw.githubusercontent.com/alphacep/vosk-android-demo/master/models/src/main/assets/model-en-us"
VOSK_EN_US_FILES = [
    "README", "am/final.mdl", "conf/mfcc.conf", "conf/model.conf", "graph/disambig_tid.int", "graph/Gr.fst",
    "graph/HCLr.fst", "graph/phones/word_boundary.int", "ivector/final.dubm", "ivector/final.ie",
    "ivector/final.mat", "ivector/global_cmvn.stats", "ivector/online_cmvn.conf", "ivector/splice.conf",
]

LICENSES = """\
Models included with Campus Assistant
-------------------------------------
face/face_detection_yunet_2023mar.onnx       YuNet, OpenCV model zoo, MIT licence
face/face_recognition_sface_2021dec_int8.onnx SFace, OpenCV model zoo, Apache 2.0 licence
minilm/                                      sentence-transformers/all-MiniLM-L6-v2, Apache 2.0 licence
                                             (converted to 8-bit with ONNX Runtime)
vosk/                                        Vosk small English model, Alpha Cephei, Apache 2.0 licence
"""


def fetch(url: str, sha256: str | None = None) -> bytes:
    print(f"  downloading {url.rsplit('/', 1)[-1]} ...", flush=True)
    with urllib.request.urlopen(url, timeout=120) as response:
        data = response.read()
    if sha256 and hashlib.sha256(data).hexdigest() != sha256:
        raise RuntimeError(f"Checksum mismatch for {url}")
    return data


def get_face() -> None:
    folder = MODELS / "face"
    folder.mkdir(parents=True, exist_ok=True)
    for name, (url, sha) in FACE_FILES.items():
        if not (folder / name).exists():
            (folder / name).write_bytes(fetch(url, sha))


def get_minilm() -> None:
    folder = MODELS / "minilm"
    if (folder / "model.onnx").exists():
        return
    folder.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(fetch(*MINILM))) as tar, tempfile.TemporaryDirectory() as tmp:
        for member in ("onnx/model.onnx", "onnx/vocab.txt"):
            tar.extract(member, tmp, filter="data")
        shutil.copy(Path(tmp) / "onnx" / "vocab.txt", folder / "vocab.txt")
        try:
            from onnxruntime.quantization import QuantType, quantize_dynamic

            print("  shrinking the search model to 8-bit (90 MB -> 23 MB) ...", flush=True)
            quantize_dynamic(Path(tmp) / "onnx" / "model.onnx", folder / "model.onnx", weight_type=QuantType.QInt8)
        except ImportError:
            print("  (install `onnx` to shrink this model; keeping the full 90 MB version)")
            shutil.copy(Path(tmp) / "onnx" / "model.onnx", folder / "model.onnx")


def get_vosk(language: str) -> None:
    folder = MODELS / "vosk"
    if (folder / "am").exists():
        return
    try:
        archive = zipfile.ZipFile(io.BytesIO(fetch(VOSK[language])))
        with tempfile.TemporaryDirectory() as tmp:
            archive.extractall(tmp)
            (inner,) = [p for p in Path(tmp).iterdir() if p.is_dir()]
            shutil.move(str(inner), str(folder))
    except Exception as e:
        if language != "en-us":
            raise
        print(f"  alphacephei.com failed ({e}); using the GitHub copy of the same model")
        for name in VOSK_EN_US_FILES:
            target = folder / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(fetch(f"{VOSK_EN_US_MIRROR}/{name}"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--speech", choices=sorted(VOSK), default="en-us", help="speech model language")
    args = parser.parse_args()

    print("Face models")
    get_face()
    print("Search model")
    get_minilm()
    print("Speech model")
    get_vosk(args.speech)
    (MODELS / "LICENSES.txt").write_text(LICENSES, encoding="utf-8")

    size = sum(f.stat().st_size for f in MODELS.rglob("*") if f.is_file()) / 1e6
    print(f"Done. {size:.0f} MB in {MODELS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
