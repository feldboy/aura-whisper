"""Natural Hebrew read-aloud with Kokoro (Shaul voice), fully local.

Phonikud adds nikud and turns the text into phonemes; the Kokoro ONNX model
turns phonemes into audio. Text is synthesized sentence by sentence on a
background thread and played through sounddevice, so reading starts after
the first sentence and can be paused or re-paced at any time.

The model and voice are licensed for non-commercial use only.
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal

from aura_whisper.config import MODELS_DIR
from aura_whisper.speech.english import LATIN_WORD, mixed_phonemes
from aura_whisper.speech.speaker import clamp_speed

KOKORO_DIR = MODELS_DIR / "tts" / "kokoro-hebrew"
SAMPLE_RATE = 24000
VOICE = "he_shaul"
# Kokoro's own speed input slurs and drops sounds when sped up (Whisper
# misheard 3/25 words at 1.7x), so faster speeds are synthesized at the
# natural pace and time-compressed instead (pitch unchanged; 0/25 at 2.5x).
MODEL_MAX_SPEED = 1.0
# Audio buffer size. PortAudio's default here is ~15 frames (0.6 ms), which
# starves whenever Python holds the GIL (Qt, Phonikud) -> crackling and
# stutter. ~85 ms buffers play smoothly even under load.
BLOCK_FRAMES = 2048
MAX_TOKENS = 510
SENTENCE_PAUSE_S = 0.15
# Long sentences are split further so the first audio arrives quickly.
MAX_CHUNK_CHARS = 220

_HF = "https://huggingface.co"
# (local name, url, exact size in bytes)
KOKORO_FILES = [
    (
        "kokoro.onnx",
        f"{_HF}/thewh1teagle/kokoro-hebrew-nc/resolve/main/kokoro.onnx",
        325505393,
    ),
    (
        "voices-hebrew.bin",
        f"{_HF}/thewh1teagle/kokoro-hebrew-nc/resolve/main/voices-hebrew.bin",
        522510,
    ),
    (
        "config.json",
        f"{_HF}/thewh1teagle/kokoro-hebrew-nc/resolve/main/config.json",
        2526,
    ),
    (
        "phonikud.onnx",
        f"{_HF}/thewh1teagle/phonikud-onnx/resolve/main/phonikud-1.0.int8.onnx",
        307844158,
    ),
    # Phonikud's tokenizer; bundled so loading never touches the network.
    (
        "phonikud-tokenizer.json",
        f"{_HF}/dicta-il/dictabert-large-char-menaked/resolve/main/tokenizer.json",
        18016,
    ),
]
DOWNLOAD_SIZE = sum(size for _, _, size in KOKORO_FILES)


def kokoro_installed(model_dir: Path = KOKORO_DIR) -> bool:
    return all(
        (model_dir / name).is_file() and (model_dir / name).stat().st_size == size
        for name, _, size in KOKORO_FILES
    )


def split_sentences(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Sentences (then clauses, then word runs) of at most ``max_chars``."""
    chunks: list[str] = []
    for sentence in re.split(r"(?<=[.!?…:;])\s+|\n+", text):
        sentence = " ".join(sentence.split())
        if not sentence:
            continue
        if len(sentence) <= max_chars:
            chunks.append(sentence)
            continue
        current = ""
        for part in re.split(r"(?<=,)\s+|\s+", sentence):
            if current and len(current) + 1 + len(part) > max_chars:
                chunks.append(current)
                current = part
            else:
                current = f"{current} {part}" if current else part
        if current:
            chunks.append(current)
    return chunks


def time_stretch(audio: np.ndarray, factor: float, sr: int = SAMPLE_RATE) -> np.ndarray:
    """Speed speech up by ``factor`` without changing its pitch (WSOLA)."""
    win = int(0.03 * sr)
    if factor <= 1.0 or len(audio) < 4 * win:
        return audio
    hop_out = win // 2
    hop_in = hop_out * factor
    tol = int(0.01 * sr)
    window = np.hanning(win).astype(np.float32)
    out = np.zeros(int(len(audio) / factor) + 2 * win, dtype=np.float32)
    norm = np.zeros_like(out)
    pos_in, o = 0.0, 0
    prev: np.ndarray | None = None
    while True:
        center = int(pos_in)
        if prev is None:
            start = center
        else:
            # Pick the nearby segment that best continues what was just
            # written, so the overlapped waveforms line up in phase.
            lo = max(0, center - tol)
            hi = min(len(audio) - win, center + tol)
            if hi < lo:
                break
            corr = np.correlate(audio[lo : hi + win], prev, mode="valid")
            start = lo + int(np.argmax(corr))
        if start + win > len(audio) or o + win > len(out):
            break
        out[o : o + win] += audio[start : start + win] * window
        norm[o : o + win] += window
        prev = audio[start + hop_out : start + hop_out + win]
        if len(prev) < win:
            break
        o += hop_out
        pos_in += hop_in
    norm[norm < 1e-3] = 1.0
    return (out / norm)[: o + hop_out]


def _load_phonikud(model_dir: Path):
    """Phonikud with its tokenizer read from disk. phonikud_onnx fetches the
    tokenizer from Hugging Face by name, so swap in a local loader while it
    initializes."""
    from phonikud_onnx import Phonikud
    from phonikud_onnx import model as pk_model
    from tokenizers import Tokenizer

    tokenizer_path = str(model_dir / "phonikud-tokenizer.json")

    class _LocalTokenizer:
        @staticmethod
        def from_pretrained(_name: str) -> Tokenizer:
            return Tokenizer.from_file(tokenizer_path)

    original = pk_model.Tokenizer
    pk_model.Tokenizer = _LocalTokenizer
    try:
        return Phonikud(str(model_dir / "phonikud.onnx"))
    finally:
        pk_model.Tokenizer = original


class _Engine:
    """The loaded models (~700 MB in memory)."""

    def __init__(self, model_dir: Path) -> None:
        import onnxruntime as rt

        self.sess = rt.InferenceSession(
            str(model_dir / "kokoro.onnx"), providers=["CPUExecutionProvider"]
        )
        self.phonikud = _load_phonikud(model_dir)
        config = json.loads((model_dir / "config.json").read_text())
        self.vocab: dict[str, int] = config["vocab"]
        self.style = np.load(model_dir / "voices-hebrew.bin")[VOICE]

    def _hebrew_phonemes(self, text: str) -> str:
        from phonikud import phonemize

        # "ה-GitHub": the prefix hyphen would otherwise glue onto the word.
        text = text.replace("-", " ")
        if not re.search(r"[\u0590-\u05FF0-9]", text):
            return ""  # punctuation/spaces between English words
        return phonemize(self.phonikud.add_diacritics(text))

    def synthesize(self, text: str, speed: float) -> np.ndarray:
        if LATIN_WORD.search(text):
            phonemes = mixed_phonemes(text, self._hebrew_phonemes)
        else:
            phonemes = self._hebrew_phonemes(text)
        tokens = [self.vocab[c] for c in phonemes if c in self.vocab][:MAX_TOKENS]
        if not tokens:
            return np.zeros(0, dtype=np.float32)
        out = self.sess.run(
            None,
            {
                "input_ids": np.array([[0, *tokens, 0]], dtype=np.int64),
                "style": self.style[len(tokens) - 1],
                "speed": np.array([min(speed, MODEL_MAX_SPEED)], dtype=np.float32),
            },
        )
        audio = np.asarray(out[0], dtype=np.float32).ravel()
        if speed > MODEL_MAX_SPEED:
            audio = time_stretch(audio, speed / MODEL_MAX_SPEED)
        pause = np.zeros(int(SENTENCE_PAUSE_S / speed * SAMPLE_RATE), np.float32)
        return np.concatenate([audio, pause])


class KokoroSpeaker:
    """Same interface as ``Speaker``: speak / pause / resume / speed / stop."""

    def __init__(self, model_dir: Path = KOKORO_DIR) -> None:
        self._model_dir = model_dir
        self._engine: _Engine | None = None
        self._load_lock = threading.Lock()
        self._lock = threading.Lock()
        self._stream = None
        self._gen = 0
        self._sentences: list[str] = []
        self._speed = 1.0
        self._paused = False
        # Synthesized sentences waiting to play: (sentence index, samples).
        self._chunks: deque[tuple[int, np.ndarray]] = deque()
        self._current: np.ndarray | None = None
        self._current_idx = -1
        self._pos = 0
        self._synth_done = True
        self._last_used = time.monotonic()
        self.error: str | None = None

    # --- model lifetime ---

    def _load(self) -> _Engine:
        with self._load_lock:
            if self._engine is None:
                self._engine = _Engine(self._model_dir)
            return self._engine

    def unload_if_idle(self, minutes: int) -> None:
        if (
            minutes > 0
            and self._engine is not None
            and not self.is_active()
            and time.monotonic() - self._last_used > minutes * 60
        ):
            with self._load_lock:
                self._engine = None

    # --- state ---

    def is_active(self) -> bool:
        """Speaking, paused, or still preparing the next sentence."""
        if self._paused:
            return True
        with self._lock:
            playing = self._current is not None and self._pos < len(self._current)
            return playing or bool(self._chunks) or not self._synth_done

    def is_speaking(self) -> bool:
        return self.is_active() and not self._paused

    def is_paused(self) -> bool:
        return self._paused

    @property
    def speed(self) -> float:
        return self._speed

    # --- control ---

    def speak(self, text: str, speed: float) -> bool:
        self.stop()
        sentences = split_sentences(text)
        if not sentences:
            return False
        self.error = None
        self._sentences = sentences
        self._speed = clamp_speed(speed)
        self._last_used = time.monotonic()
        try:
            import sounddevice as sd

            self._stream = sd.OutputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=BLOCK_FRAMES,
                latency="high",
                callback=self._fill,
            )
            self._stream.start()
        except Exception as e:
            self.error = f"audio output failed: {e}"
            self._stream = None
            return False
        self._start_synthesis(0)
        return True

    def set_speed(self, speed: float) -> None:
        speed = clamp_speed(speed)
        if speed == self._speed:
            return
        self._speed = speed
        if not self.is_active():
            return
        with self._lock:
            # Keep the current sentence playing; its re-paced version is
            # swapped in at the same relative point once it's ready.
            self._chunks.clear()
            start = max(self._current_idx, 0)
        self._start_synthesis(start)

    def pause(self) -> None:
        if self.is_active():
            self._paused = True

    def resume(self) -> None:
        self._paused = False

    def toggle_pause(self) -> None:
        if self._paused:
            self.resume()
        else:
            self.pause()

    def stop(self) -> None:
        with self._lock:
            self._gen += 1
            self._chunks.clear()
            self._current = None
            self._current_idx = -1
            self._pos = 0
            self._synth_done = True
        self._paused = False
        if self._stream is not None:
            try:
                self._stream.abort()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self._last_used = time.monotonic()

    # --- synthesis thread ---

    def _start_synthesis(self, start: int) -> None:
        with self._lock:
            self._gen += 1
            gen = self._gen
            self._synth_done = False
        threading.Thread(
            target=self._synthesize, args=(gen, start, self._speed), daemon=True
        ).start()

    def _synthesize(self, gen: int, start: int, speed: float) -> None:
        try:
            engine = self._load()
            for idx in range(start, len(self._sentences)):
                if gen != self._gen:
                    return
                audio = engine.synthesize(self._sentences[idx], speed)
                with self._lock:
                    if gen != self._gen:
                        return
                    self._chunks.append((idx, audio))
        except Exception as e:
            self.error = f"Kokoro failed: {e}"
        finally:
            with self._lock:
                if gen == self._gen:
                    self._synth_done = True

    # --- audio callback (sounddevice thread) ---

    def _fill(self, outdata, frames, _time, _status) -> None:
        out = outdata[:, 0]
        out.fill(0)
        if self._paused:
            return
        n = 0
        with self._lock:
            while n < frames:
                if self._chunks and self._chunks[0][0] == self._current_idx:
                    # Re-paced version of the sentence that's playing.
                    _, audio = self._chunks.popleft()
                    done = self._pos / max(len(self._current), 1)
                    self._current = audio
                    self._pos = int(done * len(audio))
                if self._current is None or self._pos >= len(self._current):
                    if not self._chunks:
                        break
                    self._current_idx, self._current = self._chunks.popleft()
                    self._pos = 0
                take = min(frames - n, len(self._current) - self._pos)
                out[n : n + take] = self._current[self._pos : self._pos + take]
                self._pos += take
                n += take


class KokoroDownloader(QObject):
    """Downloads the Kokoro + Phonikud model files on a QThread."""

    progress = Signal(int, int)  # bytes_done, bytes_total
    finished = Signal(str)  # model directory
    error = Signal(str)

    def __init__(self, model_dir: Path = KOKORO_DIR) -> None:
        super().__init__()
        self._model_dir = model_dir
        self._thread: QThread | None = None

    def start(self) -> None:
        self._thread = QThread()
        self.moveToThread(self._thread)
        self._thread.started.connect(self._run)
        self.finished.connect(self._thread.quit)
        self.error.connect(self._thread.quit)
        self._thread.finished.connect(self.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _run(self) -> None:
        done = 0
        part: Path | None = None
        try:
            self._model_dir.mkdir(parents=True, exist_ok=True)
            for name, url, size in KOKORO_FILES:
                dest = self._model_dir / name
                if dest.is_file() and dest.stat().st_size == size:
                    done += size
                    self.progress.emit(done, DOWNLOAD_SIZE)
                    continue
                part = dest.with_suffix(dest.suffix + ".part")
                req = urllib.request.Request(
                    url, headers={"User-Agent": "AuraWhisper/0.2"}
                )
                got = 0
                with urllib.request.urlopen(req, timeout=30) as resp, open(part, "wb") as f:
                    while chunk := resp.read(1024 * 256):
                        f.write(chunk)
                        got += len(chunk)
                        self.progress.emit(done + got, DOWNLOAD_SIZE)
                if got != size:
                    raise OSError(f"{name}: incomplete download ({got}/{size} bytes)")
                part.rename(dest)
                part = None
                done += size
            self.finished.emit(str(self._model_dir))
        except (urllib.error.URLError, OSError) as e:
            if part is not None:
                part.unlink(missing_ok=True)
            self.error.emit(f"Download failed: {e}")
