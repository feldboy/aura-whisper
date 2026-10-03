from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from aura_whisper.config import Config
from aura_whisper.llm.ollama_client import OllamaClient, OllamaError


class LLMWorker(QObject):
    """Runs on a background QThread. Consume via moveToThread()."""

    text_ready = Signal(str)
    error = Signal(str)
    started_processing = Signal(str)  # model name, for status display
    finished_processing = Signal()

    rewrite_requested = Signal(str, dict)  # transcript, mode dict

    def __init__(self, config: Config) -> None:
        super().__init__()
        self._config = config
        self.rewrite_requested.connect(self._on_rewrite)

    def update_config(self, config: Config) -> None:
        self._config = config

    @Slot(str, dict)
    def _on_rewrite(self, text: str, mode: dict) -> None:
        model = mode.get("ollama_model") or self._config.ollama_model
        if not model:
            self.error.emit("No Ollama model set — pick one in Settings → AI Modes.")
            return
        self.started_processing.emit(model)
        try:
            client = OllamaClient(self._config.ollama_url)
            result = client.rewrite(
                text,
                mode.get("prompt", ""),
                model,
                keep_alive_minutes=self._config.ollama_keep_alive_minutes,
            )
            self.text_ready.emit(result)
        except OllamaError as e:
            self.error.emit(str(e))
        except Exception as e:
            self.error.emit(f"AI rewrite failed: {e}")
        finally:
            self.finished_processing.emit()
