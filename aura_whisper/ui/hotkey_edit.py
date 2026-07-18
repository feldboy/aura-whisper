from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QPushButton, QWidget

# (label, token) pairs. Order here is the canonical output order.
_MODIFIERS: list[tuple[str, str]] = [
    ("⌘", "<cmd>"),
    ("⇧", "<shift>"),
    ("⌥", "<alt>"),
    ("⌃", "<ctrl>"),
]

# Friendly label -> combo token. Tokens match aura_whisper.hotkey parsing.
_KEYS: list[tuple[str, str]] = (
    [("Space", "<space>"), ("Return", "<return>"), ("Tab", "<tab>"),
     ("Escape", "<escape>"), ("Delete", "<delete>")]
    + [(c.upper(), c) for c in "abcdefghijklmnopqrstuvwxyz"]
    + [(str(d), f"<{d}>") for d in range(10)]
    + [(f"F{n}", f"<f{n}>") for n in range(1, 13)]
)

_MOD_TOKENS = {t for _, t in _MODIFIERS}
# Accept a few aliases when parsing existing config strings.
_MOD_ALIASES = {
    "<command>": "<cmd>",
    "<option>": "<alt>",
    "<opt>": "<alt>",
    "<control>": "<ctrl>",
}

# Named Qt keys -> combo token (letters/digits/F-keys handled programmatically).
_NAMED_KEYS: dict[int, str] = {
    Qt.Key_Space: "<space>",
    Qt.Key_Return: "<return>",
    Qt.Key_Enter: "<return>",
    Qt.Key_Tab: "<tab>",
    Qt.Key_Delete: "<delete>",
    Qt.Key_Backspace: "<delete>",
}


def _qt_key_to_token(key: int) -> str | None:
    if Qt.Key_A <= key <= Qt.Key_Z:
        return chr(key).lower()
    if Qt.Key_0 <= key <= Qt.Key_9:
        return f"<{key - Qt.Key_0}>"
    if Qt.Key_F1 <= key <= Qt.Key_F12:
        return f"<f{key - Qt.Key_F1 + 1}>"
    return _NAMED_KEYS.get(key)


class HotkeyEdit(QWidget):
    """Pick a global shortcut from modifier toggles + a key dropdown.

    Also supports "Record": click it and press the desired combo to capture it.
    Reads/writes the app's combo format, e.g. ``<cmd>+<shift>+<1>``.
    """

    def __init__(self, combo: str = "", parent=None) -> None:
        super().__init__(parent)
        self._mod_buttons: dict[str, QPushButton] = {}
        self._recording = False

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        for label, token in _MODIFIERS:
            btn = QPushButton(label, self)
            btn.setCheckable(True)
            btn.setProperty("modKey", True)
            btn.setFixedWidth(38)
            self._mod_buttons[token] = btn
            row.addWidget(btn)

        self._key = QComboBox(self)
        for label, token in _KEYS:
            self._key.addItem(label, token)
        row.addWidget(self._key, 1)

        self._record_btn = QPushButton("Record", self)
        self._record_btn.setCheckable(True)
        self._record_btn.setFixedWidth(84)
        self._record_btn.clicked.connect(self._toggle_record)
        row.addWidget(self._record_btn)

        self.set_combo(combo)

    # --- record capture ---

    def _toggle_record(self) -> None:
        if self._recording:
            self._stop_record()
        else:
            self._start_record()

    def _start_record(self) -> None:
        self._recording = True
        self._record_btn.setChecked(True)
        self._record_btn.setText("Press keys…")
        self.setFocus(Qt.OtherFocusReason)
        self.grabKeyboard()

    def _stop_record(self) -> None:
        self._recording = False
        self._record_btn.setChecked(False)
        self._record_btn.setText("Record")
        self.releaseKeyboard()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if not self._recording:
            super().keyPressEvent(event)
            return
        key = event.key()
        if key == Qt.Key_Escape:
            self._stop_record()
            return
        if key in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta):
            return  # wait for the real (non-modifier) key
        token = _qt_key_to_token(key)
        if token is None:
            return
        # macOS Qt maps ControlModifier->⌘ and MetaModifier->⌃ by default.
        mods = event.modifiers()
        self._mod_buttons["<cmd>"].setChecked(bool(mods & Qt.ControlModifier))
        self._mod_buttons["<shift>"].setChecked(bool(mods & Qt.ShiftModifier))
        self._mod_buttons["<alt>"].setChecked(bool(mods & Qt.AltModifier))
        self._mod_buttons["<ctrl>"].setChecked(bool(mods & Qt.MetaModifier))
        idx = self._key.findData(token)
        if idx >= 0:
            self._key.setCurrentIndex(idx)
        self._stop_record()

    # --- value ---

    def set_combo(self, combo: str) -> None:
        tokens = [t.strip().lower() for t in combo.split("+") if t.strip()]
        for token, btn in self._mod_buttons.items():
            btn.setChecked(False)
        key_token: str | None = None
        for raw in tokens:
            tok = _MOD_ALIASES.get(raw, raw)
            if tok in self._mod_buttons:
                self._mod_buttons[tok].setChecked(True)
            elif tok in _MOD_TOKENS:
                self._mod_buttons[tok].setChecked(True)
            else:
                key_token = raw
        if key_token is not None:
            idx = self._key.findData(key_token)
            if idx < 0 and key_token.startswith("<") and key_token.endswith(">"):
                idx = self._key.findData(key_token[1:-1])
            if idx < 0:
                idx = self._key.findData(f"<{key_token}>")
            if idx >= 0:
                self._key.setCurrentIndex(idx)

    def combo(self) -> str:
        parts = [t for _, t in _MODIFIERS if self._mod_buttons[t].isChecked()]
        parts.append(self._key.currentData())
        return "+".join(parts)
