import threading
import time
from collections import defaultdict

_WINDOW = 60
_MAX_ATTEMPTS = 5

_lock = threading.Lock()
_attempts: dict[tuple[str, str], list[float]] = defaultdict(list)


def _prune(key: tuple[str, str], now: float) -> None:
    _attempts[key] = [t for t in _attempts[key] if now - t < _WINDOW]


def is_limited(kind: str, identifier: str) -> bool:
    key = (kind, identifier)
    now = time.monotonic()
    with _lock:
        _prune(key, now)
        return len(_attempts[key]) >= _MAX_ATTEMPTS


def record_failure(kind: str, identifier: str) -> None:
    key = (kind, identifier)
    now = time.monotonic()
    with _lock:
        _prune(key, now)
        _attempts[key].append(now)


def clear(kind: str, identifier: str) -> None:
    key = (kind, identifier)
    with _lock:
        _attempts.pop(key, None)
