"""Vision tools — read-only screen perception.

- take_screenshot: capture full screen or active window
- ocr_screen: extract text via tesseract (no LLM cost)
- describe_screen: vision LLM Q&A on the latest capture
- find_ui_element: vision LLM identifies UI element location (description only, no clicks)
"""
from __future__ import annotations

from logger import log
from tools.base import Tool
from vision.screen_state import SCREEN


class TakeScreenshotTool(Tool):
    name = "take_screenshot"
    description = (
        "Capture a screenshot. Use 'active_window' (default) for the focused window, "
        "or 'full' for entire desktop. Returns the path; downstream tools (ocr_screen, "
        "describe_screen) will use it automatically."
    )
    parameters = {
        "type": "object",
        "properties": {
            "region": {
                "type": "string",
                "enum": ["active_window", "full"],
                "description": "Capture region. Defaults to active_window.",
            }
        },
        "required": [],
    }

    def execute(self, region: str = "active_window") -> str:
        try:
            info = SCREEN.capture(region=region)
            return f"Screenshot saved: {info['path']} (hash {info['hash'][:8]})"
        except Exception as e:
            log.error(f"take_screenshot failed: {e}")
            return f"Failed to capture screen: {e}"


class OCRScreenTool(Tool):
    name = "ocr_screen"
    description = (
        "Extract text from the latest screenshot via tesseract OCR. Cheap and fast (no LLM). "
        "Best for terminals, editors, web pages with lots of visible text. "
        "Auto-captures if no screenshot exists yet."
    )
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def execute(self) -> str:
        if SCREEN.latest_path() is None:
            SCREEN.capture()

        cached = SCREEN.ocr_cached()
        if cached is not None:
            log.debug("OCR cache hit")
            return cached or "(no text detected)"

        try:
            import pytesseract
            from PIL import Image
        except ImportError as e:
            return f"OCR unavailable — install: pip install pytesseract pillow + apt install tesseract-ocr ({e})"

        try:
            img = Image.open(SCREEN.latest_path())
            text = pytesseract.image_to_string(img).strip()
        except Exception as e:
            log.error(f"OCR failed: {e}")
            return f"OCR error: {e}"

        SCREEN.set_ocr(text)
        return text or "(no text detected)"


class DescribeScreenTool(Tool):
    name = "describe_screen"
    description = (
        "Send the latest screenshot to a vision LLM to answer a specific question about it. "
        "Use for visual questions (UI layout, what is shown, what's the error, is it loaded). "
        "Auto-captures if no screenshot exists. Costs more than ocr_screen — prefer OCR for "
        "pure-text questions."
    )
    parameters = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "What do you want to know about the screen?",
            }
        },
        "required": ["question"],
    }

    def execute(self, question: str) -> str:
        if SCREEN.latest_path() is None:
            SCREEN.capture()

        cached = SCREEN.describe_cached(question)
        if cached:
            log.debug("describe_screen cache hit")
            return cached

        from llm.client import chat
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a vision assistant. Answer the user's question about the "
                    "screenshot they attached. Be concise — one short paragraph."
                ),
            },
            {"role": "user", "content": question},
        ]
        try:
            reply, _, _ = chat(
                messages,
                tools=None,
                tier="vision",
                image_paths=[str(SCREEN.latest_path())],
            )
        except Exception as e:
            log.error(f"describe_screen LLM failed: {e}")
            return f"Vision call failed: {e}"

        SCREEN.set_describe(question, reply)
        return reply or "(no description)"


class FindUIElementTool(Tool):
    name = "find_ui_element"
    description = (
        "Identify a UI element (button, search bar, link, etc.) on the latest screenshot. "
        "Returns a textual description of where it is — does NOT click or interact. "
        "Read-only inspection."
    )
    parameters = {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "What UI element to find (e.g. 'login button', 'address bar', 'send icon')",
            }
        },
        "required": ["description"],
    }

    def execute(self, description: str) -> str:
        if SCREEN.latest_path() is None:
            SCREEN.capture()

        from llm.client import chat
        prompt = (
            f"Find the {description!r} in the screenshot. "
            "Describe its approximate location (top/middle/bottom + left/center/right) "
            "and any visible label or icon. If you cannot find it, say so plainly."
        )
        messages = [
            {"role": "system", "content": "You identify UI elements in screenshots concisely."},
            {"role": "user", "content": prompt},
        ]
        try:
            reply, _, _ = chat(
                messages,
                tools=None,
                tier="vision",
                image_paths=[str(SCREEN.latest_path())],
            )
        except Exception as e:
            log.error(f"find_ui_element failed: {e}")
            return f"Vision call failed: {e}"

        return reply or "(could not locate)"
