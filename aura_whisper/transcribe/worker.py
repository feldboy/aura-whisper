from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal, Slot

from aura_whisper.config import Config
from aura_whisper.models.manager import model_kind
from aura_whisper.transcribe.engine import FasterWhisperEngine, WhisperEngine

SAMPLE_RATE = 16_000
# Streaming: while the user is still talking, every finished phrase (audio up
# to a pause) is transcribed in the background, so on stop only the last few
# seconds are left to process.
_STREAM_MIN_CHUNK_S = 2.5  # don't cut chunks shorter than this
_STREAM_MAX_CHUNK_S = 20.0  # force a cut (at the quietest spot) past this
_STREAM_PAUSE_S = 0.35  # a pause at least this long is a safe cut point
_STREAM_CHECK_S = 0.3  # how often to look for a cut point
_FRAME = 320  # 20 ms analysis frames
_PROMPT_TAIL_CHARS = 160  # earlier text handed to the next chunk as context
# Auto-detect costs a whole extra encoder pass on every call. While streaming,
# detect once from the first stretch of speech, then pin that language.
_DETECT_AFTER_S = 2.5
_DETECT_MIN_VOICE_S = 1.0
# Keep re-checking the language on the latest speech while the user talks,
# so the final stretch (transcribed after stop) uses what they spoke last.
_REDETECT_EVERY_S = 2.0
_REDETECT_WINDOW_S = 3.0
# Hebrew is the default: only switch to English when whisper is this sure.
# Anything else (unsure, or a misdetection like Arabic/Yiddish) → Hebrew.
_ENGLISH_MIN_PROB = 0.6
_DEFAULT_LANGUAGE = "he"
# Detection on less audio than this is a coin flip ("כן" reads as English):
# just use Hebrew.
_DETECT_MIN_AUDIO_S = 0.6


def _frame_rms(audio: np.ndarray) -> np.ndarray:
    n = len(audio) // _FRAME
    if n == 0:
        return np.zeros(0, dtype=np.float32)
    frames = audio[: n * _FRAME].reshape(n, _FRAME)
    return np.sqrt(np.mean(frames * frames, axis=1))


def _silence_threshold(rms: np.ndarray) -> float:
    # Relative to this recording's noise floor, so it works for a quiet room
    # and a noisy cafe alike.
    if rms.size == 0:
        return 0.005
    return max(0.004, float(np.percentile(rms, 15)) * 2.2)


def has_speech(audio: np.ndarray, min_voice_s: float = 0.16) -> bool:
    """Cheap energy check: is there anything worth sending to whisper?

    Whisper tends to hallucinate ("Thank you.") on pure silence.
    """
    rms = _frame_rms(audio)
    if rms.size == 0:
        return False
    thr = max(_silence_threshold(rms), 0.006)
    voiced = int(np.count_nonzero(rms > thr * 1.8))
    return voiced * _FRAME >= min_voice_s * SAMPLE_RATE


def _clean_chunk(text: str) -> str:
    # A chunk decoded with the previous text as prompt sometimes opens with
    # the punctuation that "belongs" to the previous chunk (", ככה…").
    return text.strip().lstrip(",.;:-–—، ").strip()


def find_cut(audio: np.ndarray, force: bool = False) -> int | None:
    """Sample index of a pause where ``audio`` can be split without cutting
    a word, or None. The cut lands inside the latest long-enough pause that
    starts after the minimum chunk length. With ``force``, falls back to the
    quietest frame of the last few seconds."""
    rms = _frame_rms(audio)
    if rms.size == 0:
        return None
    thr = _silence_threshold(rms)
    quiet = rms < thr
    min_frames = int(_STREAM_PAUSE_S * SAMPLE_RATE / _FRAME)
    first_ok = int(_STREAM_MIN_CHUNK_S * SAMPLE_RATE / _FRAME)
    best = None
    run_start = None
    for i, q in enumerate(np.append(quiet, False)):
        if q and run_start is None:
            run_start = i
        elif not q and run_start is not None:
            run_len = i - run_start
            # A pause still running at the end only counts once it's long
            # enough; the speaker may simply be mid-breath.
            if run_len >= min_frames:
                mid = run_start + min(run_len // 2, min_frames)
                if mid >= first_ok:
                    best = mid
            run_start = None
    if best is not None:
        return best * _FRAME
    if force:
        tail_from = max(first_ok, rms.size - int(4 * SAMPLE_RATE / _FRAME))
        if tail_from < rms.size:
            return int(tail_from + int(np.argmin(rms[tail_from:]))) * _FRAME
    return None


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
    # Streaming (call from any thread; handled on the worker thread).
    stream_begin_requested = Signal()
    stream_frame = Signal(object)
    stream_cancel_requested = Signal()

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
        self.stream_begin_requested.connect(self._on_stream_begin)
        self.stream_frame.connect(self._on_stream_frame)
        self.stream_cancel_requested.connect(self._on_stream_cancel)
        self._reset_stream()

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
        if not Path(path).exists():
            return None  # configured but deleted/moved: main model handles it
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

    # --- streaming ---

    def _reset_stream(self) -> None:
        self._streaming = False
        self._stream_chunks: list[np.ndarray] = []
        self._stream_len = 0
        self._stream_checked_len = 0
        self._committed = 0  # samples already transcribed
        self._stream_texts: list[str] = []
        self._stream_lang = ""  # pinned language for this recording
        self._detect_tried = False
        self._detected_at = 0  # stream length at the last detection

    @Slot()
    def _on_stream_begin(self) -> None:
        self._idle_timer.stop()
        self._reset_stream()
        self._streaming = True
        # Load the models while the user talks instead of after they stop.
        try:
            self._ensure_engine().load()
            if (self._config.language or "auto") in ("", "auto"):
                self._detect_engine().load()
        except Exception:
            pass  # surfaced by the final transcription

    @Slot(object)
    def _on_stream_frame(self, frame: np.ndarray) -> None:
        if not self._streaming:
            return
        self._stream_chunks.append(frame)
        self._stream_len += len(frame)
        if not self._detect_tried and self._stream_len >= _DETECT_AFTER_S * SAMPLE_RATE:
            audio = np.concatenate(self._stream_chunks)
            self._stream_chunks = [audio]
            self._maybe_detect_language(audio)
        elif (
            self._stream_lang
            and self._stream_len - self._detected_at >= _REDETECT_EVERY_S * SAMPLE_RATE
        ):
            audio = np.concatenate(self._stream_chunks)
            self._stream_chunks = [audio]
            self._detected_at = self._stream_len
            recent = audio[-int(_REDETECT_WINDOW_S * SAMPLE_RATE) :]
            if has_speech(recent, _DETECT_MIN_VOICE_S):
                self._stream_lang = self._pick_language(recent) or self._stream_lang
        pending = self._stream_len - self._committed
        if pending < _STREAM_MIN_CHUNK_S * SAMPLE_RATE:
            return
        if self._stream_len - self._stream_checked_len < _STREAM_CHECK_S * SAMPLE_RATE:
            return
        self._stream_checked_len = self._stream_len
        audio = np.concatenate(self._stream_chunks)
        self._stream_chunks = [audio]
        self._maybe_detect_language(audio)
        segment = audio[self._committed :]
        cut = find_cut(segment, force=pending > _STREAM_MAX_CHUNK_S * SAMPLE_RATE)
        if cut is None:
            return
        self._transcribe_stream_chunk(segment[:cut])
        self._committed += cut

    def _maybe_detect_language(self, audio: np.ndarray) -> None:
        if self._detect_tried:
            return
        if (self._config.language or "auto") not in ("", "auto"):
            self._detect_tried = True
            return
        if not has_speech(audio, _DETECT_MIN_VOICE_S):
            return  # not enough speech yet; try again on the next frames
        self._detect_tried = True
        self._detected_at = self._stream_len
        self._stream_lang = self._pick_language(audio)
        if not self._stream_lang:
            return
        if self._stream_lang and self._should_route_english(self._stream_lang):
            try:
                english = self._ensure_english_engine()
                if english is not None:
                    english.load()  # warm it up while the user is talking
            except Exception:
                pass

    def _pick_language(self, audio: np.ndarray) -> str:
        """English if clearly English, otherwise Hebrew; "" if detection
        failed (then whisper auto-detects per call)."""
        if len(audio) < _DETECT_MIN_AUDIO_S * SAMPLE_RATE:
            return _DEFAULT_LANGUAGE
        if self._ensure_english_engine() is None:
            # No separate English model: everything goes to the main (Hebrew)
            # model, and a detect pass would only cost time.
            return _DEFAULT_LANGUAGE
        try:
            language, prob = self._detect_engine().detect_language(
                audio[: 30 * SAMPLE_RATE]
            )
        except Exception:
            return ""
        if not language:
            return ""
        # prob < 0: the engine didn't compute it (whisper.cpp; costs extra).
        if _is_english(language) and (prob < 0 or prob >= _ENGLISH_MIN_PROB):
            return "en"
        return _DEFAULT_LANGUAGE

    def _detect_engine(self):
        """The model that decides the language. A Hebrew fine-tune (ivrit)
        hears Hebrew in everything, so prefer the stock English/multilingual
        model when one is configured."""
        english = None
        if self._should_route_english("en"):
            english = self._ensure_english_engine()
        return english if english is not None else self._ensure_engine()

    def _transcribe_stream_chunk(self, chunk: np.ndarray) -> None:
        if not has_speech(chunk):
            return
        if self._detect_tried and self._stream_lang:
            # Re-detect per phrase (hidden while talking) so switching
            # language between sentences works; mostly-Hebrew phrases with
            # English words still come out Hebrew.
            self._stream_lang = self._pick_language(chunk) or self._stream_lang
        try:
            text = self._transcribe_segment(
                chunk, self._stream_prompt(), self._stream_lang
            )
        except Exception:
            # Don't drop the audio: let the final pass redo it in one go.
            self._streaming = False
            return
        text = _clean_chunk(text)
        if text:
            self._stream_texts.append(text)

    def _stream_prompt(self) -> str:
        base = self._config.initial_prompt or ""
        earlier = " ".join(self._stream_texts)[-_PROMPT_TAIL_CHARS:]
        return (base + " " + earlier).strip() if earlier else base

    @Slot()
    def _on_stream_cancel(self) -> None:
        self._reset_stream()
        self._arm_idle()

    # --- transcription ---

    def _transcribe_segment(
        self, audio: np.ndarray, prompt: str, language: str = ""
    ) -> str:
        """``language``: already-detected language for this recording; skips
        whisper's own auto-detect (and goes straight to the English model
        when that's what was spoken)."""
        if language and self._should_route_english(language):
            english = self._ensure_english_engine()
            if english is not None:
                try:
                    text = english.transcribe(
                        audio,
                        language="en",
                        beam_size=self._config.beam_size,
                        vad_filter=self._config.vad_filter,
                        initial_prompt=prompt,
                    ).text
                    if text.strip():
                        return text
                except Exception as e:
                    self.error.emit(f"English model failed: {e}")
        engine = self._ensure_engine()
        result = engine.transcribe(
            audio,
            language=language or self._config.language,
            beam_size=self._config.beam_size,
            vad_filter=self._config.vad_filter,
            initial_prompt=prompt,
        )
        text = result.text
        # If the main (Hebrew) model heard English, re-run through the
        # dedicated English model and prefer its output.
        if self._should_route_english(result.language):
            english = self._ensure_english_engine()
            if english is not None:
                try:
                    english_result = english.transcribe(
                        audio,
                        language="en",
                        beam_size=self._config.beam_size,
                        vad_filter=self._config.vad_filter,
                        initial_prompt=prompt,
                    )
                    if english_result.text.strip():
                        text = english_result.text
                except Exception as e:
                    # Keep the main model's text if the fallback fails.
                    self.error.emit(f"English model failed: {e}")
        return text

    @Slot(object)
    def _on_transcribe(self, buffer: np.ndarray) -> None:
        self._idle_timer.stop()
        self.started_processing.emit()
        try:
            if self._streaming and self._committed <= len(buffer):
                # Earlier phrases are already done; only the tail is left.
                tail = buffer[self._committed :]
                parts = list(self._stream_texts)
                if len(tail) >= SAMPLE_RATE // 4 and (not parts or has_speech(tail)):
                    last = self._transcribe_segment(
                        tail, self._stream_prompt(), self._stream_lang
                    )
                    last = _clean_chunk(last) if parts else last.strip()
                    if last:
                        parts.append(last)
                text = " ".join(parts)
            else:
                # Too short to have been detected while talking: detect now.
                # Same cost as whisper's own auto-detect, but Hebrew-biased.
                language = ""
                if (self._config.language or "auto") in ("", "auto"):
                    language = self._pick_language(buffer)
                text = self._transcribe_segment(
                    buffer, self._config.initial_prompt, language
                )
            self.text_ready.emit(text)
        except Exception as e:
            self.error.emit(f"Transcription failed: {e}")
        finally:
            self._reset_stream()
            self.finished_processing.emit()
            self._arm_idle()
