"""Hands requests from the phone server's HTTP threads to the GUI thread."""

from __future__ import annotations

from concurrent.futures import Future

import numpy as np
from PySide6.QtCore import QObject, Signal


class PhoneBridge(QObject):
    """Lives on the GUI thread. ``submit_audio``/``request_approval`` are
    called from HTTP threads; the signals arrive queued on the GUI thread,
    whose slots resolve the returned Future."""

    # (audio, mode name or "", Future[str])
    audio_received = Signal(object, str, object)
    # (phone name, ip, Future[bool])
    approval_requested = Signal(str, str, object)
    # phone name
    paired = Signal(str)
    # Live streaming: (mode, Future[id]); (id, audio, Future[None]);
    # (id, last audio, Future[text]).
    stream_begin = Signal(str, object)
    stream_chunk = Signal(str, object, object)
    stream_end = Signal(str, object, object)

    def submit_audio(self, audio: np.ndarray, mode: str) -> Future:
        future: Future = Future()
        self.audio_received.emit(audio, mode, future)
        return future

    def request_approval(self, name: str, ip: str) -> Future:
        future: Future = Future()
        self.approval_requested.emit(name, ip, future)
        return future

    def begin_stream(self, mode: str) -> Future:
        future: Future = Future()
        self.stream_begin.emit(mode, future)
        return future

    def push_chunk(self, stream_id: str, audio: np.ndarray) -> Future:
        future: Future = Future()
        self.stream_chunk.emit(stream_id, audio, future)
        return future

    def end_stream(self, stream_id: str, audio: np.ndarray) -> Future:
        future: Future = Future()
        self.stream_end.emit(stream_id, audio, future)
        return future
