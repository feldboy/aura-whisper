from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from aura_whisper.config import MODELS_DIR


SUPERWHISPER_DIR = Path.home() / "Library" / "Application Support" / "superwhisper"


@dataclass
class InstalledModel:
    name: str
    path: str
    size_bytes: int
    source: str  # "AuraWhisper" | "SuperWhisper" | "Custom"


@dataclass
class CuratedModel:
    name: str
    filename: str
    url: str
    size_hint: str
    description: str


CURATED_MODELS: list[CuratedModel] = [
    CuratedModel(
        name="Large v3 Turbo",
        filename="ggml-large-v3-turbo.bin",
        url="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin",
        size_hint="1.6 GB",
        description="Best overall quality for Hebrew + English. Recommended.",
    ),
    CuratedModel(
        name="Large v3 Turbo (q5_0)",
        filename="ggml-large-v3-turbo-q5_0.bin",
        url="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo-q5_0.bin",
        size_hint="574 MB",
        description="Quantized turbo — near-identical quality, much smaller and faster.",
    ),
    CuratedModel(
        name="ivrit.ai Hebrew Turbo",
        filename="ggml-ivrit-large-v3-turbo.bin",
        url="https://huggingface.co/ivrit-ai/whisper-large-v3-turbo-ggml/resolve/main/ggml-model.bin",
        size_hint="1.6 GB",
        description="Fine-tuned on Hebrew speech (ivrit.ai) — best for Hebrew-heavy dictation.",
    ),
    CuratedModel(
        name="Medium",
        filename="ggml-medium.bin",
        url="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.bin",
        size_hint="1.5 GB",
        description="Good multilingual quality, slower than turbo.",
    ),
    CuratedModel(
        name="Small",
        filename="ggml-small.bin",
        url="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin",
        size_hint="488 MB",
        description="Fast and light; okay English, weaker Hebrew.",
    ),
]


def scan_models(extra_paths: list[str] | None = None) -> list[InstalledModel]:
    """Find whisper.cpp ggml models in known locations."""
    found: dict[str, InstalledModel] = {}

    def add(path: Path, source: str) -> None:
        try:
            resolved = str(path.resolve())
            if resolved in found or not path.is_file():
                return
            found[resolved] = InstalledModel(
                name=path.stem.replace("ggml-", ""),
                path=resolved,
                size_bytes=path.stat().st_size,
                source=source,
            )
        except OSError:
            pass

    if MODELS_DIR.exists():
        for p in sorted(MODELS_DIR.glob("*.bin")):
            add(p, "AuraWhisper")
    if SUPERWHISPER_DIR.exists():
        for p in sorted(SUPERWHISPER_DIR.glob("ggml-*.bin")):
            add(p, "SuperWhisper")
    for raw in extra_paths or []:
        p = Path(raw)
        if p.is_file():
            add(p, "Custom")
        elif p.is_dir():
            for child in sorted(p.glob("*.bin")):
                add(child, "Custom")
    return list(found.values())


def format_size(size_bytes: int) -> str:
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} GB"


class ModelDownloader(QObject):
    """Downloads one curated model on a QThread. One instance per download."""

    progress = Signal(int, int)  # bytes_done, bytes_total (total may be 0)
    finished = Signal(str)  # final path on disk
    error = Signal(str)

    def __init__(self, model: CuratedModel) -> None:
        super().__init__()
        self.model = model
        self._cancelled = False
        self._thread: QThread | None = None

    def start(self) -> None:
        self._thread = QThread()
        self.moveToThread(self._thread)
        self._thread.started.connect(self._run)
        self.finished.connect(self._thread.quit)
        self.error.connect(self._thread.quit)
        # Clean up only once the event loop has fully stopped, so the QThread
        # is never destroyed while still running (which would abort the app).
        self._thread.finished.connect(self.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def cancel(self) -> None:
        self._cancelled = True

    def _run(self) -> None:
        dest = MODELS_DIR / self.model.filename
        part = dest.with_suffix(dest.suffix + ".part")
        try:
            MODELS_DIR.mkdir(parents=True, exist_ok=True)
            req = urllib.request.Request(
                self.model.url, headers={"User-Agent": "AuraWhisper/0.2"}
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                total = int(resp.headers.get("Content-Length") or 0)
                done = 0
                with open(part, "wb") as f:
                    while True:
                        if self._cancelled:
                            raise InterruptedError("Download cancelled")
                        chunk = resp.read(1024 * 256)
                        if not chunk:
                            break
                        f.write(chunk)
                        done += len(chunk)
                        self.progress.emit(done, total)
            if total and done != total:
                raise OSError(f"Incomplete download ({done}/{total} bytes)")
            part.rename(dest)
            self.finished.emit(str(dest))
        except InterruptedError:
            part.unlink(missing_ok=True)
            self.error.emit("Download cancelled")
        except (urllib.error.URLError, OSError) as e:
            part.unlink(missing_ok=True)
            self.error.emit(f"Download failed: {e}")
