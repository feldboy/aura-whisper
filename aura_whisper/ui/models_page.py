from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from aura_whisper.models.manager import (
    CURATED_MODELS,
    CuratedModel,
    ModelDownloader,
    format_size,
    scan_models,
)
from aura_whisper.ui.smooth_scroll import enable_smooth_scroll


class ModelsPage(QWidget):
    """Settings tab: installed whisper models + curated downloads."""

    model_selected = Signal(str)  # absolute path

    def __init__(self, current_model_path: str, parent=None) -> None:
        super().__init__(parent)
        self._current_path = current_model_path
        self._downloaders: dict[str, ModelDownloader] = {}
        # Keep finished/failed downloaders alive until their thread is torn
        # down, so PySide never GCs a still-running worker.
        self._retired: list[ModelDownloader] = []

        installed_label = QLabel("Active model", self)
        installed_label.setProperty("sectionTitle", True)

        self._installed_combo = QComboBox(self)
        self._installed_combo.setMinimumHeight(30)
        self._installed_combo.currentIndexChanged.connect(
            self._on_installed_changed
        )

        add_btn = QPushButton("Add model file…", self)
        add_btn.clicked.connect(self._add_file)

        curated_label = QLabel("Download models", self)
        curated_label.setProperty("sectionTitle", True)

        self._curated_box = QVBoxLayout()
        self._curated_box.setSpacing(6)

        path_label = QLabel("Model path (advanced)", self)
        self._path_edit = QLineEdit(current_model_path, self)
        self._path_edit.setPlaceholderText("Path to a ggml-*.bin file or folder")
        self._path_edit.editingFinished.connect(
            lambda: self._select(self._path_edit.text().strip(), refresh=False)
        )

        content = QWidget(self)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        layout.addWidget(installed_label)
        layout.addWidget(self._installed_combo)
        layout.addWidget(add_btn, 0, Qt.AlignLeft)
        layout.addSpacing(6)
        layout.addWidget(curated_label)
        layout.addLayout(self._curated_box)
        layout.addSpacing(6)
        layout.addWidget(path_label)
        layout.addWidget(self._path_edit)
        layout.addStretch(1)

        scroll = QScrollArea(self)
        scroll.setWidget(content)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        enable_smooth_scroll(scroll)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        self._build_curated_rows()
        self.refresh()

    @property
    def current_model_path(self) -> str:
        return self._current_path

    def refresh(self) -> None:
        models = scan_models(
            [self._current_path] if self._current_path else None
        )
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
            self._select(path)

    # --- curated downloads ---

    def _build_curated_rows(self) -> None:
        self._curated_rows: dict[str, dict] = {}
        for cm in CURATED_MODELS:
            row = QWidget(self)
            name = QLabel(f"{cm.name}  ·  {cm.size_hint}", row)
            name.setToolTip(cm.description)
            desc = QLabel(cm.description, row)
            desc.setProperty("hint", True)
            desc.setWordWrap(True)
            progress = QProgressBar(row)
            progress.setVisible(False)
            progress.setFixedHeight(14)
            btn = QPushButton("Download", row)
            btn.clicked.connect(lambda _=False, c=cm: self._start_download(c))

            text_col = QVBoxLayout()
            text_col.setContentsMargins(0, 0, 0, 0)
            text_col.setSpacing(1)
            text_col.addWidget(name)
            text_col.addWidget(desc)
            text_col.addWidget(progress)

            h = QHBoxLayout(row)
            h.setContentsMargins(0, 2, 0, 2)
            h.addLayout(text_col, 1)
            h.addWidget(btn, 0, Qt.AlignTop)

            self._curated_box.addWidget(row)
            self._curated_rows[cm.filename] = {
                "button": btn, "progress": progress, "model": cm,
            }

    def _installed_filenames(self) -> set[str]:
        return {Path(m.path).name for m in scan_models()}

    def _update_curated_states(self) -> None:
        installed = self._installed_filenames()
        for filename, widgets in self._curated_rows.items():
            if filename in self._downloaders:
                continue
            if filename in installed:
                widgets["button"].setText("Installed")
                widgets["button"].setEnabled(False)
            else:
                widgets["button"].setText("Download")
                widgets["button"].setEnabled(True)

    def _start_download(self, cm: CuratedModel) -> None:
        widgets = self._curated_rows[cm.filename]
        widgets["button"].setText("Downloading…")
        widgets["button"].setEnabled(False)
        widgets["progress"].setVisible(True)
        widgets["progress"].setRange(0, 0)

        dl = ModelDownloader(cm)
        self._downloaders[cm.filename] = dl
        # Connect to bound methods (not lambdas). A lambda has no receiver
        # QObject, so Qt falls back to a *direct* connection and the slot would
        # run on the download thread — touching Qt widgets off the main thread
        # crashes the app. Bound methods of this QWidget resolve to a queued
        # (main-thread) connection instead.
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
