"""Pipecat LLMService that delegates to the existing Jarvis Orchestrator.

The Orchestrator already does cache lookup, direct-dispatch, quick-classify,
router → agent → tool dispatch. This wrapper plugs all of that into a Pipecat
pipeline so Pipecat's STT (Groq Whisper) and TTS (ElevenLabs WebSocket) can
stream around it.

We run the synchronous Orchestrator.handle() in a worker thread (asyncio.to_thread)
so the frame loop stays responsive, then sentence-split the reply and push it as
LLMTextFrames so the downstream TTS can start synthesising before the whole
reply arrives at the speaker.
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Callable

from pipecat.frames.frames import (
    Frame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.llm_service import LLMService
from pipecat.services.settings import LLMSettings

from agents.orchestrator import Orchestrator
from logger import log


def _store_settings() -> LLMSettings:
    """Build a fully-populated LLMSettings store so validate_complete() passes.
    Our service ignores most of these — Orchestrator owns model/tier selection."""
    return LLMSettings(
        model="jarvis-orchestrator",
        system_instruction=None,
        temperature=None,
        max_tokens=None,
        top_p=None,
        top_k=None,
        frequency_penalty=None,
        presence_penalty=None,
        seed=None,
        filter_incomplete_user_turns=None,
        user_turn_completion_config=None,
    )


# Punctuation-based sentence splitter — emits chunks ending with .!? or newline.
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+|(?<=\n)")


def _split_for_tts(text: str) -> list[str]:
    parts = [p.strip() for p in _SENT_SPLIT.split(text) if p.strip()]
    return parts or [text.strip()]


class JarvisLLMService(LLMService):
    """LLMService that proxies LLMContextFrame → Orchestrator.handle()."""

    def __init__(
        self,
        orchestrator: Orchestrator,
        on_tool_call: Callable | None = None,
        console=None,
        **kwargs,
    ):
        kwargs.setdefault("settings", _store_settings())
        super().__init__(**kwargs)
        self._orch = orchestrator
        self._on_tool_call = on_tool_call
        self._console = console

    @staticmethod
    def _last_user_text(messages: list[dict]) -> str:
        for m in reversed(messages):
            if m.get("role") == "user":
                content = m.get("content")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            return part.get("text", "")
        return ""

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if not isinstance(frame, LLMContextFrame):
            await self.push_frame(frame, direction)
            return

        user_text = self._last_user_text(frame.context.messages)
        if not user_text.strip():
            log.debug("JarvisLLMService: no user text in context, skipping")
            return

        log.info(f"JarvisLLMService received: {user_text!r}")
        if self._console:
            self._console.print(f"\n[bold]You:[/bold] {user_text}")
        await self.push_frame(LLMFullResponseStartFrame())
        await self.start_processing_metrics()
        await self.start_ttfb_metrics()
        t0 = time.time()

        try:
            agent_name, reply = await asyncio.to_thread(
                self._orch.handle, user_text, self._on_tool_call, True  # voice=True
            )
            ttfb = time.time() - t0
            await self.stop_ttfb_metrics()
            log.info(
                f"JarvisLLMService → {agent_name}: {reply!r} ({ttfb:.2f}s)"
            )

            if reply:
                if self._console:
                    self._console.print(f"[bold cyan]Jarvis[/bold cyan] [dim]({agent_name})[/dim]: {reply}")
                for sentence in _split_for_tts(reply):
                    await self.push_frame(LLMTextFrame(sentence + " "))
        except Exception as e:
            log.error(f"JarvisLLMService failed: {e}", exc_info=True)
            await self.push_error(error_msg=f"Jarvis error: {e}", exception=e)
        finally:
            await self.stop_processing_metrics()
            await self.push_frame(LLMFullResponseEndFrame())
