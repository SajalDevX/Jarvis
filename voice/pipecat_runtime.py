"""Pipecat-based voice runtime — sub-second latency target.

Pipeline:
    mic → SileroVAD → Groq Whisper STT → user-context aggregator
        → JarvisLLMService (wraps Orchestrator) → ElevenLabs Turbo WS TTS
        → speakers → assistant aggregator

All existing tools (smart_open_app, vision tools, system tools) work unchanged
because JarvisLLMService delegates to the same Orchestrator used in text mode.
"""
from __future__ import annotations

import asyncio

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
)
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.openai.stt import OpenAISTTService
from pipecat.transcriptions.language import Language
from pipecat.transports.local.audio import (
    LocalAudioTransport,
    LocalAudioTransportParams,
)

from agents.orchestrator import Orchestrator
from logger import log
from voice.services.jarvis_llm import JarvisLLMService


def _make_voice_cb(console):
    def cb(name, args, result):
        if console:
            console.print(f"  [green]✓[/green] [dim]{name}[/dim] → {result}")
    return cb


class PipecatVoiceRuntime:
    def __init__(self, orchestrator: Orchestrator, console=None):
        self.orch = orchestrator
        self.console = console

    def _build_pipeline(self) -> tuple[Pipeline, PipelineTask]:
        from config import (
            ELEVENLABS_API_KEY,
            ELEVENLABS_MODEL,
            ELEVENLABS_VOICE_ID,
            GROQ_API_KEY,
            GROQ_STT_MODEL,
        )

        if not GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY missing — Pipecat runtime requires Groq for STT+LLM")
        if not ELEVENLABS_API_KEY:
            raise RuntimeError("ELEVENLABS_API_KEY missing — Pipecat runtime requires ElevenLabs TTS")

        # Transport: local mic + speakers, 16k mono on input (Whisper-compatible).
        transport = LocalAudioTransport(
            LocalAudioTransportParams(
                audio_in_enabled=True,
                audio_in_sample_rate=16000,
                audio_in_channels=1,
                audio_out_enabled=True,
                audio_out_sample_rate=24000,
                audio_out_channels=1,
            )
        )

        # STT: Groq Whisper-large-v3-turbo via OpenAI-compatible endpoint.
        stt = OpenAISTTService(
            model=GROQ_STT_MODEL,
            api_key=GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1",
            language=Language.EN,
        )

        # LLM: our Orchestrator wrapped as a Pipecat service.
        llm = JarvisLLMService(
            orchestrator=self.orch,
            on_tool_call=_make_voice_cb(self.console),
        )

        # TTS: ElevenLabs Turbo v2 over WebSocket streaming-input.
        tts = ElevenLabsTTSService(
            api_key=ELEVENLABS_API_KEY,
            voice_id=ELEVENLABS_VOICE_ID,
            model=ELEVENLABS_MODEL,
        )

        # Context aggregator pair: collects user STT text → context → LLM,
        # and tracks assistant replies coming back from LLMTextFrames.
        context = LLMContext(messages=[])
        agg = LLMContextAggregatorPair(context)

        pipeline = Pipeline(
            [
                transport.input(),
                VADProcessor(vad_analyzer=SileroVADAnalyzer()),
                stt,
                agg.user(),
                llm,
                tts,
                transport.output(),
                agg.assistant(),
            ]
        )

        task = PipelineTask(pipeline)
        return pipeline, task

    async def _run_async(self):
        _, task = self._build_pipeline()
        runner = PipelineRunner()
        log.info("Pipecat voice pipeline starting")
        await runner.run(task)
        log.info("Pipecat voice pipeline stopped")

    def run(self):
        try:
            asyncio.run(self._run_async())
        except KeyboardInterrupt:
            log.info("Voice runtime cancelled (Ctrl+C)")
