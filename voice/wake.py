"""Always-on wake-word listener using openWakeWord. Free, local, low CPU."""
from __future__ import annotations

import threading
from typing import Callable

import numpy as np
import sounddevice as sd

from logger import log


SAMPLE_RATE = 16000
FRAME_SAMPLES = 1280  # 80ms — openwakeword's chunk size


class WakeListener:
    def __init__(self, model_name: str = "hey_jarvis_v0.1", threshold: float = 0.5):
        self.model_name = model_name
        self.threshold = threshold
        self._stop = threading.Event()
        self._thread = None

    def start(self, on_wake: Callable[[], None]):
        try:
            from openwakeword.model import Model
        except ImportError:
            log.error("openwakeword not installed — pip install openwakeword")
            return

        log.info(f"Loading wake-word model: {self.model_name}")
        try:
            model = Model(wakeword_models=[self.model_name])
        except Exception as e:
            log.error(f"Wake model load failed: {e}")
            return

        self._stop.clear()

        def loop():
            log.info("Wake listener active")
            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="int16",
                blocksize=FRAME_SAMPLES,
            ) as stream:
                while not self._stop.is_set():
                    frame, _ = stream.read(FRAME_SAMPLES)
                    pcm = frame.flatten()
                    scores = model.predict(pcm)
                    for kw, score in scores.items():
                        if score >= self.threshold:
                            log.info(f"Wake word '{kw}' detected (score={score:.2f})")
                            threading.Thread(target=on_wake, daemon=True).start()
                            # cool-down: skip for 1s to avoid double-trigger
                            sd.sleep(1000)
                            break

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        log.info("Wake listener stopped")
