"""LRU intent cache. Persists to ~/.cache/jarvis/intents.json across sessions.

Stores routing decisions (and optionally cached replies for deterministic asks).
Skips both the router LLM call AND the agent LLM call when a hit is full.
"""
from __future__ import annotations

import json
import re
from collections import OrderedDict
from pathlib import Path
from typing import Optional, NamedTuple

from logger import log


CACHE_DIR = Path.home() / ".cache" / "jarvis"
CACHE_FILE = CACHE_DIR / "intents.json"
MAX_ENTRIES = 200

# Filler words stripped during normalization for fuzzy hit-rate
_FILLER = {
    "please", "could", "you", "can", "the", "a", "an",
    "for", "me", "to", "i", "want", "need", "would", "like",
}


class CachedIntent(NamedTuple):
    agent: str
    tier: str
    reply: Optional[str]  # full cached reply, or None (route-only cache)


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation, drop filler, collapse spaces."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", " ", text)
    tokens = [t for t in text.split() if t not in _FILLER]
    return " ".join(tokens)


class IntentCache:
    def __init__(self, max_entries: int = MAX_ENTRIES):
        self._max = max_entries
        self._data: OrderedDict[str, CachedIntent] = OrderedDict()
        self._load()

    def _load(self):
        if not CACHE_FILE.exists():
            return
        try:
            raw = json.loads(CACHE_FILE.read_text())
            for k, v in raw.items():
                self._data[k] = CachedIntent(**v)
            log.info(f"IntentCache loaded {len(self._data)} entries")
        except Exception as e:
            log.warning(f"IntentCache load failed: {e}")

    def _save(self):
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            CACHE_FILE.write_text(json.dumps(
                {k: v._asdict() for k, v in self._data.items()},
                indent=2,
            ))
        except Exception as e:
            log.warning(f"IntentCache save failed: {e}")

    def get(self, user_input: str) -> Optional[CachedIntent]:
        key = _normalize(user_input)
        if not key:
            return None
        if key in self._data:
            self._data.move_to_end(key)  # LRU
            log.debug(f"IntentCache HIT: {key!r}")
            return self._data[key]
        log.debug(f"IntentCache MISS: {key!r}")
        return None

    def put(
        self,
        user_input: str,
        agent: str,
        tier: str,
        reply: Optional[str] = None,
    ):
        key = _normalize(user_input)
        if not key:
            return
        self._data[key] = CachedIntent(agent=agent, tier=tier, reply=reply)
        self._data.move_to_end(key)
        if len(self._data) > self._max:
            self._data.popitem(last=False)
        self._save()
