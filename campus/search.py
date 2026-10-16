"""Retrieval-Augmented answers, fully offline.

1. Index:  each knowledge entry is split into chunks; each chunk's embedding
           (see embed.py) is saved in the database.
2. Search: the question is embedded the same way and compared with every
           chunk (cosine similarity, one numpy matrix product). The closest
           chunks above a minimum score are the "retrieved" knowledge.
3. Answer: by default the best-matching sentences are read back directly,
           so answers are instant and never invented. If a local AI model is
           configured in settings.ini ([llm]), it writes the answer instead,
           using only the retrieved chunks.
"""
import json
import logging
import re
import threading
import urllib.request

import numpy as np

from . import config, db
from .embed import embed

log = logging.getLogger(__name__)

CHUNK_SIZE = 500
CHUNK_OVERLAP = 80
SHORT_ANSWER = 280          # chunks shorter than this are read out whole
NO_ANSWER = "I don't have any information on that yet. Please check with the college office."

SYSTEM_PROMPT = """You are the NMAMIT campus voice assistant. Your reply is read aloud.
Answer ONLY from the context. If the context does not contain the answer, say you don't have that information yet.
At most 3 short sentences. Plain spoken English: no markdown, lists, emojis or URLs. Never invent dates, fees or names."""

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n+")


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping pieces, preferring to cut at a line or sentence end."""
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    chunks, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            cut = max(text.rfind("\n", start, end), text.rfind(". ", start, end))
            if cut > start + size // 2:
                end = cut + 1
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = end - overlap
    return [c for c in chunks if c]


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_END.split(text) if len(s.strip()) > 2]


# --- The index ------------------------------------------------------------------
# All chunk vectors are kept in one numpy matrix in memory. Any change to the
# knowledge marks it stale, and the next search reloads it from the database,
# so answers always use the latest information.

class _Index:
    def __init__(self):
        self.lock = threading.Lock()
        self.stale = True
        self.rows: list[dict] = []
        self.matrix = np.zeros((0, 384), dtype=np.float32)

    def get(self):
        with self.lock:
            if self.stale:
                self.rows = db.all_chunks()
                self.matrix = (
                    np.stack([np.frombuffer(r["vector"], dtype=np.float32) for r in self.rows])
                    if self.rows else np.zeros((0, 384), dtype=np.float32)
                )
                self.stale = False
            return self.rows, self.matrix

    def invalidate(self):
        with self.lock:
            self.stale = True


_index = _Index()


def index_module(module: dict) -> None:
    pieces = chunk_text(module["content"])
    vectors = embed([f"{module['title']}. {p}" for p in pieces])
    db.replace_chunks(module["id"], [(i, p, v.tobytes()) for i, (p, v) in enumerate(zip(pieces, vectors))])
    _index.invalidate()


def refresh() -> None:
    """Call after deleting entries (the database removes their chunks itself)."""
    _index.invalidate()


def rebuild() -> int:
    count = 0
    for module in db.list_modules():
        index_module(module)
        count += len(chunk_text(module["content"]))
    return count


def search(question: str, k: int | None = None) -> list[dict]:
    rows, matrix = _index.get()
    if not rows:
        return []
    scores = matrix @ embed([question])[0]
    best = np.argsort(-scores)[: k or config.TOP_K]
    return [
        {"module_id": rows[i]["module_id"], "title": rows[i]["title"], "text": rows[i]["text"], "score": float(scores[i])}
        for i in best
        if scores[i] >= config.MIN_SCORE
    ]


# --- Answers -----------------------------------------------------------------------

def extract_answer(question: str, hits: list[dict]) -> tuple[str, list[str]]:
    """Read back the sentences that best match the question; also return where they came from."""
    best = hits[0]
    if len(best["text"]) <= SHORT_ANSWER:
        return best["text"], [best["title"]]

    candidates = [(h_i, s_i, s) for h_i, h in enumerate(hits[:2]) for s_i, s in enumerate(sentences(h["text"]))]
    scores = embed([s for _, _, s in candidates]) @ embed([question])[0]
    order = np.argsort(-scores)
    picked = [order[0]]
    for i in order[1:]:
        if scores[i] < scores[order[0]] - 0.08 or len(picked) == 2:
            break
        if sum(len(candidates[p][2]) for p in picked) + len(candidates[i][2]) <= SHORT_ANSWER + 120:
            picked.append(i)
    picked.sort(key=lambda p: candidates[p][:2])  # keep the original reading order
    titles = list(dict.fromkeys(hits[candidates[p][0]]["title"] for p in picked))
    return " ".join(candidates[p][2] for p in picked), titles


def llm_answer(question: str, hits: list[dict]) -> str:
    """Ask a local OpenAI-compatible server (Ollama, llamafile, LM Studio...)."""
    context = "\n\n---\n\n".join(f"{h['title']}: {h['text']}" for h in hits)
    body = {
        "model": config.LLM_MODEL,
        "temperature": 0.2,
        "max_tokens": 300,
        "messages": [
            {"role": "system", "content": f"{SYSTEM_PROMPT}\n\nContext:\n{context}"},
            {"role": "user", "content": question},
        ],
    }
    request = urllib.request.Request(
        config.LLM_URL + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=config.LLM_TIMEOUT) as response:
        data = json.load(response)
    text = data["choices"][0]["message"]["content"] or ""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()  # some models show their reasoning
    if not text:
        raise ValueError("empty answer from the local model")
    return text


def answer(question: str) -> dict:
    hits = search(question)
    if not hits:
        return {"answer": NO_ANSWER, "sources": [], "mode": "none"}
    if config.LLM_URL:
        try:
            sources = list(dict.fromkeys(h["title"] for h in hits))
            return {"answer": llm_answer(question, hits), "sources": sources, "mode": "llm"}
        except Exception as e:  # the local model is optional: fall back, don't fail
            log.warning("Local AI model failed (%s); answering from the knowledge base instead.", e)
    text, sources = extract_answer(question, hits)
    return {"answer": text, "sources": sources, "mode": "extract"}
