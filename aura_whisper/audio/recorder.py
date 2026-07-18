from __future__ import annotations

from typing import Optional

import numpy as np
from PySide6.QtCore import QObject, Signal

SAMPLE_RATE = 16_000
BLOCK_SIZE = 1024
CHANNELS = 1


class Recorder(QObject):
    frame_ready = Signal(np.ndarray)
    level = Signal(float)
    started = Signal()
    stopped = Signal(np.ndarray)
    error = Signal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._stream = None
        self._chunks: list[np.ndarray] = []
        self._recording = False
        self._warm = False

    def is_recording(self) -> bool:
        return self._recording

    def _callback(self, indata, frames, time_info, status):
        if not self._recording:
            return
        mono = indata[:, 0].astype(np.float32, copy=True)
        self._chunks.append(mono)
        self.frame_ready.emit(mono)
        rms = float(np.sqrt(np.mean(mono * mono)) + 1e-9)
        self.level.emit(min(rms * 4.0, 1.0))

    def _open_stream(self) -> bool:
        if self._stream is not None:
            return True
        try:
            import sounddevice as sd
        except Exception as e:
            self.error.emit(f"sounddevice unavailable: {e}")
            return False
        try:
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="float32",
                blocksize=BLOCK_SIZE,
                callback=self._callback,
            )
            self._stream.start()
        except Exception as e:
            self._stream = None
            self.error.emit(f"Failed to open microphone: {e}")
            return False
        return True

    def _close_stream(self) -> None:
        try:
            if self._stream is not None:
                self._stream.stop()
                self._stream.close()
        except Exception:
            pass
        self._stream = None

    def set_warm(self, warm: bool) -> None:
        """Keep the input stream open between recordings for instant start."""
        self._warm = warm
        if warm and not self._recording:
            self._open_stream()
        elif not warm and not self._recording:
            self._close_stream()

    def start(self) -> bool:
        if self._recording:
            return True
        self._chunks = []
        if not self._open_stream():
            return False
        self._recording = True
        self.started.emit()
        return True

    def stop(self) -> np.ndarray:
        if not self._recording:
            return np.zeros(0, dtype=np.float32)
        self._recording = False
        if not self._warm:
            self._close_stream()
        buffer = (
            np.concatenate(self._chunks)
            if self._chunks
            else np.zeros(0, dtype=np.float32)
        )
        self._chunks = []
        self.stopped.emit(buffer)
        return buffer

    def shutdown(self) -> None:
        self._recording = False
        self._close_stream()
