from __future__ import annotations

import copy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from aura_whisper.config import Config
from aura_whisper.llm.ollama_client import OllamaClient, OllamaError, OllamaPuller
from aura_whisper.ui.hotkey_edit import HotkeyEdit
from aura_whisper.ui.ui_kit import (
    ToggleSwitch,
    page_header,
    panel_section,
    pill,
    scroll_page,
)


USE_DEFAULT = "(use default model)"


class AIModesPage(QWidget):
    """Settings tab: edit AI rewrite modes and the Ollama connection."""

    def __init__(self, config: Config, parent=None) -> None:
        super().__init__(parent)
        self.setLayoutDirection(Qt.LeftToRight)
        self.modes: list[dict] = copy.deepcopy(config.modes)
        self.active_mode: str = config.active_mode
        self._current_index: int = -1
        self._ollama_models: list[str] = []

        # --- Ollama connection ---
        self._ollama_url = QLineEdit(config.ollama_url, self)
        self._ollama_url.setCursorPosition(0)
        self._default_model = QComboBox(self)
        self._default_model.setView(QListView(self._default_model))
        if config.ollama_model:
            self._default_model.addItem(config.ollama_model)
        refresh_btn = QPushButton("Refresh", self)
        refresh_btn.clicked.connect(self._refresh_ollama_models)
        self._ollama_status = pill("Not connected", "neutral", self)
        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.addWidget(self._ollama_status)
        status_row.addStretch(1)
        self._status_row = status_row

        url_row = QHBoxLayout()
        url_row.setContentsMargins(0, 0, 0, 0)
        url_row.setSpacing(8)
        url_row.addWidget(self._ollama_url, 1)
        url_row.addWidget(refresh_btn)
        url_holder = QWidget(self)
        url_holder.setLayout(url_row)

        conn_form = QFormLayout()
        conn_form.setSpacing(10)
        conn_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        conn_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        conn_form.addRow(QLabel("Ollama URL"), url_holder)
        conn_form.addRow(QLabel("Default model"), self._default_model)

        # --- pull a new Ollama model by name ---
        self._pull_input = QLineEdit(self)
        self._pull_input.setPlaceholderText(
            "Model to pull, e.g. llama3.1:8b, qwen2.5:7b"
        )
        self._pull_btn = QPushButton("Pull", self)
        self._pull_btn.clicked.connect(self._start_pull)
        self._pull_puller: OllamaPuller | None = None
        self._pull_retired: list[OllamaPuller] = []
        pull_row = QHBoxLayout()
        pull_row.setContentsMargins(0, 0, 0, 0)
        pull_row.setSpacing(8)
        pull_row.addWidget(self._pull_input, 1)
        pull_row.addWidget(self._pull_btn)
        self._pull_progress = QProgressBar(self)
        self._pull_progress.setVisible(False)
        self._pull_progress.setFixedHeight(6)
        self._pull_progress.setTextVisible(False)
        conn_form.addRow(QLabel("Pull a model"), pull_row)

        # --- mode picker: a compact, full-width list with a small toolbar ---
        self._list = QListWidget(self)
        self._list.setObjectName("modePicker")
        self._list.setMinimumHeight(122)
        self._list.setMaximumHeight(150)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list.currentRowChanged.connect(self._on_row_changed)

        add_btn = QPushButton("＋  New mode", self)
        add_btn.setObjectName("addModeBtn")
        add_btn.clicked.connect(self._add_mode)
        delete_btn = QPushButton("Delete", self)
        delete_btn.clicked.connect(self._delete_mode)
        active_btn = QPushButton("★  Set as active", self)
        active_btn.clicked.connect(self._set_active)

        picker_toolbar = QHBoxLayout()
        picker_toolbar.setContentsMargins(0, 0, 0, 0)
        picker_toolbar.setSpacing(8)
        picker_toolbar.addWidget(add_btn)
        picker_toolbar.addWidget(delete_btn)
        picker_toolbar.addStretch(1)
        picker_toolbar.addWidget(active_btn)

        picker_col = QVBoxLayout()
        picker_col.setContentsMargins(0, 0, 0, 0)
        picker_col.setSpacing(10)
        picker_col.addWidget(self._list)
        picker_col.addLayout(picker_toolbar)
        picker_holder = QWidget(self)
        picker_holder.setLayout(picker_col)

        # --- mode editor: a full-width form beneath the picker ---
        self._name = QLineEdit(self)
        self._name.setPlaceholderText("e.g. Email, Summary, Formal tone…")
        self._name.editingFinished.connect(self._save_current)
        self._prompt = QTextEdit(self)
        self._prompt.setAcceptRichText(False)
        self._prompt.setPlaceholderText(
            "What should the AI do with your dictated text? "
            "e.g. “Turn this into a concise, friendly email.”"
        )
        self._prompt.setMinimumHeight(128)
        self._model = QComboBox(self)
        self._model.setEditable(True)
        self._model.setView(QListView(self._model))
        self._enabled = ToggleSwitch(True, self)

        self._mode_hotkey = HotkeyEdit("", self)
        clear_hotkey = QPushButton("Clear", self)
        clear_hotkey.setFixedWidth(72)
        clear_hotkey.clicked.connect(self._clear_mode_hotkey)
        hotkey_row = QHBoxLayout()
        hotkey_row.setContentsMargins(0, 0, 0, 0)
        hotkey_row.setSpacing(8)
        hotkey_row.addWidget(self._mode_hotkey, 1)
        hotkey_row.addWidget(clear_hotkey)
        hotkey_holder = QWidget(self)
        hotkey_holder.setLayout(hotkey_row)

        editor = QFormLayout()
        editor.setSpacing(12)
        editor.setContentsMargins(0, 0, 0, 0)
        editor.setLabelAlignment(Qt.AlignLeft | Qt.AlignTop)
        editor.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        editor.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        editor.addRow(self._form_label("Name"), self._name)
        editor.addRow(self._form_label("Prompt"), self._prompt)
        editor.addRow(self._form_label("Model"), self._model)
        editor.addRow(self._form_label("Shortcut"), hotkey_holder)

        enabled_row = QWidget(self)
        enabled_layout = QHBoxLayout(enabled_row)
        enabled_layout.setContentsMargins(0, 0, 0, 0)
        enabled_label = QLabel(
            "Show this mode in the menu and shortcuts", enabled_row
        )
        enabled_label.setProperty("rowTitle", True)
        enabled_layout.addWidget(enabled_label)
        enabled_layout.addStretch(1)
        enabled_layout.addWidget(self._enabled)
        editor.addRow(enabled_row)
        editor_holder = QWidget(self)
        editor_holder.setLayout(editor)

        # Thin divider between the picker and the editor inside the card.
        divider = QFrame(self)
        divider.setObjectName("cardDivider")
        divider.setFrameShape(QFrame.NoFrame)
        divider.setFixedHeight(1)

        inner = QWidget(self)
        v = QVBoxLayout(inner)
        v.setContentsMargins(28, 24, 28, 28)
        v.setSpacing(22)
        v.addWidget(
            page_header(
                inner,
                "AI Modes",
                "Rewrite what you dictate with a local AI model. The mode marked "
                "★ runs when you use the \"Dictate with AI\" shortcut.",
                icon="sparkles",
            )
        )
        v.addWidget(
            panel_section(
                inner,
                "Ollama connection",
                [conn_form, self._pull_progress, self._status_row],
                "AuraWhisper sends your dictation to a local Ollama server, then "
                "types back the AI's reply. Pulling a model downloads it into "
                "Ollama, same as running `ollama pull` in a terminal.",
            )
        )
        v.addWidget(
            panel_section(
                inner,
                "Your modes",
                [picker_holder, divider, editor_holder],
            )
        )
        v.addStretch(1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll_page(inner))

        self._set_model_choices([])
        self._default_model.setCurrentText(config.ollama_model)
        self._rebuild_list()
        self._refresh_ollama_models()

    # --- results consumed by the dialog on save ---

    @staticmethod
    def _form_label(text: str) -> QLabel:
        """A right-column form label styled as a small, muted caption."""
        label = QLabel(text)
        label.setProperty("fieldLabel", True)
        label.setMinimumWidth(72)
        return label

    def result(self) -> tuple[list[dict], str, str, str]:
        self._save_current()
        return (
            self.modes,
            self.active_mode,
            self._ollama_url.text().strip() or "http://localhost:11434",
            self._default_model.currentText().strip(),
        )

    # --- Ollama ---

    def _refresh_ollama_models(self) -> None:
        url = self._ollama_url.text().strip() or "http://localhost:11434"
        try:
            self._ollama_models = OllamaClient(url).list_models()
            self._set_status(
                f"Connected — {len(self._ollama_models)} models available",
                "success",
            )
        except OllamaError as e:
            self._ollama_models = []
            self._set_status(str(e), "neutral")
        self._set_model_choices(self._ollama_models)

    def _start_pull(self) -> None:
        name = self._pull_input.text().strip()
        if not name or self._pull_puller is not None:
            return
        url = self._ollama_url.text().strip() or "http://localhost:11434"
        self._pull_btn.setText("Pulling…")
        self._pull_btn.setEnabled(False)
        self._pull_input.setEnabled(False)
        self._pull_progress.setVisible(True)
        self._pull_progress.setRange(0, 0)

        puller = OllamaPuller(url, name)
        self._pull_puller = puller
        # Connect to bound methods (not lambdas) so Qt queues the slot onto
        # the main thread instead of running it on the pull thread, where
        # touching widgets would crash the app.
        puller.progress.connect(self._on_pull_progress)
        puller.status.connect(self._on_pull_status)
        puller.finished.connect(self._on_pull_finished)
        puller.error.connect(self._on_pull_error)
        puller.start()

    def _on_pull_progress(self, done: int, total: int) -> None:
        if total > 0:
            self._pull_progress.setRange(0, 100)
            self._pull_progress.setValue(int(done * 100 / total))

    def _on_pull_status(self, status: str) -> None:
        self._set_status(status, "neutral")

    def _retire_pull(self) -> None:
        if self._pull_puller is not None:
            self._pull_retired.append(self._pull_puller)
        self._pull_puller = None
        self._pull_progress.setVisible(False)
        self._pull_btn.setText("Pull")
        self._pull_btn.setEnabled(True)
        self._pull_input.setEnabled(True)

    def _on_pull_finished(self, name: str) -> None:
        self._retire_pull()
        self._pull_input.clear()
        self._refresh_ollama_models()
        if self._default_model.findText(name) < 0:
            self._default_model.addItem(name)
        self._default_model.setCurrentText(name)

    def _on_pull_error(self, message: str) -> None:
        self._retire_pull()
        self._pull_btn.setToolTip(message)
        self._set_status(message, "neutral")

    def _set_status(self, text: str, tone: str) -> None:
        self._ollama_status.setText(text)
        self._ollama_status.setProperty("tone", tone)
        style = self._ollama_status.style()
        style.unpolish(self._ollama_status)
        style.polish(self._ollama_status)

    def _set_model_choices(self, names: list[str]) -> None:
        default_current = self._default_model.currentText()
        mode_current = self._model.currentText()

        self._default_model.clear()
        self._default_model.addItems(names)
        # Keep the configured model selectable even if the server didn't list
        # it (Ollama offline, or the model hasn't been pulled yet).
        if default_current and self._default_model.findText(default_current) < 0:
            self._default_model.insertItem(0, default_current)
        if default_current:
            self._default_model.setCurrentText(default_current)

        self._model.clear()
        self._model.addItem(USE_DEFAULT)
        self._model.addItems(names)
        if mode_current and self._model.findText(mode_current) < 0:
            self._model.addItem(mode_current)
        self._model.setCurrentText(mode_current or USE_DEFAULT)

    # --- modes list handling ---

    def _rebuild_list(self, select: int = 0) -> None:
        self._current_index = -1
        self._list.blockSignals(True)
        self._list.clear()
        for mode in self.modes:
            label = mode.get("name", "?")
            if label == self.active_mode:
                label = f"★  {label}"
            item = QListWidgetItem(label)
            if not mode.get("enabled", True):
                item.setForeground(Qt.gray)
            self._list.addItem(item)
        self._list.blockSignals(False)
        if self.modes:
            select = max(0, min(select, len(self.modes) - 1))
            self._list.setCurrentRow(select)

    def _on_row_changed(self, row: int) -> None:
        self._save_current()
        self._current_index = row
        if row < 0 or row >= len(self.modes):
            return
        mode = self.modes[row]
        self._name.setText(mode.get("name", ""))
        self._prompt.setPlainText(mode.get("prompt", ""))
        self._model.setCurrentText(mode.get("ollama_model") or USE_DEFAULT)
        self._mode_hotkey.set_combo(mode.get("hotkey", ""))
        self._enabled.setChecked(bool(mode.get("enabled", True)))

    def _save_current(self) -> None:
        i = self._current_index
        if i < 0 or i >= len(self.modes):
            return
        mode = self.modes[i]
        old_name = mode.get("name", "")
        new_name = self._name.text().strip() or old_name
        model = self._model.currentText().strip()
        mode.update(
            name=new_name,
            prompt=self._prompt.toPlainText().strip(),
            ollama_model="" if model == USE_DEFAULT else model,
            enabled=self._enabled.isChecked(),
            hotkey=self._mode_hotkey_value(),
        )
        if old_name == self.active_mode:
            self.active_mode = new_name
        item = self._list.item(i)
        if item is not None:
            label = new_name
            if new_name == self.active_mode:
                label = f"★  {label}"
            item.setText(label)

    def _mode_hotkey_value(self) -> str:
        """Only treat a combo with at least one modifier as a real shortcut."""
        combo = self._mode_hotkey.combo()
        mods = ("<cmd>", "<shift>", "<alt>", "<ctrl>")
        return combo if any(m in combo for m in mods) else ""

    def _clear_mode_hotkey(self) -> None:
        self._mode_hotkey.set_combo("")

    def _add_mode(self) -> None:
        self._save_current()
        base = "New mode"
        names = {m.get("name") for m in self.modes}
        name = base
        n = 2
        while name in names:
            name = f"{base} {n}"
            n += 1
        self.modes.append(
            {"name": name, "prompt": "", "ollama_model": "", "enabled": True}
        )
        self._rebuild_list(select=len(self.modes) - 1)

    def _delete_mode(self) -> None:
        row = self._list.currentRow()
        if row < 0 or row >= len(self.modes):
            return
        removed = self.modes.pop(row)
        self._current_index = -1
        if removed.get("name") == self.active_mode and self.modes:
            self.active_mode = self.modes[0].get("name", "")
        self._rebuild_list(select=row)

    def _set_active(self) -> None:
        row = self._list.currentRow()
        if row < 0 or row >= len(self.modes):
            return
        self._save_current()
        self.active_mode = self.modes[row].get("name", "")
        self._rebuild_list(select=row)
