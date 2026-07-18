from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from aura_whisper.audio import cues
from aura_whisper.config import Config
from aura_whisper.models.manager import format_size, scan_models
from aura_whisper.ui.hotkey_edit import HotkeyEdit
from aura_whisper.ui.models_page import ModelsPage
from aura_whisper.ui.modes_page import AIModesPage
from aura_whisper.ui.ui_kit import (
    card as _card,
    checkbox_with_sub as _checkbox_with_sub,
    load_styles,
    page_header as _page_header,
    scroll_page as _scroll_page,
    subgroup as _subgroup,
)


LANGUAGES = [
    ("Auto — Hebrew & English mix (recommended)", "auto"),
    ("Hebrew only", "he"),
    ("English only", "en"),
    ("Spanish", "es"),
    ("French", "fr"),
    ("German", "de"),
    ("Italian", "it"),
    ("Portuguese", "pt"),
    ("Russian", "ru"),
    ("Mandarin", "zh"),
    ("Japanese", "ja"),
    ("Korean", "ko"),
    ("Arabic", "ar"),
    ("Hindi", "hi"),
]

DEVICES = ["auto", "cpu", "cuda"]
COMPUTE_TYPES = ["auto", "int8", "int8_float16", "float16", "float32"]

# (label, minutes) — 0 means never unload while the app is open.
IDLE_UNLOAD_OPTIONS = [
    ("Never (keep loaded)", 0),
    ("After 2 minutes idle", 2),
    ("After 5 minutes idle", 5),
    ("After 10 minutes idle", 10),
    ("After 30 minutes idle", 30),
]


class GeneralPage(QWidget):
    def __init__(self, config: Config, parent=None) -> None:
        super().__init__(parent)

        # --- Speech ---
        self.language = QComboBox(self)
        for label, code in LANGUAGES:
            self.language.addItem(label, code)
        idx = self.language.findData(config.language)
        self.language.setCurrentIndex(idx if idx >= 0 else 0)

        # Optional second model, used only when auto-detect hears English.
        self.english_model = QComboBox(self)
        self.english_model.addItem("Off — use the main model for English", "")
        try:
            for m in scan_models(
                [config.model_path] if config.model_path else None
            ):
                self.english_model.addItem(
                    f"{m.name}  ·  {format_size(m.size_bytes)}", m.path
                )
        except Exception:
            pass
        current_english = getattr(config, "english_model_path", "") or ""
        eng_idx = self.english_model.findData(current_english)
        if eng_idx < 0 and current_english:
            self.english_model.addItem(
                f"{Path(current_english).stem}  ·  current", current_english
            )
            eng_idx = self.english_model.count() - 1
        self.english_model.setCurrentIndex(eng_idx if eng_idx >= 0 else 0)

        # --- Hotkeys ---
        self.hotkey = HotkeyEdit(config.hotkey, self)
        self.ai_hotkey = HotkeyEdit(config.ai_hotkey, self)

        self.hold_to_talk = _checkbox_with_sub(
            self,
            "Hold-to-talk",
            "Hold the shortcut down while you speak, release to stop.",
            config.hold_to_talk,
        )

        # --- Behavior ---
        self.auto_paste = _checkbox_with_sub(
            self,
            "Type the result where my cursor is",
            "Drops the finished text straight into the app you were using.",
            config.auto_paste,
        )
        self.keep_mic_warm = _checkbox_with_sub(
            self,
            "Instant start",
            "Keeps the mic open all the time so recording begins with no delay "
            "(the orange indicator stays on).",
            config.keep_mic_warm,
        )
        self.pause_media = _checkbox_with_sub(
            self,
            "Pause music while I dictate",
            "Automatically resumes playback when you're done.",
            config.pause_media_while_recording,
        )
        self.cue_sounds = _checkbox_with_sub(
            self,
            "Play a sound when recording starts and stops",
            "A soft cue so you always know when the mic is live.",
            getattr(config, "cue_sounds", True),
        )

        # Pick which cue sound to play, with an instant preview.
        self.cue_sound = QComboBox(self)
        for key, label in cues.CUE_SOUND_OPTIONS:
            self.cue_sound.addItem(label, key)
        cue_idx = self.cue_sound.findData(getattr(config, "cue_sound", "harp"))
        self.cue_sound.setCurrentIndex(cue_idx if cue_idx >= 0 else 0)
        # Connect only after the initial selection so the dialog opens silently.
        self.cue_sound.currentIndexChanged.connect(
            lambda: cues.preview(self.cue_sound.currentData(), "start")
        )
        cue_preview = QPushButton("▶", self)
        cue_preview.setFixedWidth(40)
        cue_preview.setToolTip("Preview this sound")
        cue_preview.setFocusPolicy(Qt.NoFocus)
        cue_preview.clicked.connect(
            lambda: cues.preview(self.cue_sound.currentData(), "start")
        )
        cue_row = QHBoxLayout()
        cue_row.setContentsMargins(24, 0, 0, 0)
        cue_row.setSpacing(8)
        cue_lbl = QLabel("Sound")
        cue_lbl.setProperty("toggleHint", True)
        cue_row.addWidget(cue_lbl)
        cue_row.addWidget(self.cue_sound, 1)
        cue_row.addWidget(cue_preview)
        self._cue_sound_row = QWidget(self)
        self._cue_sound_row.setLayout(cue_row)
        self.vad = _checkbox_with_sub(
            self,
            "Skip silent parts automatically",
            "Trims long pauses for faster, cleaner transcripts.",
            config.vad_filter,
        )

        body = QWidget(self)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(16)

        layout.addWidget(
            _page_header(
                body,
                "General",
                "Everyday settings for how AuraWhisper listens and behaves.",
            )
        )

        speech_form = QFormLayout()
        speech_form.setSpacing(10)
        speech_form.addRow(QLabel("Language"), self.language)
        speech_form.addRow(QLabel("English model"), self.english_model)

        layout.addWidget(
            _card(
                body,
                "Speech & Language",
                [speech_form],
                "Auto figures out which language you spoke each time — speak "
                "Hebrew in one message and English in the next. If you pick an "
                "English model, English speech is re-transcribed with it while "
                "Hebrew keeps using the main model.",
            )
        )

        shortcuts_form = QFormLayout()
        shortcuts_form.setSpacing(10)
        shortcuts_form.addRow(QLabel("Dictate"), self.hotkey)
        shortcuts_form.addRow(QLabel("Dictate with AI"), self.ai_hotkey)
        layout.addWidget(
            _card(
                body,
                "Shortcuts",
                [shortcuts_form, _subgroup(body, "", [self.hold_to_talk])],
                "Press once to start, press again to stop. \"Dictate with AI\" "
                "also rewrites what you said using the active AI mode.",
            )
        )

        layout.addWidget(
            _card(
                body,
                "Behavior",
                [
                    _subgroup(
                        body,
                        "While recording",
                        [self.keep_mic_warm, self.pause_media, self.cue_sounds,
                         self._cue_sound_row],
                    ),
                    _subgroup(body, "Transcription", [self.vad]),
                    _subgroup(body, "Output", [self.auto_paste]),
                ],
            )
        )

        layout.addStretch(1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(_scroll_page(body))


class AdvancedPage(QWidget):
    """Power-user options split out of General so they don't clutter it."""

    def __init__(self, config: Config, parent=None) -> None:
        super().__init__(parent)

        self.device = QComboBox(self)
        self.device.addItems(DEVICES)
        self.device.setCurrentText(config.device if config.device in DEVICES else "auto")

        self.compute = QComboBox(self)
        self.compute.addItems(COMPUTE_TYPES)
        self.compute.setCurrentText(
            config.compute_type if config.compute_type in COMPUTE_TYPES else "auto"
        )

        self.idle_unload = QComboBox(self)
        for label, minutes in IDLE_UNLOAD_OPTIONS:
            self.idle_unload.addItem(label, minutes)
        idle_idx = self.idle_unload.findData(config.idle_unload_minutes)
        self.idle_unload.setCurrentIndex(idle_idx if idle_idx >= 0 else 2)

        body = QWidget(self)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(16)

        layout.addWidget(
            _page_header(
                body,
                "Advanced",
                "Fine-tune performance and memory. The defaults work well for "
                "most Macs — only change these if you know you need to.",
            )
        )

        perf = QFormLayout()
        perf.setSpacing(10)
        perf.addRow(QLabel("Device"), self.device)
        perf.addRow(QLabel("Compute type"), self.compute)
        layout.addWidget(
            _card(
                body,
                "Performance",
                [perf],
                "\"Auto\" picks the fastest safe option for your hardware.",
            )
        )

        mem = QFormLayout()
        mem.setSpacing(10)
        mem.addRow(QLabel("Free memory when idle"), self.idle_unload)
        layout.addWidget(
            _card(
                body,
                "Memory",
                [mem],
                "Unloads the speech model after a while unused to free up RAM. "
                "The next dictation reloads it automatically.",
            )
        )

        layout.addStretch(1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(_scroll_page(body))


class SettingsDialog(QDialog):
    # (emoji, title, subtitle) for each sidebar entry, in order.
    _NAV = [
        ("🎙", "General", "Language, shortcuts & behavior"),
        ("✨", "AI Modes", "Rewrite what you dictate"),
        ("📦", "Models", "Speech-to-text engines"),
        ("⚙", "Advanced", "Performance & memory"),
    ]

    def __init__(self, config: Config, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("AuraWhisper — Settings")
        # The UI is authored left-to-right; pin the direction so a Hebrew/RTL
        # system locale can't mirror the layout and clip content off-screen.
        self.setLayoutDirection(Qt.LeftToRight)
        self._config = config
        self.result_config = replace(config)

        self.setStyleSheet(load_styles())

        self._general_page = GeneralPage(config, self)
        self._modes_page = AIModesPage(config, self)
        self._models_page = ModelsPage(config.model_path, self)
        self._advanced_page = AdvancedPage(config, self)

        pages = [
            self._general_page,
            self._modes_page,
            self._models_page,
            self._advanced_page,
        ]

        # --- left sidebar navigation ---
        self._nav = QListWidget(self)
        self._nav.setObjectName("settingsNav")
        self._nav.setFixedWidth(214)
        self._nav.setIconSize(QSize(0, 0))
        self._nav.setUniformItemSizes(True)
        for emoji, title, subtitle in self._NAV:
            item = QListWidgetItem(f"{emoji}   {title}", self._nav)
            item.setToolTip(subtitle)
            item.setSizeHint(QSize(0, 46))

        self._stack = QStackedWidget(self)
        for page in pages:
            self._stack.addWidget(page)

        self._nav.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._nav.setCurrentRow(0)

        content = QHBoxLayout()
        content.setSpacing(14)
        content.addWidget(self._nav)
        content.addWidget(self._stack, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel, parent=self
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addLayout(content, 1)
        layout.addWidget(buttons)

        self._fit_to_screen()

    def _fit_to_screen(self) -> None:
        """Size the window to comfortably fit the current screen, positioned
        slightly above center for better ergonomics."""
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(900, 680)
            return
        avail = screen.availableGeometry()
        width = min(920, avail.width() - 60)
        height = min(700, avail.height() - 60)
        self.setMinimumSize(min(760, width), min(560, height))
        self.resize(width, height)
        # Position at 38% from top (slightly above center) for comfort
        self.move(
            avail.x() + (avail.width() - width) // 2,
            avail.y() + int((avail.height() - height) * 0.38),
        )

    def _accept(self) -> None:
        g = self._general_page
        a = self._advanced_page
        modes, active_mode, ollama_url, ollama_model = self._modes_page.result()
        self.result_config = replace(
            self._config,
            model_path=self._models_page.current_model_path.strip(),
            english_model_path=g.english_model.currentData() or "",
            language=g.language.currentData() or "auto",
            hotkey=g.hotkey.combo() or "<cmd>+<shift>+<space>",
            ai_hotkey=g.ai_hotkey.combo() or "<cmd>+<shift>+<alt>+<space>",
            device=a.device.currentText(),
            compute_type=a.compute.currentText(),
            auto_paste=g.auto_paste.isChecked(),
            vad_filter=g.vad.isChecked(),
            hold_to_talk=g.hold_to_talk.isChecked(),
            keep_mic_warm=g.keep_mic_warm.isChecked(),
            pause_media_while_recording=g.pause_media.isChecked(),
            idle_unload_minutes=a.idle_unload.currentData(),
            cue_sounds=g.cue_sounds.isChecked(),
            cue_sound=g.cue_sound.currentData() or "harp",
            modes=modes,
            active_mode=active_mode,
            ollama_url=ollama_url,
            ollama_model=ollama_model,
        )
        self.accept()
