"""Sentence embeddings with all-MiniLM-L6-v2, run by ONNX Runtime.

An embedding is a list of 384 numbers that captures the meaning of a piece of
text. Texts with similar meaning get similar numbers, which is what lets the
assistant find "When does the library open?" in an entry titled "Library
timings" even though the words differ.

The tokenizer below is a small pure-Python version of BERT's WordPiece
tokenizer, so no extra native library is needed.
"""
import threading
import unicodedata
from functools import lru_cache

import numpy as np

from . import config

MAX_TOKENS = 256  # the model was trained on up to 256 tokens


# --- WordPiece tokenizer (lower-cased BERT) ---------------------------------------

def _is_punctuation(ch: str) -> bool:
    cp = ord(ch)
    if 33 <= cp <= 47 or 58 <= cp <= 64 or 91 <= cp <= 96 or 123 <= cp <= 126:
        return True
    return unicodedata.category(ch).startswith("P")


def _is_cjk(cp: int) -> bool:
    return (
        0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF or 0x20000 <= cp <= 0x2A6DF
        or 0x2A700 <= cp <= 0x2B73F or 0x2B740 <= cp <= 0x2B81F or 0x2B820 <= cp <= 0x2CEAF
        or 0xF900 <= cp <= 0xFAFF or 0x2F800 <= cp <= 0x2FA1F
    )


def _basic_tokens(text: str) -> list[str]:
    """Clean, lower-case, strip accents and split on spaces and punctuation."""
    out = []
    for ch in text:
        cp = ord(ch)
        if cp == 0 or cp == 0xFFFD or (unicodedata.category(ch).startswith("C") and ch not in "\t\n\r"):
            continue
        if _is_cjk(cp):
            out.append(f" {ch} ")
        elif ch.isspace():
            out.append(" ")
        else:
            out.append(ch)
    text = unicodedata.normalize("NFD", "".join(out).lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")

    tokens = []
    for word in text.split():
        current = ""
        for ch in word:
            if _is_punctuation(ch):
                if current:
                    tokens.append(current)
                    current = ""
                tokens.append(ch)
            else:
                current += ch
        if current:
            tokens.append(current)
    return tokens


class WordPiece:
    def __init__(self, vocab_path):
        words = vocab_path.read_text(encoding="utf-8").splitlines()
        self.vocab = {w: i for i, w in enumerate(words)}
        self.unk = self.vocab["[UNK]"]
        self.cls = self.vocab["[CLS]"]
        self.sep = self.vocab["[SEP]"]

    def _word_ids(self, word: str) -> list[int]:
        if len(word) > 100:
            return [self.unk]
        ids, start = [], 0
        while start < len(word):
            end = len(word)
            while end > start:
                piece = word[start:end] if start == 0 else "##" + word[start:end]
                if piece in self.vocab:
                    ids.append(self.vocab[piece])
                    break
                end -= 1
            else:
                return [self.unk]
            start = end
        return ids

    def encode(self, text: str) -> list[int]:
        ids = []
        for word in _basic_tokens(text):
            ids.extend(self._word_ids(word))
        return [self.cls] + ids[: MAX_TOKENS - 2] + [self.sep]


# --- Model ------------------------------------------------------------------------

_lock = threading.Lock()


@lru_cache(maxsize=1)
def _load():
    import onnxruntime as ort

    folder = config.MODELS_DIR / "minilm"
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = config.THREADS
    opts.log_severity_level = 3
    session = ort.InferenceSession(str(folder / "model.onnx"), opts, providers=["CPUExecutionProvider"])
    return WordPiece(folder / "vocab.txt"), session


def embed(texts: list[str]) -> np.ndarray:
    """Return one normalised 384-number vector per text (shape: len(texts) x 384)."""
    if not texts:
        return np.zeros((0, 384), dtype=np.float32)
    tokenizer, session = _load()
    encoded = [tokenizer.encode(t) for t in texts]
    width = max(len(e) for e in encoded)
    ids = np.zeros((len(encoded), width), dtype=np.int64)
    mask = np.zeros_like(ids)
    for row, e in enumerate(encoded):
        ids[row, : len(e)] = e
        mask[row, : len(e)] = 1
    with _lock:
        hidden = session.run(None, {"input_ids": ids, "attention_mask": mask, "token_type_ids": np.zeros_like(ids)})[0]
    # Average the token vectors (ignoring padding), then scale to length 1.
    summed = (hidden * mask[..., None]).sum(axis=1)
    vectors = summed / np.maximum(mask.sum(axis=1, keepdims=True), 1)
    vectors /= np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)
    return vectors.astype(np.float32)
