from __future__ import annotations

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal, Slot

from aura_whisper.config import Config
from aura_whisper.models.manager import model_kind
from aura_whisper.transcribe.engine import FasterWhisperEngine, WhisperEngine


def _make_engine(path: str, device: str, compute_type: str):
    if model_kind(path) == "ctranslate2":
        return FasterWhisperEngine(path, device=device, compute_type=compute_type)
    return WhisperEngine(path, device=device, compute_type=compute_type)


def _is_english(language: str) -> bool:
    """True if whisper reported the utterance as English.

    The server returns full names ("english"); the CLI returns codes ("en").
    """
    lang = (language or "").strip().lower()
    return lang == "en" or lang.startswith("english")


class TranscribeWorker(QObject):
    """Runs on a background QThread. Consume via moveToThread()."""

    text_ready = Signal(str)
    error = Signal(str)
    started_processing = Signal()
    finished_processing = Signal()
    model_loaded = Signal()

    transcribe_requested = Signal(object)
    preload_requested = Signal()

    def __init__(self, config: Config) -> None:
        super().__init__()
        self._config = config
        self._engine: WhisperEngine | FasterWhisperEngine | None = None
        self._english_engine: WhisperEngine | FasterWhisperEngine | None = None
        self._idle_ms = 0
        self._apply_idle_interval()
        # Parented to self, so it moves to the worker thread with moveToThread.
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._on_idle)
        self.transcribe_requested.connect(self._on_transcribe)
        self.preload_requested.connect(self._on_preload)

    def _apply_idle_interval(self) -> None:
        minutes = int(getattr(self._config, "idle_unload_minutes", 5) or 0)
        self._idle_ms = max(0, minutes) * 60_000

    def _arm_idle(self) -> None:
        """(Re)start the idle countdown; call only from the worker thread."""
        if self._idle_ms > 0:
            self._idle_timer.start(self._idle_ms)
        else:
            self._idle_timer.stop()

    @Slot()
    def _on_idle(self) -> None:
        # No dictation for a while — unload the model to free RAM/GPU.
        if self._engine is not None:
            self._engine.shutdown()
            self._engine = None
        if self._english_engine is not None:
            self._english_engine.shutdown()
            self._english_engine = None

    def update_config(self, config: Config) -> None:
        self._config = config
        self._apply_idle_interval()
        if self._engine is not None:
            self._engine.shutdown()
        self._engine = None
        if self._english_engine is not None:
            self._english_engine.shutdown()
        self._english_engine = None

    def _ensure_engine(self):
        if self._engine is None:
            self._engine = _make_engine(
                self._config.model_path,
                self._config.device,
                self._config.compute_type,
            )
        return self._engine

    def _ensure_english_engine(self):
        """The optional English-only model, loaded lazily on first use."""
        path = (getattr(self._config, "english_model_path", "") or "").strip()
        if not path or path == (self._config.model_path or "").strip():
            return None
        if self._english_engine is None:
            self._english_engine = _make_engine(
                path, self._config.device, self._config.compute_type
            )
        return self._english_engine

    def _should_route_english(self, detected_language: str) -> bool:
        # Routing only makes sense while auto-detecting; a forced language
        # never triggers a switch.
        if (self._config.language or "auto") not in ("", "auto"):
            return False
        if not (getattr(self._config, "english_model_path", "") or "").strip():
            return False
        return _is_english(detected_language)

    @Slot()
    def _on_preload(self) -> None:
        try:
            self._ensure_engine().load()
            self.model_loaded.emit()
        except Exception as e:
            self.error.emit(f"Model load failed: {e}")
        self._arm_idle()

    @Slot(object)
    def _on_transcribe(self, buffer: np.ndarray) -> None:
        self._idle_timer.stop()
        self.started_processing.emit()
        try:
            engine = self._ensure_engine()
            result = engine.transcribe(
                buffer,
                language=self._config.language,
                beam_size=self._config.beam_size,
                vad_filter=self._config.vad_filter,
                initial_prompt=self._config.initial_prompt,
            )
            text = result.text
            # If the main (Hebrew) model heard English, re-run through the
            # dedicated English model and prefer its output.
            if self._should_route_english(result.language):
                english = self._ensure_english_engine()
                if english is not None:
                    try:
                        english_result = english.transcribe(
                            buffer,
                            language="en",
                            beam_size=self._config.beam_size,
                            vad_filter=self._config.vad_filter,
                            initial_prompt=self._config.initial_prompt,
                        )
                        if english_result.text.strip():
                            text = english_result.text
                    except Exception as e:
                        # Keep the main model's text if the fallback fails.
                        self.error.emit(f"English model failed: {e}")
            self.text_ready.emit(text)
        except Exception as e:
            self.error.emit(f"Transcription failed: {e}")
        finally:
            self.finished_processing.emit()
            self._arm_idle()
