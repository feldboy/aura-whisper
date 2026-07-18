from __future__ import annotations

import copy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from aura_whisper.config import Config
from aura_whisper.llm.ollama_client import OllamaClient, OllamaError
from aura_whisper.ui.hotkey_edit import HotkeyEdit
from aura_whisper.ui.ui_kit import card, page_header, scroll_page


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
        self._ollama_status = QLabel("", self)
        self._ollama_status.setProperty("hint", True)
        self._ollama_status.setWordWrap(True)

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

        # --- modes list (left column) ---
        self._list = QListWidget(self)
        self._list.setMinimumWidth(150)
        self._list.setMinimumHeight(220)
        self._list.currentRowChanged.connect(self._on_row_changed)

        add_btn = QPushButton("Add", self)
        add_btn.clicked.connect(self._add_mode)
        delete_btn = QPushButton("Delete", self)
        delete_btn.clicked.connect(self._delete_mode)
        active_btn = QPushButton("Set active", self)
        active_btn.clicked.connect(self._set_active)

        list_btns = QHBoxLayout()
        list_btns.setSpacing(6)
        list_btns.addWidget(add_btn)
        list_btns.addWidget(delete_btn)
        list_btns.addWidget(active_btn)

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(8)
        left.addWidget(self._list, 1)
        left.addLayout(list_btns)
        left_holder = QWidget(self)
        left_holder.setLayout(left)
        left_holder.setFixedWidth(180)

        # --- mode editor (right column) ---
        self._name = QLineEdit(self)
        self._name.editingFinished.connect(self._save_current)
        self._prompt = QTextEdit(self)
        self._prompt.setAcceptRichText(False)
        self._prompt.setPlaceholderText(
            "What should the AI do with your dictated text?"
        )
        self._prompt.setMinimumHeight(150)
        self._model = QComboBox(self)
        self._model.setEditable(True)
        self._model.setView(QListView(self._model))
        self._enabled = QCheckBox(
            "Enabled — show this mode in the menu and shortcuts", self
        )

        self._mode_hotkey = HotkeyEdit("", self)
        clear_hotkey = QPushButton("Clear", self)
        clear_hotkey.setFixedWidth(64)
        clear_hotkey.clicked.connect(self._clear_mode_hotkey)
        hotkey_row = QHBoxLayout()
        hotkey_row.setContentsMargins(0, 0, 0, 0)
        hotkey_row.addWidget(self._mode_hotkey, 1)
        hotkey_row.addWidget(clear_hotkey)
        hotkey_holder = QWidget(self)
        hotkey_holder.setLayout(hotkey_row)

        editor = QFormLayout()
        editor.setSpacing(10)
        editor.setLabelAlignment(Qt.AlignRight | Qt.AlignTop)
        editor.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        editor.addRow(QLabel("Name"), self._name)
        editor.addRow(QLabel("Prompt"), self._prompt)
        editor.addRow(QLabel("Model"), self._model)
        editor.addRow(QLabel("Shortcut"), hotkey_holder)
        editor.addRow(QLabel(""), self._enabled)
        editor_holder = QWidget(self)
        editor_holder.setLayout(editor)

        modes_body = QHBoxLayout()
        modes_body.setContentsMargins(0, 0, 0, 0)
        modes_body.setSpacing(16)
        modes_body.addWidget(left_holder)
        modes_body.addWidget(editor_holder, 1)
        modes_body_holder = QWidget(self)
        modes_body_holder.setLayout(modes_body)

        inner = QWidget(self)
        v = QVBoxLayout(inner)
        v.setContentsMargins(20, 18, 20, 20)
        v.setSpacing(16)
        v.addWidget(
            page_header(
                inner,
                "AI Modes",
                "Rewrite what you dictate with a local AI model. The mode marked "
                "✓ runs when you use the \"Dictate with AI\" shortcut.",
            )
        )
        v.addWidget(
            card(
                inner,
                "Connection",
                [conn_form, self._ollama_status],
                "AuraWhisper sends your dictation to a local Ollama server, then "
                "types back the AI's reply.",
            )
        )
        v.addWidget(
            card(
                inner,
                "Modes",
                [modes_body_holder],
                "Pick a mode on the left to edit its instructions, or add your own "
                "for emails, summaries, tone fixes — anything.",
            ),
            1,
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll_page(inner))

        self._set_model_choices([])
        self._default_model.setCurrentText(config.ollama_model)
        self._rebuild_list()
        self._refresh_ollama_models()

    # --- results consumed by the dialog on save ---

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
            self._ollama_status.setText(
                f"Connected — {len(self._ollama_models)} models available"
            )
        except OllamaError as e:
            self._ollama_models = []
            self._ollama_status.setText(str(e))
        self._set_model_choices(self._ollama_models)

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
                label = f"✓ {label}"
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
                label = f"✓ {label}"
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
