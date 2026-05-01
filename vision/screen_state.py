"""Singleton screen state. Holds latest capture + cached OCR / vision answers.

Lets repeated 'what's on screen' queries reuse work when nothing has changed.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

from logger import log
from vision.capture import capture_active_window, capture_full_screen


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


class ScreenState:
    def __init__(self):
        self._latest: Optional[Path] = None
        self._hash: Optional[str] = None
        self._ocr: Optional[str] = None
        self._describe_cache: dict[tuple[str, str], str] = {}  # (hash, question) → answer

    def capture(self, region: str = "active_window") -> dict:
        """Capture and refresh state. Returns dict with path, hash, dimensions."""
        if region == "full":
            path = capture_full_screen()
        else:
            path = capture_active_window()

        new_hash = _hash_file(path)
        if new_hash != self._hash:
            self._ocr = None  # invalidate cached OCR
            self._describe_cache.clear()
        self._latest = path
        self._hash = new_hash
        log.info(f"ScreenState captured: {path.name} hash={new_hash[:8]}")
        return {"path": str(path), "hash": new_hash}

    def latest_path(self) -> Optional[Path]:
        return self._latest

    def latest_hash(self) -> Optional[str]:
        return self._hash

    def ocr_cached(self) -> Optional[str]:
        return self._ocr

    def set_ocr(self, text: str):
        self._ocr = text

    def describe_cached(self, question: str) -> Optional[str]:
        if self._hash is None:
            return None
        return self._describe_cache.get((self._hash, question.strip().lower()))

    def set_describe(self, question: str, answer: str):
        if self._hash is None:
            return
        self._describe_cache[(self._hash, question.strip().lower())] = answer


# Singleton
SCREEN = ScreenState()
