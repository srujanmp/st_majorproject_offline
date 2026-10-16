"""Passwords, lockouts and rate limits. Standard library only."""
import base64
import hashlib
import hmac
import secrets
import threading
import time
from collections import defaultdict, deque

from . import config

# scrypt is a deliberately slow password hash built into Python.
_N, _R, _P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return "scrypt${}${}".format(base64.b64encode(salt).decode(), base64.b64encode(digest).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_b64, digest_b64 = stored.split("$")
        salt, expected = base64.b64decode(salt_b64), base64.b64decode(digest_b64)
    except ValueError:
        return False
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return hmac.compare_digest(digest, expected)


# A real hash to compare against when the login doesn't exist, so a wrong
# login takes as long as a wrong password (doesn't reveal which IDs exist).
DUMMY_HASH = hash_password(secrets.token_hex(8))


def load_secret_key() -> bytes:
    """Random key that signs session cookies, created once and kept in data/."""
    path = config.DATA_DIR / "secret.key"
    if path.exists():
        return path.read_bytes()
    key = secrets.token_bytes(32)
    path.write_bytes(key)
    return key


class Lockout:
    """Block an account for a while after too many failed attempts."""

    def __init__(self, max_failures: int, lock_seconds: int):
        self.max_failures = max_failures
        self.lock_seconds = lock_seconds
        self._fails: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def _recent(self, key: str) -> list[float]:
        cutoff = time.time() - self.lock_seconds
        self._fails[key] = [t for t in self._fails[key] if t > cutoff]
        return self._fails[key]

    def seconds_left(self, key: str) -> int:
        with self._lock:
            fails = self._recent(key)
            if len(fails) < self.max_failures:
                return 0
            return int(fails[-self.max_failures] + self.lock_seconds - time.time()) + 1

    def tries_left(self, key: str) -> int:
        with self._lock:
            return max(0, self.max_failures - len(self._recent(key)))

    def fail(self, key: str) -> None:
        with self._lock:
            self._fails[key].append(time.time())

    def reset(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)


class RateLimit:
    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] < now - 60:
                hits.popleft()
            if len(hits) >= self.per_minute:
                return False
            hits.append(now)
            return True


login_lockout = Lockout(5, 10 * 60)
face_lockout = Lockout(config.FACE_MAX_FAILURES, config.FACE_LOCK_MINUTES * 60)
voice_limit = RateLimit(30)
