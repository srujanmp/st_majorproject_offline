import os
from pathlib import Path

import numpy as np
import pytest

from campus import config, face, ingest, search, security, speech
from campus.embed import WordPiece, _basic_tokens

from .conftest import needs_face, needs_search, needs_speech


# --- Tokenizer and embeddings ------------------------------------------------------------

def test_basic_tokens():
    assert _basic_tokens("Héllo, NMAMIT's  Library!") == ["hello", ",", "nmamit", "'", "s", "library", "!"]


@needs_search
def test_wordpiece_matches_bert():
    tok = WordPiece(config.MODELS_DIR / "minilm" / "vocab.txt")
    # Reference ids from the official tokenizer.
    assert tok.encode("When is the library open?") == [101, 2043, 2003, 1996, 3075, 2330, 1029, 102]
    assert len(tok.encode("word " * 1000)) == 256


@needs_search
def test_embeddings_rank_by_meaning():
    from campus.embed import embed

    docs = embed(["The library opens at 8:30 AM.", "Hostel fees are due in December."])
    question = embed(["when can I go to the library"])[0]
    assert np.argmax(docs @ question) == 0
    assert np.allclose(np.linalg.norm(docs, axis=1), 1, atol=1e-5)


# --- Text handling ------------------------------------------------------------------------

def test_chunk_text():
    assert search.chunk_text("hello") == ["hello"]
    text = " ".join(f"Sentence number {i}." for i in range(300))
    chunks = search.chunk_text(text, size=200, overlap=40)
    assert all(len(c) <= 200 for c in chunks)
    assert chunks[0].startswith("Sentence number 0.") and chunks[-1].endswith("Sentence number 299.")


def test_sentences():
    assert search.sentences("One. Two!\nThree? x") == ["One.", "Two!", "Three?"]


def test_parse_csv_and_text_files():
    assert ingest.parse_file(b"Title,Content\nA,first\n,skip\n", "x.csv") == [{"title": "A", "content": "first"}]
    assert ingest.parse_file(b"Day,Room\nMon,LH-1\n", "timetable.csv") == [
        {"title": "timetable - row 1", "content": "Day: Mon. Room: LH-1"}
    ]
    assert ingest.parse_file("Caf\xe9 opens at 8.".encode("cp1252"), "cafe.txt") == [
        {"title": "cafe", "content": "Café opens at 8."}
    ]
    with pytest.raises(ingest.IngestError):
        ingest.parse_file(b"", "x.csv")
    with pytest.raises(ingest.IngestError):
        ingest.parse_file(b"  ", "x.md")


# --- Security helpers --------------------------------------------------------------------

def test_password_hashing():
    stored = security.hash_password("open sesame")
    assert stored.startswith("scrypt$") and "open sesame" not in stored
    assert security.verify_password("open sesame", stored)
    assert not security.verify_password("open sesam", stored)
    assert not security.verify_password("x", "garbage")


def test_lockout():
    lock = security.Lockout(max_failures=3, lock_seconds=600)
    for _ in range(2):
        lock.fail("a")
    assert lock.seconds_left("a") == 0 and lock.tries_left("a") == 1
    lock.fail("a")
    assert lock.seconds_left("a") > 0 and lock.seconds_left("b") == 0
    lock.reset("a")
    assert lock.seconds_left("a") == 0


# --- Face ----------------------------------------------------------------------------------

def test_face_math_and_pixel_checks():
    a = np.array([1, 0, 0], dtype=np.float32)
    assert face.similarity(a, a) == pytest.approx(1.0)
    assert np.array_equal(face.from_bytes(face.to_bytes(a)), a)
    with pytest.raises(face.FaceError):
        face.pixels_to_image(b"123", 64, 64)
    with pytest.raises(face.FaceError):
        face.pixels_to_image(b"", 5000, 10)


def test_similarity_transform_recovers_known_transform():
    src = np.array([[10, 20], [50, 22], [30, 40], [15, 60], [45, 61]], dtype=np.float64)
    angle, scale, shift = 0.3, 1.7, np.array([5.0, -3.0])
    rot = scale * np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    m = face._similarity_transform(src, src @ rot.T + shift)
    assert np.allclose(m[:, :2], rot) and np.allclose(m[:, 2], shift)


@needs_face
def test_blank_picture_has_no_face():
    with pytest.raises(face.FaceError, match="No face"):
        face.embedding(np.full((480, 640, 3), 200, np.uint8))


@needs_face
@pytest.mark.skipif(not os.getenv("FACE_TEST_A") or not os.getenv("FACE_TEST_B"),
                    reason="set FACE_TEST_A / FACE_TEST_B to .npy RGB arrays of two different people")
def test_same_person_matches_and_different_person_does_not():
    a = np.load(os.environ["FACE_TEST_A"])
    b = np.load(os.environ["FACE_TEST_B"])
    ea, ea_flip, eb = face.embedding(a), face.embedding(a[:, ::-1].copy()), face.embedding(b)
    assert face.is_match(ea, ea_flip)[0]
    assert not face.is_match(ea, eb)[0]


# --- Speech ---------------------------------------------------------------------------------

@needs_speech
def test_transcribe_sample():
    wav = (Path(__file__).parent / "data" / "jfk.wav").read_bytes()
    text = speech.transcribe(wav)
    assert "ask not what your country can do for you" in text


def test_transcribe_rejects_bad_audio():
    with pytest.raises(speech.SpeechError):
        speech.transcribe(b"RIFF....not really")


# --- Optional local AI model (OpenAI-compatible server such as Ollama) ------------------------

@needs_search
def test_local_llm_is_used_and_falls_back(monkeypatch):
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    seen = {}

    class FakeOllama(BaseHTTPRequestHandler):
        def do_POST(self):
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            reply = {"choices": [{"message": {"content": "<think>hmm</think>The library opens at 8:30."}}]}
            data = json.dumps(reply).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), FakeOllama)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    hits = [{"title": "Library", "text": "The library opens at 8:30 AM on weekdays.", "score": 0.7, "module_id": 1}]
    monkeypatch.setattr(search, "search", lambda q: hits)
    monkeypatch.setattr(config, "LLM_MODEL", "qwen2.5:0.5b")

    monkeypatch.setattr(config, "LLM_URL", f"http://127.0.0.1:{server.server_port}/v1")
    result = search.answer("when does the library open")
    assert result == {"answer": "The library opens at 8:30.", "sources": ["Library"], "mode": "llm"}
    assert "8:30 AM" in seen["body"]["messages"][0]["content"] and seen["body"]["model"] == "qwen2.5:0.5b"

    server.shutdown()
    monkeypatch.setattr(config, "LLM_URL", "http://127.0.0.1:9/v1")  # nothing listening: fall back
    result = search.answer("when does the library open")
    assert result["mode"] == "extract" and "8:30 AM" in result["answer"]
