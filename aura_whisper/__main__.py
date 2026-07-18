from __future__ import annotations

import signal
import socket
import sys

from PySide6.QtCore import QSocketNotifier
from PySide6.QtWidgets import QApplication

from aura_whisper.config import Config
from aura_whisper.transcribe.engine import _kill_spawned_servers, kill_stale_servers
from aura_whisper.ui.main_window import MainWindow


def _hide_dock_icon() -> None:
    """Run as a menu-bar-only (accessory) app — no Dock icon, no app switcher."""
    if sys.platform != "darwin":
        return
    try:
        from AppKit import NSApplication  # type: ignore

        NSApplicationActivationPolicyAccessory = 1
        NSApplication.sharedApplication().setActivationPolicy_(
            NSApplicationActivationPolicyAccessory
        )
    except Exception:
        pass


def _install_signal_cleanup(app: QApplication) -> None:
    """Kill spawned whisper-servers on SIGTERM/SIGINT (e.g. pkill), which
    otherwise bypass atexit and orphan the model processes.

    Uses a self-pipe + QSocketNotifier so the signal is handled reliably at
    Qt's C++ event-loop level, rather than depending on the Python
    interpreter's eval-loop signal delivery (unreliable with many threads).
    """
    rsock, wsock = socket.socketpair()
    rsock.setblocking(False)
    wsock.setblocking(False)
    signal.set_wakeup_fd(wsock.fileno())
    # A Python handler must exist for the signal to reach the wakeup fd.
    signal.signal(signal.SIGTERM, lambda *_: None)
    signal.signal(signal.SIGINT, lambda *_: None)

    notifier = QSocketNotifier(rsock.fileno(), QSocketNotifier.Type.Read)

    def _on_signal() -> None:
        try:
            rsock.recv(64)
        except OSError:
            pass
        _kill_spawned_servers()
        app.quit()

    notifier.activated.connect(_on_signal)
    # Keep references alive for the life of the app.
    app._sig_sockets = (rsock, wsock)
    app._sig_notifier = notifier


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("AuraWhisper")
    app.setOrganizationName("AuraWhisper")
    app.setQuitOnLastWindowClosed(False)

    _hide_dock_icon()

    # Clear any model servers orphaned by a previous crash/force-kill.
    kill_stale_servers()

    config = Config.load()
    window = MainWindow(config)
    if not config.is_configured:
        # First run: show the window so the settings dialog has an anchor.
        window.show()
    # Otherwise stay in the menu bar — hotkeys work everywhere.

    # Install last, so C libraries pulled in by MainWindow (e.g. PortAudio)
    # can't clobber our SIGTERM/SIGINT handling.
    _install_signal_cleanup(app)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
