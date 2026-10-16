"""Face check with one reference photo per user.

Uses two small models from the OpenCV model zoo, run directly with ONNX
Runtime (the full OpenCV library is not needed, which keeps the app small):

  * YuNet finds faces and 5 landmarks (eyes, nose tip, mouth corners).
  * SFace turns a face into 128 numbers (an "embedding").

Two photos of the same person give embeddings pointing in nearly the same
direction, so they are compared with cosine similarity. Nothing is trained,
which is why one registered photo is enough.

The browser sends raw RGB pixels (it already decoded and resized the image),
so the server needs no image-decoding library either.
"""
import threading
from functools import lru_cache

import numpy as np

from . import config

DETECTOR_FILE = "face_detection_yunet_2023mar.onnx"
RECOGNIZER_FILE = "face_recognition_sface_2021dec_int8.onnx"

DETECT_SIZE = 640
SCORE_THRESHOLD = 0.8
NMS_THRESHOLD = 0.3
MIN_FACE_PX = 60
MAX_SIDE = 1280

# Where SFace expects the 5 landmarks to be in its 112 x 112 input.
SFACE_LANDMARKS = np.array(
    [[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366], [41.5493, 92.3655], [70.7299, 92.2041]],
    dtype=np.float64,
)

_lock = threading.Lock()


class FaceError(Exception):
    """A problem with the photo the user can fix (no face, two faces, ...)."""


@lru_cache(maxsize=1)
def _sessions():
    import onnxruntime as ort

    opts = ort.SessionOptions()
    opts.intra_op_num_threads = config.THREADS
    opts.log_severity_level = 3  # hide harmless model-format warnings
    load = lambda name: ort.InferenceSession(  # noqa: E731
        str(config.MODELS_DIR / "face" / name), opts, providers=["CPUExecutionProvider"]
    )
    return load(DETECTOR_FILE), load(RECOGNIZER_FILE)


def pixels_to_image(data: bytes, width: int, height: int) -> np.ndarray:
    """Turn raw RGB bytes from the browser into an H x W x 3 array."""
    if not (32 <= width <= MAX_SIDE and 32 <= height <= MAX_SIDE):
        raise FaceError("The picture size is not supported.")
    if len(data) != width * height * 3:
        raise FaceError("The picture data is incomplete. Please try again.")
    return np.frombuffer(data, dtype=np.uint8).reshape(height, width, 3)


# --- Detection (YuNet) ---------------------------------------------------------

def _nms(boxes: np.ndarray, scores: np.ndarray) -> list[int]:
    order = scores.argsort()[::-1]
    keep = []
    while order.size:
        i = order[0]
        keep.append(int(i))
        x1 = np.maximum(boxes[i, 0], boxes[order[1:], 0])
        y1 = np.maximum(boxes[i, 1], boxes[order[1:], 1])
        x2 = np.minimum(boxes[i, 0] + boxes[i, 2], boxes[order[1:], 0] + boxes[order[1:], 2])
        y2 = np.minimum(boxes[i, 1] + boxes[i, 3], boxes[order[1:], 1] + boxes[order[1:], 3])
        inter = np.maximum(0, x2 - x1) * np.maximum(0, y2 - y1)
        union = boxes[i, 2] * boxes[i, 3] + boxes[order[1:], 2] * boxes[order[1:], 3] - inter
        order = order[1:][inter / np.maximum(union, 1e-9) <= NMS_THRESHOLD]
    return keep


def detect(rgb: np.ndarray) -> np.ndarray:
    """Return one row per face: x, y, w, h, 5 landmark (x, y) pairs, score."""
    detector, _ = _sessions()
    # The model takes a fixed 640 x 640 picture: shrink if needed, pad the rest.
    h, w = rgb.shape[:2]
    scale = min(1.0, DETECT_SIZE / max(h, w))
    small = rgb if scale == 1.0 else _warp(rgb, np.array([[scale, 0, 0], [0, scale, 0]]), round(w * scale), round(h * scale))
    blob = np.zeros((1, 3, DETECT_SIZE, DETECT_SIZE), dtype=np.float32)
    blob[0, :, : small.shape[0], : small.shape[1]] = small[:, :, ::-1].transpose(2, 0, 1)  # BGR, 0-255
    with _lock:
        outputs = dict(zip([o.name for o in detector.get_outputs()], detector.run(None, {"input": blob})))

    faces = []
    for stride in (8, 16, 32):
        cols = DETECT_SIZE // stride
        cls = outputs[f"cls_{stride}"].reshape(-1)
        obj = outputs[f"obj_{stride}"].reshape(-1)
        score = np.sqrt(np.clip(cls, 0, 1) * np.clip(obj, 0, 1))
        idx = np.nonzero(score >= SCORE_THRESHOLD)[0]
        if not idx.size:
            continue
        bbox = outputs[f"bbox_{stride}"].reshape(-1, 4)[idx]
        kps = outputs[f"kps_{stride}"].reshape(-1, 10)[idx]
        c, r = (idx % cols).astype(np.float32), (idx // cols).astype(np.float32)
        cx, cy = (c + bbox[:, 0]) * stride, (r + bbox[:, 1]) * stride
        bw, bh = np.exp(bbox[:, 2]) * stride, np.exp(bbox[:, 3]) * stride
        marks = np.empty_like(kps)
        marks[:, 0::2] = (kps[:, 0::2] + c[:, None]) * stride
        marks[:, 1::2] = (kps[:, 1::2] + r[:, None]) * stride
        faces.append(np.column_stack([cx - bw / 2, cy - bh / 2, bw, bh, marks, score[idx]]))

    if not faces:
        return np.zeros((0, 15), dtype=np.float32)
    faces = np.concatenate(faces)
    faces = faces[_nms(faces[:, :4], faces[:, 14])]
    faces[:, :14] /= scale  # back to the original picture's coordinates
    return faces


# --- Alignment + recognition (SFace) ----------------------------------------------

def _similarity_transform(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """2 x 3 matrix (rotation + uniform scale + shift) that best maps src points to dst."""
    src_mean, dst_mean = src.mean(0), dst.mean(0)
    src_c, dst_c = src - src_mean, dst - dst_mean
    u, s, vt = np.linalg.svd(dst_c.T @ src_c / len(src))
    d = np.ones(2)
    if np.linalg.det(u) * np.linalg.det(vt) < 0:
        d[-1] = -1
    rot = u @ np.diag(d) @ vt
    scale = (s * d).sum() / src_c.var(0).sum()
    m = np.zeros((2, 3))
    m[:, :2] = scale * rot
    m[:, 2] = dst_mean - scale * rot @ src_mean
    return m


def _warp(rgb: np.ndarray, m: np.ndarray, out_w: int = 112, out_h: int = 112) -> np.ndarray:
    """Apply a 2 x 3 affine matrix (bilinear sampling): used to cut out and to resize."""
    inv = np.linalg.inv(np.vstack([m, [0, 0, 1]]))[:2]
    ys, xs = np.mgrid[0:out_h, 0:out_w].astype(np.float64)
    sx = inv[0, 0] * xs + inv[0, 1] * ys + inv[0, 2]
    sy = inv[1, 0] * xs + inv[1, 1] * ys + inv[1, 2]
    x0, y0 = np.floor(sx).astype(int), np.floor(sy).astype(int)
    fx, fy = (sx - x0)[..., None], (sy - y0)[..., None]
    h, w = rgb.shape[:2]
    img = rgb.astype(np.float32)

    def px(y, x):
        inside = ((x >= 0) & (x < w) & (y >= 0) & (y < h))[..., None]
        return img[np.clip(y, 0, h - 1), np.clip(x, 0, w - 1)] * inside

    top = px(y0, x0) * (1 - fx) + px(y0, x0 + 1) * fx
    bottom = px(y0 + 1, x0) * (1 - fx) + px(y0 + 1, x0 + 1) * fx
    return top * (1 - fy) + bottom * fy


def embedding(rgb: np.ndarray) -> np.ndarray:
    """Find exactly one face and return its 128-number embedding."""
    faces = detect(rgb)
    if len(faces) == 0:
        raise FaceError("No face found. Look at the camera in good light.")
    if len(faces) > 1:
        raise FaceError("More than one face found. Only one person should be in the picture.")
    face = faces[0]
    if min(face[2], face[3]) < MIN_FACE_PX:
        raise FaceError("Your face is too small in the picture. Move closer to the camera.")

    aligned = _warp(rgb, _similarity_transform(face[4:14].reshape(5, 2).astype(np.float64), SFACE_LANDMARKS))
    blob = aligned.round().clip(0, 255).transpose(2, 0, 1)[None].astype(np.float32)  # RGB, 0-255
    _, recognizer = _sessions()
    with _lock:
        feature = recognizer.run(None, {recognizer.get_inputs()[0].name: blob})[0]
    return feature.reshape(-1).astype(np.float32)


def similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def is_match(a: np.ndarray, b: np.ndarray) -> tuple[bool, float]:
    score = similarity(a, b)
    return score >= config.FACE_MATCH_THRESHOLD, score


def to_bytes(vec: np.ndarray) -> bytes:
    return vec.astype(np.float32).tobytes()


def from_bytes(data: bytes) -> np.ndarray:
    return np.frombuffer(data, dtype=np.float32)
