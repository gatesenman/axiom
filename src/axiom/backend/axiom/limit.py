"""Small in-memory window used by chat and solve starts.

The limits are generous so a normal studio session and the test suite stay
under them. A unit test drives the limiter directly.
"""

from __future__ import annotations

import time
from collections import defaultdict

from axiom.errors import AxiomError

_hits: dict[str, list[float]] = defaultdict(list)


def reset_limits() -> None:
    _hits.clear()


def check_rate(key: str, limit: int = 40, window: float = 60.0) -> None:
    now = time.monotonic()
    bucket = _hits[key]
    cutoff = now - window
    while bucket and bucket[0] < cutoff:
        bucket.pop(0)
    if len(bucket) >= limit:
        raise AxiomError(
            "请求过于频繁，请稍后再试。",
            "Too many requests. Wait a moment and try again.",
            code="rate_limit",
            status=429,
        )
    bucket.append(now)
