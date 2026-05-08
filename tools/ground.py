"""Pixel-coordinate grounder.

Given a natural-language description ("the green Login button") and the
latest screenshot, asks Gemini 2.5 Flash to return the (x, y) center of
that element in image-pixel space, then scales coords back to native
screen geometry. Returns strict JSON for the agent to consume.

Cache: keyed by (screenshot_hash, normalized_description) so repeated
grounding of the same target on the same screen is free.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from PIL import Image

from logger import log
from tools.base import Tool
from vision.screen_state import SCREEN


# Send larger images to the grounder than to describe_screen — we need the
# detail for accurate coordinates. 1280 wide is a good cost/quality trade.
GROUND_MAX_WIDTH = 1280


_GROUND_PROMPT = (
    "You are a UI grounding model. Given the screenshot, return the pixel "
    "coordinates of the CENTER of the element described. Output STRICT JSON "
    "and nothing else.\n\n"
    "Schema: {\"x\": int, \"y\": int, \"confidence\": \"high|medium|low\", "
    "\"reasoning\": \"one short clause\"}\n\n"
    "Coordinates are pixels in the image you see (not the user's full screen). "
    "If the element is not visible or you are uncertain, set confidence=low and "
    "still return your best guess. NEVER refuse, NEVER add prose."
)


class GroundCache:
    """Tiny in-memory cache keyed by (screenshot_hash, normalized_description)."""

    def __init__(self, max_entries: int = 64):
        self._d: dict[tuple[str, str], dict] = {}
        self._max = max_entries

    @staticmethod
    def _norm(s: str) -> str:
        return re.sub(r"\s+", " ", s.strip().lower())

    def get(self, screen_hash: str, description: str) -> Optional[dict]:
        return self._d.get((screen_hash, self._norm(description)))

    def put(self, screen_hash: str, description: str, value: dict) -> None:
        if len(self._d) >= self._max:
            # drop arbitrary oldest entry
            self._d.pop(next(iter(self._d)))
        self._d[(screen_hash, self._norm(description))] = value


_CACHE = GroundCache()


def _image_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as im:
        return im.size  # (width, height)


def _scale_to_native(x: int, y: int, image_size: tuple[int, int], native: tuple[int, int]) -> tuple[int, int]:
    iw, ih = image_size
    nw, nh = native
    if iw <= 0 or ih <= 0:
        return x, y
    sx = nw / iw
    sy = nh / ih
    return int(round(x * sx)), int(round(y * sy))


def ground(description: str) -> dict:
    """Run a grounding call. Returns dict with keys x, y, confidence, reasoning, native_size, image_size.

    Captures a fresh screenshot if none exists yet. Uses last cached value when
    description + screenshot hash match.
    """
    if SCREEN.latest_path() is None:
        SCREEN.capture()

    screen_hash = SCREEN.latest_hash() or ""
    cached = _CACHE.get(screen_hash, description)
    if cached:
        log.debug(f"ground cache hit: {description!r}")
        return cached

    path = SCREEN.latest_path()
    if path is None:
        return {"x": -1, "y": -1, "confidence": "low", "reasoning": "no screenshot available"}

    # Image as Gemini will see it after downscale
    img_w, img_h = _image_size(path)
    if img_w > GROUND_MAX_WIDTH:
        scaled_w = GROUND_MAX_WIDTH
        scaled_h = int(round(img_h * (GROUND_MAX_WIDTH / img_w)))
    else:
        scaled_w, scaled_h = img_w, img_h

    from llm.client import chat
    messages = [
        {"role": "system", "content": _GROUND_PROMPT},
        {
            "role": "user",
            "content": (
                f"Find this on the screen: {description.strip()}.\n"
                f"Image dimensions: {scaled_w}x{scaled_h} pixels."
            ),
        },
    ]
    try:
        reply, _, _ = chat(
            messages,
            tools=None,
            tier="vision",
            image_paths=[str(path)],
            image_max_width=GROUND_MAX_WIDTH,
        )
    except Exception as e:
        log.error(f"ground LLM error: {e}")
        return {"x": -1, "y": -1, "confidence": "low", "reasoning": f"LLM error: {e}"}

    parsed = _parse_json(reply)
    if parsed is None:
        log.warning(f"ground: failed to parse JSON from {reply!r}")
        return {"x": -1, "y": -1, "confidence": "low", "reasoning": f"unparsable reply: {reply[:80]}"}

    # Coords arrive in scaled-image space; map back to native screen pixels.
    native_x, native_y = _scale_to_native(
        int(parsed.get("x", 0)),
        int(parsed.get("y", 0)),
        image_size=(scaled_w, scaled_h),
        native=(img_w, img_h),
    )
    out = {
        "x": native_x,
        "y": native_y,
        "confidence": str(parsed.get("confidence", "low")).lower(),
        "reasoning": str(parsed.get("reasoning", "")),
        "image_size": [img_w, img_h],
    }
    _CACHE.put(screen_hash, description, out)
    log.info(f"ground {description!r} -> ({native_x}, {native_y}) conf={out['confidence']}")
    return out


def _parse_json(text: str) -> Optional[dict]:
    text = text.strip()
    # Strip ```json fences if present
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Fall back: extract first {...} block
    m = re.search(r"\{.*?\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None


class GroundElementTool(Tool):
    name = "ground_element"
    description = (
        "Locate a UI element on the current screenshot. Returns pixel "
        "coordinates (x, y) and a confidence rating. ALWAYS call this before "
        "any click/drag/right_click — never guess coordinates yourself. "
        "If confidence is 'low', call screen_zoom on the suspected region "
        "and re-ground for higher accuracy."
    )
    parameters = {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": (
                    "Concrete description of the element to locate, e.g. "
                    "'the green Login button', 'the Firefox URL bar', "
                    "'the close (X) button on the active window'."
                ),
            }
        },
        "required": ["description"],
    }

    def execute(self, description: str) -> str:
        result = ground(description)
        return json.dumps(result, separators=(",", ":"))
