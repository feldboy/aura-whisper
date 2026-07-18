from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPoint, QSize, Qt, QThread, QTimer, Slot
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from aura_whisper.audio.recorder import Recorder
from aura_whisper.audio import cues
from aura_whisper.config import Config
from aura_whisper.hotkey.global_hotkey import GlobalHotkey
from aura_whisper.llm.worker import LLMWorker
from aura_whisper.media import MediaController
from aura_whisper.paste.active_app import ActiveAppPaster
from aura_whisper.transcribe.worker import TranscribeWorker
from aura_whisper.ui.hud import RecordingHUD
from aura_whisper.ui.settings_dialog import SettingsDialog
from aura_whisper.ui.transcription_view import TranscriptionView
from aura_whisper.ui.waveform import Waveform
from aura_whisper.vibrancy import apply_vibrancy, style_native_window
from aura_whisper.ui.ui_kit import load_styles


def _make_tray_icon() -> QIcon:
    """Simple microphone glyph, rendered as a template (mask) icon."""
    pm = QPixmap(44, 44)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(0, 0, 0), 3)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(QColor(0, 0, 0))
    p.drawRoundedRect(16, 5, 12, 20, 6, 6)  # capsule
    p.setBrush(Qt.NoBrush)
    p.drawArc(10, 12, 24, 20, 180 * 16, 180 * 16)  # cradle
    p.drawLine(22, 32, 22, 38)  # stem
    p.drawLine(15, 38, 29, 38)  # base
    p.end()
    pm.setDevicePixelRatio(2.0)
    icon = QIcon(pm)
    icon.setIsMask(True)  # adapts to light/dark menu bar on macOS
    return icon


def _activate_app() -> None:
    """Bring our (dock-less) app forward so dialogs get focus."""
    try:
        from AppKit import (  # type: ignore
            NSApplicationActivateIgnoringOtherApps,
            NSRunningApplication,
        )

        NSRunningApplication.currentApplication().activateWithOptions_(
            NSApplicationActivateIgnoringOtherApps
        )
    except Exception:
        pass


class RootFrame(QWidget):
    """Rounded translucent background frame."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("root")
        self.setAttribute(Qt.WA_StyledBackground, False)
        # When True, the native NSVisualEffectView (vibrancy) shows through and
        # this widget paints nothing. Falls back to a solid panel otherwise.
        self._glass = False

    def paintEvent(self, _event) -> None:  # noqa: N802
        if self._glass:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(self.rect().adjusted(0, 0, -1, -1), 18, 18)
        painter.fillPath(path, QColor(18, 18, 26, 210))
        painter.setPen(QColor(255, 255, 255, 28))
        painter.drawPath(path)


class TitleBar(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(42)
        self.setObjectName("titleBar")

        self.title = QLabel("AuraWhisper", self)
        self.title.setObjectName("titleLabel")

        self.mode_label = QLabel("", self)
        self.mode_label.setObjectName("modeLabel")
        self.mode_label.setStyleSheet("color: rgba(255,255,255,120); font-size: 11px;")

        self.settings_btn = QPushButton("⚙", self)
        self.settings_btn.setObjectName("toolBtn")
        self.settings_btn.setCursor(Qt.PointingHandCursor)
        self.settings_btn.setFixedSize(QSize(28, 24))

        # Left inset leaves room for the native macOS traffic-light controls.
        layout = QHBoxLayout(self)
        layout.setContentsMargins(78, 6, 12, 4)
        layout.setSpacing(8)
        layout.addWidget(self.title)
        layout.addStretch(1)
        layout.addWidget(self.mode_label)
        layout.addWidget(self.settings_btn)


class MainWindow(QMainWindow):
    def __init__(self, config: Config) -> None:
        super().__init__()
        self._config = config
        self._drag_offset: QPoint | None = None
        self._quitting = False

        self.setWindowTitle("AuraWhisper")
        self.resize(560, 320)
        # Let the native NSWindow / vibrancy show through Qt's own fill.
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._native_styled = False

        self._root = RootFrame(self)
        self.setCentralWidget(self._root)

        self._title_bar = TitleBar(self._root)
        self._waveform = Waveform(self._root)
        self._transcription = TranscriptionView(self._root)

        layout = QVBoxLayout(self._root)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(4)
        layout.addWidget(self._title_bar)
        layout.addWidget(self._waveform)
        layout.addWidget(self._transcription, 1)

        self._title_bar.settings_btn.clicked.connect(self.open_settings)

        self._hud = RecordingHUD()

        self._pending_mode: dict | None = None

        self._recorder = Recorder(self)
        self._recorder.frame_ready.connect(self._waveform.push_frame)
        self._recorder.frame_ready.connect(self._hud.waveform.push_frame)
        self._recorder.stopped.connect(self._on_recording_stopped)
        self._recorder.error.connect(self._on_error)

        self._worker = TranscribeWorker(config)
        self._worker_thread = QThread(self)
        self._worker.moveToThread(self._worker_thread)
        self._worker_thread.start()
        self._worker.text_ready.connect(self._on_text_ready)
        self._worker.error.connect(self._on_error)
        self._worker.started_processing.connect(self._on_transcribe_started)
        self._worker.model_loaded.connect(self._on_model_loaded)

        self._llm = LLMWorker(config)
        self._llm_thread = QThread(self)
        self._llm.moveToThread(self._llm_thread)
        self._llm_thread.start()
        self._llm.text_ready.connect(self._on_ai_text_ready)
        self._llm.error.connect(self._on_error)
        self._llm.started_processing.connect(self._on_rewrite_started)

        self._paste = ActiveAppPaster()

        self._media = MediaController()

        self._hotkey = GlobalHotkey(config.hotkey, self)
        self._hotkey.pressed.connect(lambda: self._on_hotkey_pressed(None))
        self._hotkey.released.connect(lambda: self._on_hotkey_released())
        self._hotkey.error.connect(self._on_error)
        self._hotkey.start()

        self._ai_hotkey = GlobalHotkey(config.ai_hotkey, self)
        self._ai_hotkey.pressed.connect(self._on_ai_hotkey_pressed)
        self._ai_hotkey.released.connect(lambda: self._on_hotkey_released())
        self._ai_hotkey.error.connect(self._on_error)
        self._ai_hotkey.start()

        self._mode_hotkeys: list[GlobalHotkey] = []
        self._build_mode_hotkeys()

        self._recorder.set_warm(config.keep_mic_warm)

        self._build_tray()
        self._update_mode_label()

        self._apply_styles()
        # Native chrome + vibrancy are applied once the window first appears
        # (see showEvent), when the underlying NSWindow exists.

        if not config.is_configured:
            QTimer.singleShot(300, self.open_settings)
        else:
            QTimer.singleShot(200, self._worker.preload_requested.emit)

    def _apply_styles(self) -> None:
        self.setStyleSheet(load_styles())

    # --- tray / background-app behavior ---

    def _build_tray(self) -> None:
        self._tray = QSystemTrayIcon(_make_tray_icon(), self)
        self._tray.setToolTip("AuraWhisper")
        menu = QMenu()

        self._mode_menu = QMenu("AI Mode", menu)
        menu.addMenu(self._mode_menu)
        self._rebuild_mode_menu()

        show_action = QAction("Open AuraWhisper", menu)
        show_action.triggered.connect(self._show_window)
        menu.addAction(show_action)

        settings_action = QAction("Settings…", menu)
        settings_action.triggered.connect(self.open_settings)
        menu.addAction(settings_action)

        menu.addSeparator()
        quit_action = QAction("Quit AuraWhisper", menu)
        quit_action.triggered.connect(self.quit_app)
        menu.addAction(quit_action)

        self._tray_menu = menu  # keep a reference; tray does not own it
        self._tray.setContextMenu(menu)
        self._tray.show()

    def _rebuild_mode_menu(self) -> None:
        self._mode_menu.clear()
        group = QActionGroup(self._mode_menu)
        group.setExclusive(True)
        for mode in self._config.modes:
            if not mode.get("enabled", True):
                continue
            name = mode.get("name", "?")
            action = QAction(name, self._mode_menu)
            action.setCheckable(True)
            action.setChecked(name == self._config.active_mode)
            action.triggered.connect(
                lambda _=False, n=name: self._set_active_mode(n)
            )
            group.addAction(action)
            self._mode_menu.addAction(action)

    def _set_active_mode(self, name: str) -> None:
        self._config.active_mode = name
        self._config.save()
        self._update_mode_label()

    def _show_window(self) -> None:
        self.show()
        self.raise_()
        _activate_app()

    def quit_app(self) -> None:
        self._quitting = True
        self._tray.hide()
        self._hud.hide()
        self.close()
        from PySide6.QtWidgets import QApplication

        QApplication.quit()

    # --- settings ---

    def open_settings(self) -> None:
        _activate_app()
        dialog = SettingsDialog(self._config, self)
        if dialog.exec():
            self._config = dialog.result_config
            self._config.save()
            self._worker.update_config(self._config)
            self._llm.update_config(self._config)
            self._hotkey.set_combo(self._config.hotkey)
            self._ai_hotkey.set_combo(self._config.ai_hotkey)
            self._build_mode_hotkeys()
            self._recorder.set_warm(self._config.keep_mic_warm)
            self._update_mode_label()
            self._rebuild_mode_menu()
            if self._config.is_configured:
                QTimer.singleShot(200, self._worker.preload_requested.emit)

    def _update_mode_label(self) -> None:
        mode = self._config.get_active_mode()
        self._title_bar.mode_label.setText(
            f"AI: {mode['name']}" if mode else "AI: off"
        )

    # --- dictation pipeline ---

    def _set_status(self, text: str) -> None:
        self._transcription.set_status(text)
        self._hud.set_status(text)

    def _set_busy_status(self, text: str) -> None:
        """Status + animated 'working…' indicator for long steps."""
        self._transcription.set_status(text + "…")
        self._hud.set_busy(True, text)

    @Slot()
    def _on_transcribe_started(self) -> None:
        self._set_busy_status("Transcribing")

    @Slot()
    def _on_model_loaded(self) -> None:
        self._transcription.set_status("Model ready")

    @Slot(str)
    def _on_rewrite_started(self, model: str) -> None:
        self._set_busy_status(f"Rewriting · {model}")

    def _on_hotkey_pressed(self, mode: dict | None) -> None:
        if self._config.hold_to_talk:
            self._start_recording(mode)
            return
        # Toggle mode: first press starts, second press stops & delivers.
        if self._recorder.is_recording():
            self._stop_recording()
        else:
            self._start_recording(mode)

    def _on_ai_hotkey_pressed(self) -> None:
        mode = self._config.get_active_mode()
        if mode is None:
            self._set_status("No AI mode enabled — check Settings")
            return
        self._on_hotkey_pressed(mode)

    def _build_mode_hotkeys(self) -> None:
        """Register one global hotkey per AI mode that has a shortcut set."""
        for hk in self._mode_hotkeys:
            hk.stop()
        self._mode_hotkeys = []
        used = {self._config.hotkey, self._config.ai_hotkey}
        for mode in self._config.modes:
            combo = (mode.get("hotkey") or "").strip()
            if not combo or not mode.get("enabled", True) or combo in used:
                continue
            used.add(combo)
            hk = GlobalHotkey(combo, self)
            hk.pressed.connect(lambda m=mode: self._on_hotkey_pressed(m))
            hk.released.connect(lambda: self._on_hotkey_released())
            hk.error.connect(self._on_error)
            hk.start()
            self._mode_hotkeys.append(hk)

    def _on_hotkey_released(self) -> None:
        if self._config.hold_to_talk:
            self._stop_recording()

    def _start_recording(self, mode: dict | None) -> None:
        if self._recorder.is_recording():
            return
        if not self._config.is_configured:
            self._set_status("Set model folder in Settings")
            return
        self._pending_mode = mode
        self._paste.remember_frontmost()
        self._waveform.set_active(True)
        self._hud.set_recording(True)
        if mode is not None:
            status = f"Listening… ({mode.get('name', 'AI')} mode)"
        else:
            status = "Listening…"
        self._transcription.set_status(status)
        self._hud.show_pill(status)
        # Pause music *before* opening the mic, so the Bluetooth profile
        # downgrade is never audible.
        if self._config.pause_media_while_recording:
            self._media.pause()
        if getattr(self._config, "cue_sounds", True):
            cues.play_start()
        self._recorder.start()

    def _stop_recording(self) -> None:
        if not self._recorder.is_recording():
            return
        self._waveform.set_active(False)
        self._hud.set_recording(False)
        self._set_status("Processing…")
        if getattr(self._config, "cue_sounds", True):
            cues.play_stop()
        self._recorder.stop()
        if self._config.pause_media_while_recording:
            self._media.resume()

    def _on_recording_stopped(self, buffer: np.ndarray) -> None:
        if buffer.size < 1600:
            self._hud.set_busy(False)
            self._set_status("Too short")
            self._hud.hide_soon()
            return
        QTimer.singleShot(0, lambda: self._worker.transcribe_requested.emit(buffer))

    def _on_text_ready(self, text: str) -> None:
        if not text.strip():
            self._hud.set_busy(False)
            self._set_status("No speech detected")
            self._hud.hide_soon()
            return
        mode = self._pending_mode
        self._pending_mode = None
        if mode is not None:
            self._llm.rewrite_requested.emit(text, mode)
            return
        self._deliver(text)

    def _on_ai_text_ready(self, text: str) -> None:
        self._deliver(text)

    def _deliver(self, text: str) -> None:
        self._hud.set_busy(False)
        self._transcription.append_text(text)
        if self._config.auto_paste and text.strip():
            self._paste.paste(text)
            self._hud.set_status("Pasted ✓")
        else:
            self._hud.set_status("Ready — copied to app window")
        self._hud.hide_soon()

    def _on_error(self, message: str) -> None:
        self._hud.set_busy(False)
        self._set_status(message)
        self._hud.hide_soon(3000)

    # --- window chrome ---

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            local = event.position().toPoint() if hasattr(event, "position") else event.pos()
            if self._title_bar.geometry().contains(local):
                self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        # Esc dismisses the window; dictation keeps running in the menu bar.
        if event.key() == Qt.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._native_styled:
            return
        self._native_styled = True

        def _apply_native() -> None:
            style_native_window(self)
            if apply_vibrancy(self):
                self._root._glass = True
                self._root.update()

        # Defer one tick so the NSWindow is fully realized.
        QTimer.singleShot(0, _apply_native)

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self._quitting:
            # Background app: closing the window keeps dictation running.
            event.ignore()
            self.hide()
            return
        try:
            self._hotkey.stop()
            self._ai_hotkey.stop()
        except Exception:
            pass
        try:
            self._recorder.shutdown()
        except Exception:
            pass
        for thread in (self._worker_thread, self._llm_thread):
            thread.quit()
            thread.wait(2000)
        super().closeEvent(event)
