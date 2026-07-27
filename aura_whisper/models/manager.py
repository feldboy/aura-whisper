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


def model_kind(path: str) -> str | None:
    """Classify a model path as "ggml" (whisper.cpp) or "ctranslate2"
    (faster-whisper), or None if it doesn't look like either."""
    p = Path(path)
    if p.is_file():
        return "ggml"
    if p.is_dir():
        if any(p.glob("ggml-*.bin")):
            return "ggml"
        if (p / "model.bin").is_file() and (p / "config.json").is_file():
            return "ctranslate2"
    return None


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
        name="Large v3 (full)",
        filename="ggml-large-v3.bin",
        url="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3.bin",
        size_hint="3.1 GB",
        description="Non-turbo large v3 — marginally more accurate, slower and larger than Turbo.",
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
    CuratedModel(
        name="Base",
        filename="ggml-base.bin",
        url="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin",
        size_hint="148 MB",
        description="Very fast, low resource use; noticeably weaker than Small.",
    ),
    CuratedModel(
        name="Tiny",
        filename="ggml-tiny.bin",
        url="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.bin",
        size_hint="78 MB",
        description="Smallest and fastest option — quick drafts or very old hardware only.",
    ),
]

# CTranslate2/faster-whisper models. ``filename`` holds a sanitized folder
# name (used as both the on-disk directory name and the dict key that tracks
# install/download state); ``url`` holds the Hugging Face repo id, which
# ``faster_whisper.download_model`` accepts directly.
CURATED_CT2_MODELS: list[CuratedModel] = [
    CuratedModel(
        name="ivrit.ai Hebrew Turbo (CTranslate2)",
        filename="ivrit-ai__whisper-large-v3-turbo-ct2",
        url="ivrit-ai/whisper-large-v3-turbo-ct2",
        size_hint="~1.6 GB",
        description=(
            "Same ivrit.ai model as the ggml build above, packaged for "
            "faster-whisper/CTranslate2. Runs CPU-only on Apple Silicon (no "
            "Metal) — prefer the ggml build above unless you specifically "
            "need this format."
        ),
    ),
]


def scan_models(extra_paths: list[str] | None = None) -> list[InstalledModel]:
    """Find whisper.cpp ggml models and CTranslate2 model folders in known
    locations."""
    found: dict[str, InstalledModel] = {}

    def add_file(path: Path, source: str) -> None:
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

    def add_ct2_dirs(base: Path, source: str) -> None:
        # A CTranslate2 export can sit at any depth under ``base`` (e.g.
        # MODELS_DIR/ct2/<repo>/), so search recursively rather than
        # assuming a fixed layout.
        try:
            for model_bin in sorted(base.rglob("model.bin")):
                model_dir = model_bin.parent
                resolved = str(model_dir.resolve())
                if resolved in found or not (model_dir / "config.json").is_file():
                    continue
                size = sum(
                    f.stat().st_size for f in model_dir.glob("*") if f.is_file()
                )
                found[resolved] = InstalledModel(
                    name=model_dir.name, path=resolved, size_bytes=size, source=source
                )
        except OSError:
            pass

    if MODELS_DIR.exists():
        for p in sorted(MODELS_DIR.glob("*.bin")):
            add_file(p, "AuraWhisper")
        add_ct2_dirs(MODELS_DIR, "AuraWhisper")
    if SUPERWHISPER_DIR.exists():
        for p in sorted(SUPERWHISPER_DIR.glob("ggml-*.bin")):
            add_file(p, "SuperWhisper")
    for raw in extra_paths or []:
        p = Path(raw)
        if p.is_file():
            add_file(p, "Custom")
        elif p.is_dir():
            for child in sorted(p.glob("*.bin")):
                add_file(child, "Custom")
            add_ct2_dirs(p, "Custom")
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


class FasterWhisperDownloader(QObject):
    """Downloads one CTranslate2/faster-whisper model (a Hugging Face repo
    snapshot) on a QThread. ``huggingface_hub``'s snapshot download doesn't
    expose per-byte progress, so callers show an indeterminate spinner for
    the duration instead of a percentage."""

    finished = Signal(str)  # final directory on disk
    error = Signal(str)

    def __init__(self, model: CuratedModel) -> None:
        super().__init__()
        self.model = model
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
        from faster_whisper import download_model

        dest = MODELS_DIR / "ct2" / self.model.filename
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            path = download_model(self.model.url, output_dir=str(dest))
            self.finished.emit(path)
        except Exception as e:
            self.error.emit(f"Download failed: {e}")
