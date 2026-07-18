from __future__ import annotations

import atexit
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np


@dataclass
class TranscriptionResult:
    text: str
    language: str
    duration: float


_TIMESTAMP_RE = re.compile(r"^\[\d{2}:\d{2}:\d{2}\.\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}\.\d{3}\]\s*")

_SPAWNED_SERVERS: list[subprocess.Popen] = []


def _kill_spawned_servers() -> None:
    for proc in _SPAWNED_SERVERS:
        try:
            proc.terminate()
        except Exception:
            pass


atexit.register(_kill_spawned_servers)


def _find_binary(names: tuple[str, ...]) -> Optional[str]:
    for name in names:
        p = shutil.which(name)
        if p:
            return p
    for name in names:
        for prefix in ("/opt/homebrew/bin", "/usr/local/bin"):
            p = Path(prefix) / name
            if p.exists():
                return str(p)
    return None


def kill_stale_servers() -> None:
    """Terminate leftover whisper-server processes from a previous run.

    Matches only our whisper.cpp server binary path, so SuperWhisper's own
    bundled server is never touched. Safe to call at startup (before we spawn
    our own), which clears models orphaned by a crash or force-kill.
    """
    binary = _find_binary(("whisper-server",))
    if not binary:
        return
    try:
        subprocess.run(
            ["pkill", "-f", binary],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except Exception:
        pass


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _write_wav(path: Path, samples: np.ndarray, sample_rate: int = 16000) -> None:
    pcm = np.clip(samples, -1.0, 1.0)
    pcm = (pcm * 32767.0).astype(np.int16).tobytes()
    byte_rate = sample_rate * 2
    data_size = len(pcm)
    with open(path, "wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, byte_rate, 2, 16))
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        f.write(pcm)


def _multipart(fields: dict[str, str], file_field: str, filename: str, file_bytes: bytes) -> tuple[bytes, str]:
    boundary = f"----AuraWhisper{uuid.uuid4().hex}"
    lines: list[bytes] = []
    for name, value in fields.items():
        lines.append(f"--{boundary}\r\n".encode())
        lines.append(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    lines.append(f"--{boundary}\r\n".encode())
    lines.append(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
        f"Content-Type: audio/wav\r\n\r\n".encode()
    )
    lines.append(file_bytes)
    lines.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(lines), boundary


class WhisperEngine:
    """Persistent whisper.cpp server (model stays loaded, GPU-accelerated).

    Falls back to one-shot whisper-cli calls if whisper-server is missing.
    """

    def __init__(
        self,
        model_path: str,
        device: str = "auto",
        compute_type: str = "auto",
    ) -> None:
        self.model_path = model_path
        self.device = device
        self.compute_type = compute_type
        self._resolved_model: Optional[str] = None
        self._cli: Optional[str] = None
        self._server: Optional[subprocess.Popen] = None
        self._server_url: Optional[str] = None

    @property
    def is_loaded(self) -> bool:
        if self._server is not None and self._server.poll() is None:
            return True
        return self._resolved_model is not None and self._cli is not None

    def _resolve_model(self) -> str:
        path = Path(self.model_path)
        if not self.model_path or not path.exists():
            raise FileNotFoundError(
                f"Model path does not exist: {self.model_path!r}"
            )
        if path.is_dir():
            candidates = sorted(path.glob("ggml-*.bin"))
            if not candidates:
                raise FileNotFoundError(
                    f"No ggml-*.bin found in folder: {self.model_path}"
                )
            return str(candidates[0])
        return str(path)

    def load(self) -> None:
        if self.is_loaded:
            return
        self._resolved_model = self._resolve_model()
        self._start_server()
        if self._server is None:
            # Fall back to the one-shot CLI.
            self._cli = _find_binary(("whisper-cli", "whisper-cpp", "main"))
            if self._cli is None:
                raise FileNotFoundError(
                    "Neither whisper-server nor whisper-cli found. "
                    "Install with: brew install whisper-cpp"
                )

    def _start_server(self) -> None:
        binary = _find_binary(("whisper-server",))
        if binary is None:
            return
        port = _free_port()
        cmd = [
            binary,
            "-m", self._resolved_model or "",
            "--host", "127.0.0.1",
            "--port", str(port),
            "-l", "auto",
            "-t", str(max(1, os.cpu_count() or 4)),
        ]
        if self.device == "cpu":
            cmd.append("-ng")
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
        except OSError:
            return
        url = f"http://127.0.0.1:{port}"
        # Wait for the model to load (Metal load of large-v3-turbo takes ~1-3s).
        deadline = time.monotonic() + 60.0
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                return  # crashed; caller falls back to CLI
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    break
            except OSError:
                time.sleep(0.15)
        else:
            proc.terminate()
            return
        self._server = proc
        self._server_url = url
        _SPAWNED_SERVERS.append(proc)

    def shutdown(self) -> None:
        if self._server is not None:
            try:
                self._server.terminate()
            except Exception:
                pass
            if self._server in _SPAWNED_SERVERS:
                _SPAWNED_SERVERS.remove(self._server)
            self._server = None
            self._server_url = None

    def transcribe(
        self,
        audio: np.ndarray,
        language: Optional[str] = None,
        beam_size: int = 1,
        vad_filter: bool = True,
        initial_prompt: str = "",
    ) -> TranscriptionResult:
        self.load()
        if audio.size == 0:
            return TranscriptionResult(text="", language="", duration=0.0)

        audio = np.asarray(audio, dtype=np.float32).ravel()
        duration = float(len(audio) / 16000.0)
        lang = language if language and language != "auto" else "auto"

        if self._server is not None and self._server.poll() is None:
            text, detected = self._transcribe_server(
                audio, lang, initial_prompt, duration
            )
        else:
            text, detected = self._transcribe_cli(
                audio, lang, beam_size, initial_prompt, duration
            )

        resolved_lang = detected or (lang if lang != "auto" else "")
        return TranscriptionResult(text=text, language=resolved_lang, duration=duration)

    def _transcribe_server(
        self, audio: np.ndarray, lang: str, initial_prompt: str, duration: float
    ) -> tuple[str, str]:
        with tempfile.TemporaryDirectory(prefix="aura_whisper_") as tmp:
            wav_path = Path(tmp) / "input.wav"
            _write_wav(wav_path, audio)
            wav_bytes = wav_path.read_bytes()

        # verbose_json reports the language whisper actually used, which lets
        # the caller route English speech to a dedicated model. Skipping the
        # language-probability table keeps this free (no extra detect pass).
        fields = {
            "response_format": "verbose_json",
            "language": lang,
            "no_language_probabilities": "true",
        }
        if initial_prompt:
            fields["prompt"] = initial_prompt
        body, boundary = _multipart(fields, "file", "input.wav", wav_bytes)
        req = urllib.request.Request(
            f"{self._server_url}/inference",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        try:
            with urllib.request.urlopen(
                req, timeout=max(60.0, duration * 10 + 30)
            ) as resp:
                data = json.loads(resp.read().decode())
        except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
            raise RuntimeError(f"whisper-server request failed: {e}") from e
        if "error" in data:
            raise RuntimeError(f"whisper-server error: {data['error']}")
        text = " ".join((data.get("text") or "").split()).strip()
        detected = str(data.get("language") or "")
        return text, detected

    def _transcribe_cli(
        self,
        audio: np.ndarray,
        lang: str,
        beam_size: int,
        initial_prompt: str,
        duration: float,
    ) -> tuple[str, str]:
        with tempfile.TemporaryDirectory(prefix="aura_whisper_") as tmp:
            wav_path = Path(tmp) / "input.wav"
            _write_wav(wav_path, audio)

            cmd = [
                self._cli or "",
                "-m", self._resolved_model or "",
                "-f", str(wav_path),
                "-l", lang,
                "-t", str(max(1, os.cpu_count() or 4)),
                "-nt",
                "-np",
            ]
            if self.device == "cpu":
                cmd.append("-ng")
            if initial_prompt:
                cmd.extend(["--prompt", initial_prompt])
            if beam_size and beam_size > 1:
                cmd.extend(["-bs", str(beam_size)])

            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=max(60.0, duration * 10 + 30),
                )
            except subprocess.TimeoutExpired as e:
                raise RuntimeError(f"whisper-cli timed out: {e}") from e

            if proc.returncode != 0:
                err = (proc.stderr or proc.stdout or "").strip()[-400:]
                raise RuntimeError(f"whisper-cli failed ({proc.returncode}): {err}")

            detected = ""
            m = re.search(
                r"auto-detected language:\s*([a-zA-Z]{2,})", proc.stderr or ""
            )
            if m:
                detected = m.group(1).lower()

            raw = proc.stdout or ""
            lines = []
            for line in raw.splitlines():
                stripped = _TIMESTAMP_RE.sub("", line).strip()
                if stripped:
                    lines.append(stripped)
            return " ".join(lines).strip(), detected
