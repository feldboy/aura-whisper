from __future__ import annotations

import time
from typing import Optional

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal

SAMPLE_RATE = 16_000
BLOCK_SIZE = 1024
CHANNELS = 1

# How often to check whether the OS default input device changed while idle.
DEVICE_POLL_MS = 3_000
# Skip a poll tick within this long after a start()/stop() transition, so we
# never race sd._terminate() against an in-flight cue sound or a recording.
TRANSITION_COOLDOWN_S = 1.2


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
        self._current_device_name: Optional[str] = None
        self._last_transition_ts = 0.0
        self._device_poll_timer = QTimer(self)
        self._device_poll_timer.setInterval(DEVICE_POLL_MS)
        self._device_poll_timer.timeout.connect(self._poll_device_change)
        self._device_poll_timer.start()

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

        def _try_open() -> None:
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="float32",
                blocksize=BLOCK_SIZE,
                callback=self._callback,
            )
            self._stream.start()

        try:
            _try_open()
        except Exception:
            # PortAudio snapshots its device table when the host API is
            # initialized and does not rescan it while the process is
            # running, so a device that was hot-plugged (e.g. AirPods
            # connected after the app was already open) can be invisible
            # or stale until the table is rebuilt. Force a rescan by
            # tearing down and reinitializing PortAudio, then retry once.
            try:
                sd._terminate()
                sd._initialize()
                _try_open()
            except Exception as e:
                self._stream = None
                self.error.emit(f"Failed to open microphone: {e}")
                return False
        try:
            self._current_device_name = sd.query_devices(kind="input")["name"]
        except Exception:
            self._current_device_name = None
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
        self._last_transition_ts = time.monotonic()
        if self._recording:
            return True
        self._chunks = []
        if not self._open_stream():
            return False
        self._recording = True
        self.started.emit()
        return True

    def stop(self) -> np.ndarray:
        self._last_transition_ts = time.monotonic()
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

    def _poll_device_change(self) -> None:
        """Idle-time watchdog: keep the default input device in sync.

        PortAudio never re-syncs its notion of "the default device" on its
        own (see the comment in _open_stream), so switching between two
        already-connected devices in macOS Sound settings would otherwise
        go unnoticed until the app is restarted. Runs only while idle and
        well clear of a start()/stop() transition, so it never races the
        cue sound (a separate PortAudio output stream) or a live recording.
        """
        if self._recording:
            return
        if time.monotonic() - self._last_transition_ts < TRANSITION_COOLDOWN_S:
            return
        try:
            import sounddevice as sd
        except Exception:
            return
        try:
            sd._terminate()
            sd._initialize()
            current_name = sd.query_devices(kind="input")["name"]
        except Exception:
            return
        if current_name == self._current_device_name:
            return
        if self._warm and self._stream is not None:
            self._close_stream()
            self._open_stream()
        else:
            self._current_device_name = current_name

    def shutdown(self) -> None:
        self._recording = False
        self._device_poll_timer.stop()
        self._close_stream()
