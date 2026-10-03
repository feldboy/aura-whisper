from __future__ import annotations

import ctypes
import ctypes.util
import time
from typing import Optional

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal

SAMPLE_RATE = 16_000
BLOCK_SIZE = 1024
CHANNELS = 1

# How often to check (via CoreAudio, ~50 µs) whether audio hardware changed.
DEVICE_POLL_MS = 1_000
# Skip a resync within this long after a start()/stop() transition, so we
# never race sd._terminate() against an in-flight cue sound or a recording.
TRANSITION_COOLDOWN_S = 1.2


class _AudioPropertyAddress(ctypes.Structure):
    _fields_ = [
        ("mSelector", ctypes.c_uint32),
        ("mScope", ctypes.c_uint32),
        ("mElement", ctypes.c_uint32),
    ]


def _fourcc(code: str) -> int:
    return int.from_bytes(code.encode("ascii"), "big")


_coreaudio = None


def _audio_route() -> Optional[tuple[int, int, int]]:
    """(default input id, default output id, device-list size) from CoreAudio.

    Unlike PortAudio's device table this is always live, so it tells us
    cheaply when headphones/mics were connected or the default device
    switched. Returns None if CoreAudio can't be queried (non-macOS, etc.).
    """
    global _coreaudio
    try:
        if _coreaudio is None:
            lib = ctypes.CDLL(ctypes.util.find_library("CoreAudio"))
            lib.AudioObjectGetPropertyData.argtypes = [
                ctypes.c_uint32,
                ctypes.POINTER(_AudioPropertyAddress),
                ctypes.c_uint32,
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_uint32),
                ctypes.c_void_p,
            ]
            lib.AudioObjectGetPropertyData.restype = ctypes.c_int32
            lib.AudioObjectGetPropertyDataSize.argtypes = [
                ctypes.c_uint32,
                ctypes.POINTER(_AudioPropertyAddress),
                ctypes.c_uint32,
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_uint32),
            ]
            lib.AudioObjectGetPropertyDataSize.restype = ctypes.c_int32
            _coreaudio = lib
        system_object = 1  # kAudioObjectSystemObject
        glob = _fourcc("glob")  # kAudioObjectPropertyScopeGlobal

        def default_device(selector: str) -> int:
            addr = _AudioPropertyAddress(_fourcc(selector), glob, 0)
            value = ctypes.c_uint32(0)
            size = ctypes.c_uint32(4)
            err = _coreaudio.AudioObjectGetPropertyData(
                system_object, ctypes.byref(addr), 0, None,
                ctypes.byref(size), ctypes.byref(value),
            )
            if err:
                raise OSError(err)
            return value.value

        addr = _AudioPropertyAddress(_fourcc("dev#"), glob, 0)
        list_size = ctypes.c_uint32(0)
        err = _coreaudio.AudioObjectGetPropertyDataSize(
            system_object, ctypes.byref(addr), 0, None, ctypes.byref(list_size)
        )
        if err:
            raise OSError(err)
        return default_device("dIn "), default_device("dOut"), list_size.value
    except Exception:
        return None


def _cue_playing(sd) -> bool:
    """True while sounddevice's play() stream (our cue sounds) is running."""
    try:
        cb = sd._last_callback
        return bool(cb and cb.stream.active)
    except Exception:
        return False


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
        self._last_transition_ts = 0.0
        # The route PortAudio's device table currently reflects (it was built
        # when sounddevice was imported, i.e. just before this).
        self._route = _audio_route()
        self._device_poll_timer = QTimer(self)
        self._device_poll_timer.setInterval(DEVICE_POLL_MS)
        self._device_poll_timer.timeout.connect(self._poll_device_change)
        self._device_poll_timer.start()

    def is_recording(self) -> bool:
        return self._recording

    def refresh_devices(self, force: bool = False) -> None:
        """Rebuild PortAudio's device table if the audio hardware changed.

        PortAudio snapshots the device list (and which input/output is the
        default) when it initializes and never rescans it while the process
        runs, so headphones connected after launch stay invisible — the app
        keeps recording from (and playing cues to) the old device until it is
        restarted. Called before every recording (before the start cue, since
        a rebuild stops any sound that is playing); it's a no-op unless
        CoreAudio reports a change or ``force`` is set. Skipped while
        recording or while a warm stream is open, because a rebuild tears
        down every PortAudio stream.
        """
        if self._recording or self._stream is not None:
            return
        route = _audio_route()
        if not force and route is not None and route == self._route:
            return
        try:
            import sounddevice as sd
        except Exception:
            return
        try:
            sd.stop()  # close the last cue stream before PortAudio goes away
        except Exception:
            pass
        try:
            if sd._initialized:
                sd._terminate()
        except Exception:
            pass
        try:
            sd._initialize()
        except Exception:
            return
        self._route = route

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
            self._close_stream()
            self.refresh_devices(force=True)
            try:
                _try_open()
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
        """Idle-time watchdog: follow hot-plugged / newly-default devices.

        Rescans as soon as CoreAudio reports a change, so the next recording
        starts instantly on the right mic. A warm (kept-open) stream is
        reopened on the new default device. Waits while recording, right
        after a start()/stop(), or while a cue is playing — the change stays
        pending and is retried on the next tick (and start() catches it too).
        """
        if self._recording:
            return
        route = _audio_route()
        if route is None or route == self._route:
            return
        if time.monotonic() - self._last_transition_ts < TRANSITION_COOLDOWN_S:
            return
        try:
            import sounddevice as sd
        except Exception:
            return
        if _cue_playing(sd):
            return
        was_warm = self._stream is not None
        self._close_stream()
        self.refresh_devices()
        if was_warm and self._warm:
            self._open_stream()

    def shutdown(self) -> None:
        self._recording = False
        self._device_poll_timer.stop()
        self._close_stream()
