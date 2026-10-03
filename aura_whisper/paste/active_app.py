from __future__ import annotations

import sys
import time

# macOS virtual keycodes.
C_KEY = 8
V_KEY = 9


class ActiveAppPaster:
    """Remember frontmost app, then paste into it after transcription.

    macOS-only. Falls back gracefully if pyobjc isn't available.
    """

    def __init__(self) -> None:
        self._remembered_pid: int | None = None
        self._is_macos = sys.platform == "darwin"

    def remember_frontmost(self) -> None:
        if not self._is_macos:
            return
        try:
            from AppKit import NSWorkspace

            app = NSWorkspace.sharedWorkspace().frontmostApplication()
            if app is not None:
                self._remembered_pid = int(app.processIdentifier())
        except Exception:
            self._remembered_pid = None

    def paste(self, text: str) -> bool:
        if not text:
            return False
        if not self._is_macos:
            return self._fallback_copy(text)
        try:
            from AppKit import (
                NSPasteboard,
                NSPasteboardTypeString,
                NSRunningApplication,
                NSApplicationActivateIgnoringOtherApps,
            )
        except Exception:
            return self._fallback_copy(text)

        pb = NSPasteboard.generalPasteboard()
        pb.clearContents()
        pb.setString_forType_(text, NSPasteboardTypeString)

        if self.activate_remembered():
            time.sleep(0.08)

        return self._post_cmd_key(V_KEY)

    def activate_remembered(self) -> bool:
        """Bring the remembered app back to the front (our HUD can steal it)."""
        if not self._is_macos or self._remembered_pid is None:
            return False
        try:
            from AppKit import (
                NSApplicationActivateIgnoringOtherApps,
                NSRunningApplication,
            )

            target = NSRunningApplication.runningApplicationWithProcessIdentifier_(
                self._remembered_pid
            )
            if target is None:
                return False
            target.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
            return True
        except Exception:
            return False

    def selected_text_ax(self) -> str | None:
        """The remembered app's selected text via the Accessibility API.

        Doesn't touch the clipboard or send keys. Returns None when the app
        doesn't expose its selection this way (then fall back to ⌘C).
        """
        if not self._is_macos or self._remembered_pid is None:
            return None
        try:
            from ApplicationServices import (
                AXUIElementCopyAttributeValue,
                AXUIElementCreateApplication,
            )

            app = AXUIElementCreateApplication(self._remembered_pid)
            err, focused = AXUIElementCopyAttributeValue(
                app, "AXFocusedUIElement", None
            )
            if err or focused is None:
                return None
            err, text = AXUIElementCopyAttributeValue(focused, "AXSelectedText", None)
            if err or text is None:
                return None
            return str(text)
        except Exception:
            return None

    # --- reading the current selection (for "rewrite selection") ---

    def modifiers_down(self) -> bool:
        """True while any of ⌘ ⇧ ⌥ ⌃ is physically held.

        The synthetic ⌘C must wait for the user to let go of the hotkey's
        modifiers, or apps see e.g. ⌃⌘C instead of a plain copy.
        """
        if not self._is_macos:
            return False
        try:
            from Quartz import (
                CGEventSourceFlagsState,
                kCGEventFlagMaskAlternate,
                kCGEventFlagMaskCommand,
                kCGEventFlagMaskControl,
                kCGEventFlagMaskShift,
                kCGEventSourceStateHIDSystemState,
            )
        except Exception:
            return False
        mask = (
            kCGEventFlagMaskCommand
            | kCGEventFlagMaskShift
            | kCGEventFlagMaskAlternate
            | kCGEventFlagMaskControl
        )
        return bool(CGEventSourceFlagsState(kCGEventSourceStateHIDSystemState) & mask)

    def pasteboard_change_count(self) -> int:
        try:
            from AppKit import NSPasteboard

            return int(NSPasteboard.generalPasteboard().changeCount())
        except Exception:
            return -1

    def send_copy(self) -> bool:
        """Press ⌘C in the frontmost app to copy its current selection."""
        if not self._is_macos:
            return False
        return self._post_cmd_key(C_KEY)

    def copied_text(self, since_change_count: int) -> str | None:
        """Clipboard text if the clipboard changed since ``since_change_count``
        (i.e. our ⌘C actually copied something), else None."""
        try:
            from AppKit import NSPasteboard, NSPasteboardTypeString

            pb = NSPasteboard.generalPasteboard()
            if int(pb.changeCount()) == since_change_count:
                return None
            text = pb.stringForType_(NSPasteboardTypeString)
            return str(text) if text is not None else ""
        except Exception:
            return None

    def _post_cmd_key(self, keycode: int) -> bool:
        try:
            from Quartz import (
                CGEventCreateKeyboardEvent,
                CGEventPost,
                CGEventSetFlags,
                kCGEventFlagMaskCommand,
                kCGHIDEventTap,
            )
        except Exception:
            return False

        down = CGEventCreateKeyboardEvent(None, keycode, True)
        up = CGEventCreateKeyboardEvent(None, keycode, False)
        CGEventSetFlags(down, kCGEventFlagMaskCommand)
        CGEventSetFlags(up, kCGEventFlagMaskCommand)
        CGEventPost(kCGHIDEventTap, down)
        CGEventPost(kCGHIDEventTap, up)
        return True

    def _fallback_copy(self, text: str) -> bool:
        try:
            from PySide6.QtGui import QGuiApplication

            QGuiApplication.clipboard().setText(text)
            return False
        except Exception:
            return False
