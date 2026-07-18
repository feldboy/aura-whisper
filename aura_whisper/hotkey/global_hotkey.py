from __future__ import annotations

import sys
from typing import Optional

from PySide6.QtCore import QObject, Signal


NS_COMMAND = 1 << 20
NS_SHIFT = 1 << 17
NS_OPTION = 1 << 19
NS_CONTROL = 1 << 18
NS_DEVICE_INDEPENDENT_MASK = 0xFFFF0000
NS_ALL_MODS = NS_COMMAND | NS_SHIFT | NS_OPTION | NS_CONTROL

MOD_TOKENS = {
    "<cmd>": NS_COMMAND,
    "<command>": NS_COMMAND,
    "<shift>": NS_SHIFT,
    "<alt>": NS_OPTION,
    "<option>": NS_OPTION,
    "<opt>": NS_OPTION,
    "<ctrl>": NS_CONTROL,
    "<control>": NS_CONTROL,
}

KEYCODES: dict[str, int] = {
    "<space>": 49,
    "<return>": 36,
    "<enter>": 36,
    "<tab>": 48,
    "<escape>": 53,
    "<esc>": 53,
    "<delete>": 51,
    "<backspace>": 51,
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7,
    "c": 8, "v": 9, "b": 11, "q": 12, "w": 13, "e": 14, "r": 15,
    "y": 16, "t": 17, "1": 18, "2": 19, "3": 20, "4": 21, "6": 22,
    "5": 23, "9": 25, "7": 26, "8": 28, "0": 29, "o": 31, "u": 32,
    "i": 34, "p": 35, "l": 37, "j": 38, "k": 40, "n": 45, "m": 46,
    "<f1>": 122, "<f2>": 120, "<f3>": 99, "<f4>": 118, "<f5>": 96,
    "<f6>": 97, "<f7>": 98, "<f8>": 100, "<f9>": 101, "<f10>": 109,
    "<f11>": 103, "<f12>": 111,
    # Punctuation (ANSI layout virtual keycodes).
    "-": 27, "=": 24, "[": 33, "]": 30, "\\": 42, ";": 41, "'": 39,
    ",": 43, ".": 47, "/": 44, "`": 50,
    # Arrows & navigation cluster.
    "<left>": 123, "<right>": 124, "<down>": 125, "<up>": 126,
    "<home>": 115, "<end>": 119, "<pageup>": 116, "<pagedown>": 121,
    "<forward_delete>": 117,
}


def _accessibility_trusted(prompt: bool = False) -> bool:
    """Return True if this process is trusted for Accessibility.

    When ``prompt`` is True and the process is not yet trusted, macOS shows the
    system dialog offering to open the Accessibility settings pane.
    """
    if sys.platform != "darwin":
        return True
    try:
        from ApplicationServices import (  # type: ignore
            AXIsProcessTrusted,
            AXIsProcessTrustedWithOptions,
            kAXTrustedCheckOptionPrompt,
        )
    except Exception:
        return True  # can't check — don't block the hotkey
    if not prompt:
        return bool(AXIsProcessTrusted())
    try:
        return bool(AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True}))
    except Exception:
        return bool(AXIsProcessTrusted())


def _parse(combo: str) -> tuple[int, Optional[int]]:
    """Return (modifier_mask, keycode_or_None). keycode None means modifier-only."""
    mods = 0
    keycode: Optional[int] = None
    for raw in combo.lower().split("+"):
        t = raw.strip()
        if not t:
            continue
        if t in MOD_TOKENS:
            mods |= MOD_TOKENS[t]
            continue
        if t in KEYCODES:
            keycode = KEYCODES[t]
            continue
        stripped = t[1:-1] if t.startswith("<") and t.endswith(">") else t
        if stripped in KEYCODES:
            keycode = KEYCODES[stripped]
            continue
        raise ValueError(f"Unknown hotkey token: {t!r}")
    return mods, keycode


class GlobalHotkey(QObject):
    """Hold-to-talk global hotkey using NSEvent monitors (main-thread safe)."""

    pressed = Signal()
    released = Signal()
    error = Signal(str)

    def __init__(self, combo: str, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._combo = combo
        self._mods = 0
        self._keycode: Optional[int] = None
        self._armed = False
        self._global_monitor = None
        self._local_monitor = None
        self._handler_refs: list = []
        try:
            self._mods, self._keycode = _parse(combo)
        except ValueError as e:
            self.error.emit(str(e))

    def set_combo(self, combo: str) -> None:
        was_running = self._global_monitor is not None or self._local_monitor is not None
        if was_running:
            self.stop()
        self._combo = combo
        try:
            self._mods, self._keycode = _parse(combo)
        except ValueError as e:
            self.error.emit(str(e))
            return
        self._armed = False
        if was_running:
            self.start()

    def start(self) -> bool:
        if sys.platform != "darwin":
            self.error.emit("Global hotkey requires macOS in this build.")
            return False
        if self._global_monitor is not None:
            return True
        if self._mods == 0 and self._keycode is None:
            return False

        try:
            from AppKit import NSEvent  # type: ignore
        except Exception as e:
            self.error.emit(f"pyobjc unavailable: {e}")
            return False

        # Global key monitors receive nothing unless the process is trusted for
        # Accessibility. Without this check the hotkey silently does nothing.
        if not _accessibility_trusted(prompt=True):
            self.error.emit(
                "Grant Accessibility permission (System Settings › Privacy & "
                "Security › Accessibility), then restart — the hotkey needs it."
            )
            return False

        # Monitor masks are bit shifts of the event TYPE numbers below.
        NSEventTypeKeyDown = 10
        NSEventTypeKeyUp = 11
        NSEventTypeFlagsChanged = 12
        mask = (
            (1 << NSEventTypeKeyDown)
            | (1 << NSEventTypeKeyUp)
            | (1 << NSEventTypeFlagsChanged)
        )

        def handle(event) -> None:
            try:
                etype = int(event.type())
                flags = int(event.modifierFlags()) & NS_DEVICE_INDEPENDENT_MASK
                # Exact modifier match so <cmd>+<shift>+<space> does not also
                # swallow <cmd>+<shift>+<alt>+<space>.
                mods_match = (flags & NS_ALL_MODS) == self._mods

                if self._keycode is None:
                    if mods_match and not self._armed:
                        self._armed = True
                        self.pressed.emit()
                    elif not mods_match and self._armed:
                        self._armed = False
                        self.released.emit()
                    return

                if etype == NSEventTypeKeyDown:
                    kc = int(event.keyCode())
                    if kc == self._keycode and mods_match and not self._armed:
                        self._armed = True
                        self.pressed.emit()
                elif etype == NSEventTypeKeyUp:
                    kc = int(event.keyCode())
                    if kc == self._keycode and self._armed:
                        self._armed = False
                        self.released.emit()
                elif etype == NSEventTypeFlagsChanged:
                    if self._armed and not mods_match:
                        self._armed = False
                        self.released.emit()
            except Exception as e:
                self.error.emit(f"Hotkey handler error: {e}")

        def local_handle(event):
            handle(event)
            return event

        try:
            self._handler_refs = [handle, local_handle]
            self._global_monitor = (
                NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(mask, handle)
            )
            self._local_monitor = (
                NSEvent.addLocalMonitorForEventsMatchingMask_handler_(mask, local_handle)
            )
        except Exception as e:
            self.error.emit(
                f"Hotkey setup failed (grant Accessibility permission): {e}"
            )
            return False

        if self._global_monitor is None:
            self.error.emit(
                "Hotkey monitor returned None — grant Accessibility to this app."
            )
            return False
        return True

    def stop(self) -> None:
        try:
            from AppKit import NSEvent  # type: ignore

            if self._global_monitor is not None:
                NSEvent.removeMonitor_(self._global_monitor)
            if self._local_monitor is not None:
                NSEvent.removeMonitor_(self._local_monitor)
        except Exception:
            pass
        self._global_monitor = None
        self._local_monitor = None
        self._handler_refs = []
        self._armed = False
