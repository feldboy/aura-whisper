from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPalette
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
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
    ToggleSwitch,
    load_styles,
    page_header as _page_header,
    scroll_page as _scroll_page,
    section as _section,
    setting_row as _setting_row,
    icon_tile,
    tile_pixmap,
)
from aura_whisper.vibrancy import style_native_window


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
        self.language.setMinimumWidth(300)

        # Optional second model, used only when auto-detect hears English.
        self.english_model = QComboBox(self)
        self.english_model.addItem("Off — use the main model for English", "")
        try:
            extra = list(config.custom_model_paths)
            if config.model_path:
                extra.append(config.model_path)
            for m in scan_models(extra):
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
        self.english_model.setMinimumWidth(300)

        # --- Hotkeys ---
        self.hotkey = HotkeyEdit(config.hotkey, self)
        self.ai_hotkey = HotkeyEdit(config.ai_hotkey, self)
        self.rewrite_selection_hotkey = HotkeyEdit(
            config.rewrite_selection_hotkey, self
        )
        self.hold_to_talk = ToggleSwitch(config.hold_to_talk, self)

        # --- Behavior ---
        self.auto_paste = ToggleSwitch(config.auto_paste, self)
        self.keep_mic_warm = ToggleSwitch(config.keep_mic_warm, self)
        self.pause_media = ToggleSwitch(
            config.pause_media_while_recording, self
        )
        self.cue_sounds = ToggleSwitch(getattr(config, "cue_sounds", True), self)
        self.vad = ToggleSwitch(config.vad_filter, self)

        # Pick which cue sound to play, with an instant preview.
        self.cue_sound = QComboBox(self)
        for key, label in cues.CUE_SOUND_OPTIONS:
            self.cue_sound.addItem(label, key)
        cue_idx = self.cue_sound.findData(getattr(config, "cue_sound", "harp"))
        self.cue_sound.setCurrentIndex(cue_idx if cue_idx >= 0 else 0)
        self.cue_sound.setMinimumWidth(150)
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
        cue_control = QWidget(self)
        cue_ctl_row = QHBoxLayout(cue_control)
        cue_ctl_row.setContentsMargins(0, 0, 0, 0)
        cue_ctl_row.setSpacing(8)
        cue_ctl_row.addWidget(self.cue_sound)
        cue_ctl_row.addWidget(cue_preview)

        # --- assemble ---
        body = QWidget(self)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(28, 24, 28, 28)
        layout.setSpacing(22)

        layout.addWidget(
            _page_header(
                body,
                "General",
                "Configure dictation and app behavior.",
                icon="settings",
            )
        )

        layout.addWidget(
            _section(
                body,
                "Speech & Language",
                [
                    _setting_row(
                        body,
                        "Primary Language",
                        "Used to identify your speech automatically.",
                        self.language,
                    ),
                    _setting_row(
                        body,
                        "English model",
                        "Re-transcribe English speech with a dedicated model.",
                        self.english_model,
                    ),
                ],
            )
        )

        layout.addWidget(
            _section(
                body,
                "Shortcuts",
                [
                    _setting_row(
                        body,
                        "Dictate",
                        "Press once to start, again to stop.",
                        self.hotkey,
                    ),
                    _setting_row(
                        body,
                        "Dictate with AI",
                        "Rewrites your speech using the active AI mode.",
                        self.ai_hotkey,
                    ),
                    _setting_row(
                        body,
                        "Rewrite selection",
                        "Select text in any app, press to rewrite it with the active AI mode.",
                        self.rewrite_selection_hotkey,
                    ),
                    _setting_row(
                        body,
                        "Hold-to-talk",
                        "Hold the shortcut while you speak, release to stop.",
                        self.hold_to_talk,
                    ),
                ],
            )
        )

        layout.addWidget(
            _section(
                body,
                "Behavior",
                [
                    _setting_row(
                        body,
                        "Instant start",
                        "Keep the mic open so recording begins with no delay.",
                        self.keep_mic_warm,
                    ),
                    _setting_row(
                        body,
                        "Pause music while I dictate",
                        "Automatically resumes playback when you're done.",
                        self.pause_media,
                    ),
                    _setting_row(
                        body,
                        "Play a sound when recording starts and stops",
                        "A soft cue so you always know when the mic is live.",
                        self.cue_sounds,
                    ),
                    _setting_row(body, "Cue sound", "", cue_control),
                    _setting_row(
                        body,
                        "Skip silent parts automatically",
                        "Trims long pauses for faster, cleaner transcripts.",
                        self.vad,
                    ),
                    _setting_row(
                        body,
                        "Type the result where my cursor is",
                        "Drops the finished text into the app you were using.",
                        self.auto_paste,
                    ),
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
        self.device.setCurrentText(
            config.device if config.device in DEVICES else "auto"
        )
        self.device.setMinimumWidth(160)

        self.compute = QComboBox(self)
        self.compute.addItems(COMPUTE_TYPES)
        self.compute.setCurrentText(
            config.compute_type if config.compute_type in COMPUTE_TYPES else "auto"
        )
        self.compute.setMinimumWidth(160)

        self.idle_unload = QComboBox(self)
        for label, minutes in IDLE_UNLOAD_OPTIONS:
            self.idle_unload.addItem(label, minutes)
        idle_idx = self.idle_unload.findData(config.idle_unload_minutes)
        self.idle_unload.setCurrentIndex(idle_idx if idle_idx >= 0 else 2)
        self.idle_unload.setMinimumWidth(200)

        body = QWidget(self)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(28, 24, 28, 28)
        layout.setSpacing(22)

        layout.addWidget(
            _page_header(
                body,
                "Advanced",
                "Fine-tune performance for your hardware. The defaults work "
                "well for most Macs.",
                icon="tune",
            )
        )

        layout.addWidget(
            _section(
                body,
                "Performance",
                [
                    _setting_row(
                        body,
                        "Device",
                        "The hardware used for AI processing.",
                        self.device,
                    ),
                    _setting_row(
                        body,
                        "Compute type",
                        "Numeric precision of the model weights.",
                        self.compute,
                    ),
                ],
            )
        )

        layout.addWidget(
            _section(
                body,
                "Memory",
                [
                    _setting_row(
                        body,
                        "Free memory when idle",
                        "Unloads the speech model after inactivity; the next "
                        "dictation reloads it automatically.",
                        self.idle_unload,
                    ),
                ],
            )
        )

        layout.addStretch(1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(_scroll_page(body))


class SettingsDialog(QDialog):
    # (icon, title, subtitle) for each sidebar entry, in order.
    _NAV = [
        ("settings", "General", "Language, shortcuts & behavior"),
        ("sparkles", "AI Modes", "Rewrite what you dictate"),
        ("package", "Models", "Speech-to-text engines"),
        ("tune", "Advanced", "Performance & memory"),
    ]

    def __init__(self, config: Config, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("AuraWhisper — Settings")
        # The UI is authored left-to-right; pin the direction so a Hebrew/RTL
        # system locale can't mirror the layout and clip content off-screen.
        self.setLayoutDirection(Qt.LeftToRight)
        # Lay out edge-to-edge under the transparent title bar ourselves;
        # otherwise Qt insets everything by the title bar's safe area.
        self.setAttribute(Qt.WA_ContentsMarginsRespectsSafeArea, False)
        self._config = config
        self.result_config = replace(config)

        # Pin a dark palette on the dialog so unstyled surfaces (e.g. the scroll
        # viewport, which draws with the Base role) stay dark even when the
        # system is in light mode. Scoped to this dialog; propagates to children.
        palette = self.palette()
        for role in (QPalette.Window, QPalette.Base):
            palette.setColor(role, QColor("#1E1E20"))
        for role in (QPalette.WindowText, QPalette.Text):
            palette.setColor(role, QColor("#F5F5F7"))
        self.setPalette(palette)

        self.setStyleSheet(load_styles())

        self._general_page = GeneralPage(config, self)
        self._modes_page = AIModesPage(config, self)
        self._models_page = ModelsPage(
            config.model_path, config.custom_model_paths, self
        )
        self._advanced_page = AdvancedPage(config, self)

        pages = [
            self._general_page,
            self._modes_page,
            self._models_page,
            self._advanced_page,
        ]

        # --- left sidebar: floating panel with app identity + tiled nav ---
        sidebar = QFrame(self)
        sidebar.setObjectName("settingsSidebar")
        sidebar.setFixedWidth(224)
        side = QVBoxLayout(sidebar)
        # Top inset clears the native traffic-light buttons, which sit inside
        # the sidebar once the title bar is made transparent.
        side.setContentsMargins(10, 44, 10, 12)
        side.setSpacing(2)

        identity = QWidget(sidebar)
        identity.setObjectName("appIdentity")
        id_row = QHBoxLayout(identity)
        id_row.setContentsMargins(8, 8, 8, 8)
        id_row.setSpacing(10)
        id_row.addWidget(icon_tile("mic", 34, identity, circle=True))
        id_text = QVBoxLayout()
        id_text.setContentsMargins(0, 0, 0, 0)
        id_text.setSpacing(0)
        brand_title = QLabel("AuraWhisper", identity)
        brand_title.setObjectName("brandTitle")
        kicker = QLabel("Private · On-device", identity)
        kicker.setObjectName("brandKicker")
        id_text.addWidget(brand_title)
        id_text.addWidget(kicker)
        id_row.addLayout(id_text, 1)
        side.addWidget(identity)
        side.addSpacing(10)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._nav_buttons: list[QPushButton] = []
        for i, (icon_name, title, subtitle) in enumerate(self._NAV):
            btn = QPushButton(f"  {title}", sidebar)
            btn.setProperty("navItem", True)
            btn.setCheckable(True)
            btn.setToolTip(subtitle)
            btn.setIconSize(QSize(22, 22))
            btn.setIcon(QIcon(tile_pixmap(icon_name, 22)))
            btn.clicked.connect(lambda _=False, idx=i: self._select_page(idx))
            self._nav_group.addButton(btn, i)
            self._nav_buttons.append(btn)
            side.addWidget(btn)
        side.addStretch(1)

        self._stack = QStackedWidget(self)
        for page in pages:
            self._stack.addWidget(page)

        # --- bottom action bar (detail pane only, like System Settings) ---
        footer = QFrame(self)
        footer.setObjectName("settingsFooter")
        footer.setFixedHeight(56)
        footer_row = QHBoxLayout(footer)
        footer_row.setContentsMargins(20, 0, 20, 0)
        footer_row.setSpacing(10)
        footer_row.addStretch(1)
        cancel_btn = QPushButton("Cancel", footer)
        cancel_btn.setObjectName("cancelBtn")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Save", footer)
        save_btn.setObjectName("saveBtn")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._accept)
        footer_row.addWidget(cancel_btn)
        footer_row.addWidget(save_btn)

        detail = QVBoxLayout()
        detail.setContentsMargins(0, 12, 0, 0)
        detail.setSpacing(0)
        detail.addWidget(self._stack, 1)
        detail.addWidget(footer)

        layout = QHBoxLayout(self)
        # The sidebar floats: inset from the window edges like macOS Tahoe.
        layout.setContentsMargins(8, 8, 0, 8)
        layout.setSpacing(0)
        layout.addWidget(sidebar, 0)
        layout.addSpacing(4)
        layout.addLayout(detail, 1)
        self._sidebar = sidebar
        self._native_styled = False

        self._select_page(0)
        self._fit_to_screen()

    def _select_page(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        self._nav_buttons[index].setChecked(True)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._native_styled:
            self._native_styled = True
            # Transparent title bar; the sidebar runs up under the traffic
            # lights. If this fails the top inset is simply empty space.
            if not style_native_window(self):
                self._sidebar.layout().setContentsMargins(10, 14, 10, 12)

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
            custom_model_paths=self._models_page.custom_model_paths,
            english_model_path=g.english_model.currentData() or "",
            language=g.language.currentData() or "auto",
            hotkey=g.hotkey.combo() or "<cmd>+<shift>+<space>",
            ai_hotkey=g.ai_hotkey.combo() or "<cmd>+<shift>+<alt>+<space>",
            rewrite_selection_hotkey=g.rewrite_selection_hotkey.combo(),
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
