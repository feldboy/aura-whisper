from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from aura_whisper.models.manager import (
    CURATED_CT2_MODELS,
    CURATED_MODELS,
    CuratedModel,
    FasterWhisperDownloader,
    ModelDownloader,
    format_size,
    scan_models,
)
from aura_whisper.ui.ui_kit import (
    hint,
    page_header,
    panel_section,
    pill,
    scroll_page,
    section,
)

# Bare "org/repo" Hugging Face id, e.g. "ivrit-ai/whisper-large-v3-turbo-ct2" —
# as opposed to a direct ggml .bin URL (which has a scheme).
_HF_REPO_RE = re.compile(r"^[\w.\-]+/[\w.\-]+$")


class ModelsPage(QWidget):
    """Settings tab: installed whisper models + curated downloads."""

    model_selected = Signal(str)  # absolute path

    def __init__(
        self,
        current_model_path: str,
        custom_model_paths: list[str] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._current_path = current_model_path
        # Manually-added/URL-downloaded model files, kept so they stay listed
        # even after the active model is switched away from them.
        self._custom_paths: list[str] = list(
            dict.fromkeys(custom_model_paths or [])
        )
        self._downloaders: dict[str, ModelDownloader | FasterWhisperDownloader] = {}
        self._url_downloader: ModelDownloader | FasterWhisperDownloader | None = None
        # Keep finished/failed downloaders alive until their thread is torn
        # down, so PySide never GCs a still-running worker.
        self._retired: list[ModelDownloader | FasterWhisperDownloader] = []

        # --- active model ---
        self._installed_combo = QComboBox(self)
        self._installed_combo.setMinimumHeight(32)
        self._installed_combo.currentIndexChanged.connect(
            self._on_installed_changed
        )

        add_btn = QPushButton("Add model file…", self)
        add_btn.setObjectName("secondaryBtn")
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.clicked.connect(self._add_file)

        active_bottom = QHBoxLayout()
        active_bottom.setContentsMargins(0, 0, 0, 0)
        active_bottom.setSpacing(12)
        active_hint = hint(
            "The active model is loaded for instant transcription.", self
        )
        active_bottom.addWidget(active_hint, 1)
        active_bottom.addWidget(add_btn, 0, Qt.AlignRight)

        # --- advanced path ---
        self._path_edit = QLineEdit(current_model_path, self)
        self._path_edit.setPlaceholderText("Path to a ggml-*.bin file or folder")
        self._path_edit.editingFinished.connect(
            lambda: self._select(self._path_edit.text().strip(), refresh=False)
        )

        # --- curated download rows ---
        self._build_curated_rows()

        # --- add a model from an arbitrary URL or HF repo id ---
        self._url_input = QLineEdit(self)
        self._url_input.setPlaceholderText(
            "A ggml .bin URL, or a Hugging Face org/repo id (CTranslate2)"
        )
        self._url_download_btn = QPushButton("Download", self)
        self._url_download_btn.setObjectName("downloadBtn")
        self._url_download_btn.setCursor(Qt.PointingHandCursor)
        self._url_download_btn.clicked.connect(self._start_url_download)
        url_row = QHBoxLayout()
        url_row.setContentsMargins(0, 0, 0, 0)
        url_row.setSpacing(8)
        url_row.addWidget(self._url_input, 1)
        url_row.addWidget(self._url_download_btn)
        self._url_progress = QProgressBar(self)
        self._url_progress.setVisible(False)
        self._url_progress.setFixedHeight(6)
        self._url_progress.setTextVisible(False)

        content = QWidget(self)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 24, 28, 28)
        layout.setSpacing(22)
        layout.addWidget(
            page_header(
                content,
                "Models",
                "Configure your local speech-recognition models for offline "
                "transcription.",
                icon="package",
            )
        )
        layout.addWidget(
            panel_section(
                content,
                "Active model",
                [self._installed_combo, active_bottom],
            )
        )
        layout.addWidget(
            section(content, "Downloaded models", self._curated_row_widgets)
        )
        layout.addWidget(
            section(
                content,
                "Downloaded models (CTranslate2 / faster-whisper)",
                self._curated_ct2_row_widgets,
            )
        )
        layout.addWidget(
            panel_section(
                content,
                "Add a model from a URL",
                [url_row, self._url_progress],
                "Paste a direct .bin link for a whisper.cpp model, or an "
                "org/repo Hugging Face id for a CTranslate2/faster-whisper "
                "model that isn't in the lists above.",
            )
        )
        layout.addWidget(
            panel_section(
                content,
                "Model path (advanced)",
                [self._path_edit],
                "Manually setting paths may cause instability if model "
                "versions mismatch.",
            )
        )
        layout.addStretch(1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll_page(content))

        self.refresh()

    @property
    def current_model_path(self) -> str:
        return self._current_path

    @property
    def custom_model_paths(self) -> list[str]:
        return list(self._custom_paths)

    def _extra_scan_paths(self) -> list[str]:
        paths = list(self._custom_paths)
        if self._current_path and self._current_path not in paths:
            paths.append(self._current_path)
        return paths

    def refresh(self) -> None:
        models = scan_models(self._extra_scan_paths())
        combo = self._installed_combo
        combo.blockSignals(True)
        combo.clear()
        active_index = -1
        for i, m in enumerate(models):
            label = f"{m.name}  ·  {format_size(m.size_bytes)}  ·  {m.source}"
            combo.addItem(label, m.path)
            combo.setItemData(i, m.path, Qt.ToolTipRole)
            if self._current_path and str(Path(m.path)) == str(
                Path(self._current_path)
            ):
                active_index = i
        if active_index >= 0:
            combo.setCurrentIndex(active_index)
        elif self._current_path:
            # Active model lives outside the scanned folders — show it anyway.
            combo.addItem(f"{Path(self._current_path).stem}  ·  current", self._current_path)
            combo.setCurrentIndex(combo.count() - 1)
        elif combo.count() == 0:
            combo.addItem("No models installed — download one below", "")
            combo.setCurrentIndex(0)
        combo.blockSignals(False)
        self._update_curated_states()

    def _on_installed_changed(self, index: int) -> None:
        if index < 0:
            return
        path = self._installed_combo.itemData(index)
        if path:
            self._select(path, refresh=False)

    def _select(self, path: str, refresh: bool = True) -> None:
        self._current_path = path
        self._path_edit.setText(path)
        self.model_selected.emit(path)
        if refresh:
            self.refresh()

    def _add_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select a ggml Whisper model (.bin)",
            self._current_path or str(Path.home()),
            "Whisper models (ggml-*.bin *.bin);;All files (*)",
        )
        if path:
            self._remember_custom_path(path)
            self._select(path)

    def _remember_custom_path(self, path: str) -> None:
        """Keep a manually-added/downloaded model listed even after the
        active model is switched to something else."""
        resolved = str(Path(path).resolve())
        if resolved not in self._custom_paths:
            self._custom_paths.append(resolved)

    # --- curated downloads ---

    def _build_curated_rows(self) -> None:
        self._curated_rows: dict[str, dict] = {}
        self._curated_row_widgets = self._build_rows(CURATED_MODELS, ModelDownloader)
        self._curated_ct2_row_widgets = self._build_rows(
            CURATED_CT2_MODELS, FasterWhisperDownloader
        )

    def _build_rows(self, models: list[CuratedModel], downloader_cls) -> list[QWidget]:
        widgets: list[QWidget] = []
        for cm in models:
            row = QWidget(self)
            row.setProperty("settingRow", True)
            h = QHBoxLayout(row)
            h.setContentsMargins(16, 12, 16, 12)
            h.setSpacing(12)

            left = QVBoxLayout()
            left.setContentsMargins(0, 0, 0, 0)
            left.setSpacing(3)

            title_line = QHBoxLayout()
            title_line.setContentsMargins(0, 0, 0, 0)
            title_line.setSpacing(8)
            name = QLabel(cm.name, row)
            name.setProperty("rowTitle", True)
            title_line.addWidget(name)
            if "recommend" in cm.description.lower():
                title_line.addWidget(pill("Recommended", "accent", row))
            size_lbl = QLabel(f"· {cm.size_hint}", row)
            size_lbl.setProperty("rowSubtitle", True)
            title_line.addWidget(size_lbl)
            title_line.addStretch(1)
            left.addLayout(title_line)

            desc = QLabel(cm.description, row)
            desc.setProperty("rowSubtitle", True)
            desc.setToolTip(cm.description)
            desc.setWordWrap(True)
            left.addWidget(desc)

            progress = QProgressBar(row)
            progress.setVisible(False)
            progress.setFixedHeight(6)
            progress.setTextVisible(False)
            left.addWidget(progress)

            h.addLayout(left, 1)

            btn = QPushButton("Download", row)
            btn.setObjectName("downloadBtn")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(
                lambda _=False, c=cm, d=downloader_cls: self._start_download(c, d)
            )
            installed_pill = pill("Installed", "success", row)
            installed_pill.setVisible(False)

            right = QVBoxLayout()
            right.setContentsMargins(0, 0, 0, 0)
            right.addWidget(btn, 0, Qt.AlignRight | Qt.AlignVCenter)
            right.addWidget(installed_pill, 0, Qt.AlignRight | Qt.AlignVCenter)
            h.addLayout(right, 0)

            widgets.append(row)
            self._curated_rows[cm.filename] = {
                "button": btn,
                "progress": progress,
                "pill": installed_pill,
                "model": cm,
            }
        return widgets

    def _installed_filenames(self) -> set[str]:
        return {
            Path(m.path).name for m in scan_models(self._extra_scan_paths())
        }

    def _update_curated_states(self) -> None:
        installed = self._installed_filenames()
        for filename, widgets in self._curated_rows.items():
            if filename in self._downloaders:
                continue
            if filename in installed:
                widgets["button"].setVisible(False)
                widgets["pill"].setVisible(True)
            else:
                widgets["pill"].setVisible(False)
                widgets["button"].setVisible(True)
                widgets["button"].setText("Download")
                widgets["button"].setEnabled(True)

    def _start_download(self, cm: CuratedModel, downloader_cls) -> None:
        widgets = self._curated_rows[cm.filename]
        widgets["button"].setText("Downloading…")
        widgets["button"].setEnabled(False)
        widgets["progress"].setVisible(True)
        widgets["progress"].setRange(0, 0)

        dl = downloader_cls(cm)
        self._downloaders[cm.filename] = dl
        # Connect to bound methods (not lambdas). A lambda has no receiver
        # QObject, so Qt falls back to a *direct* connection and the slot would
        # run on the download thread — touching Qt widgets off the main thread
        # crashes the app. Bound methods of this QWidget resolve to a queued
        # (main-thread) connection instead.
        # FasterWhisperDownloader has no fine-grained progress signal (a HF
        # snapshot download doesn't expose per-byte progress) — only
        # ModelDownloader does, so the bar just stays indeterminate for it.
        if hasattr(dl, "progress"):
            dl.progress.connect(self._on_progress)
        dl.finished.connect(self._on_downloaded)
        dl.error.connect(self._on_download_error)
        dl.start()

    def _sender_filename(self) -> str | None:
        dl = self.sender()
        model = getattr(dl, "model", None)
        return getattr(model, "filename", None)

    def _retire(self, filename: str) -> None:
        dl = self._downloaders.pop(filename, None)
        if dl is not None:
            self._retired.append(dl)

    def _on_progress(self, done: int, total: int) -> None:
        filename = self._sender_filename()
        if filename is None:
            return
        progress = self._curated_rows[filename]["progress"]
        if total > 0:
            progress.setRange(0, 100)
            progress.setValue(int(done * 100 / total))

    def _on_downloaded(self, path: str) -> None:
        filename = self._sender_filename()
        if filename is None:
            return
        self._retire(filename)
        self._curated_rows[filename]["progress"].setVisible(False)
        self._select(path)

    def _on_download_error(self, message: str) -> None:
        filename = self._sender_filename()
        if filename is None:
            return
        self._retire(filename)
        widgets = self._curated_rows[filename]
        widgets["progress"].setVisible(False)
        widgets["button"].setText("Retry download")
        widgets["button"].setEnabled(True)
        widgets["button"].setToolTip(message)

    # --- download-by-URL (e.g. a model found on Hugging Face) ---

    def _start_url_download(self) -> None:
        text = self._url_input.text().strip()
        if not text or self._url_downloader is not None:
            return

        if text.startswith(("http://", "https://")):
            filename = Path(urlparse(text).path).name or "custom-model.bin"
            cm = CuratedModel(
                name=Path(filename).stem,
                filename=filename,
                url=text,
                size_hint="",
                description="Custom URL download",
            )
            downloader_cls = ModelDownloader
        elif _HF_REPO_RE.match(text):
            cm = CuratedModel(
                name=text,
                filename=text.replace("/", "__"),
                url=text,
                size_hint="",
                description="Custom Hugging Face (CTranslate2) download",
            )
            downloader_cls = FasterWhisperDownloader
        else:
            self._url_download_btn.setToolTip(
                "Enter a direct .bin URL, or a Hugging Face org/repo id."
            )
            return

        self._url_download_btn.setText("Downloading…")
        self._url_download_btn.setEnabled(False)
        self._url_input.setEnabled(False)
        self._url_progress.setVisible(True)
        self._url_progress.setRange(0, 0)

        dl = downloader_cls(cm)
        self._url_downloader = dl
        if hasattr(dl, "progress"):
            dl.progress.connect(self._on_url_progress)
        dl.finished.connect(self._on_url_downloaded)
        dl.error.connect(self._on_url_download_error)
        dl.start()

    def _on_url_progress(self, done: int, total: int) -> None:
        if total > 0:
            self._url_progress.setRange(0, 100)
            self._url_progress.setValue(int(done * 100 / total))

    def _on_url_downloaded(self, path: str) -> None:
        self._retired.append(self._url_downloader)
        self._url_downloader = None
        self._reset_url_row()
        self._url_input.clear()
        self._remember_custom_path(path)
        self._select(path)

    def _on_url_download_error(self, message: str) -> None:
        self._retired.append(self._url_downloader)
        self._url_downloader = None
        self._reset_url_row()
        self._url_download_btn.setToolTip(message)

    def _reset_url_row(self) -> None:
        self._url_progress.setVisible(False)
        self._url_download_btn.setText("Download")
        self._url_download_btn.setEnabled(True)
        self._url_input.setEnabled(True)
