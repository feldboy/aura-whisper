from __future__ import annotations

import sys
import time


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

        if self._remembered_pid is not None:
            try:
                target = NSRunningApplication.runningApplicationWithProcessIdentifier_(
                    self._remembered_pid
                )
                if target is not None:
                    target.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
                    time.sleep(0.08)
            except Exception:
                pass

        return self._post_cmd_v()

    def _post_cmd_v(self) -> bool:
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

        V_KEY = 9  # macOS virtual keycode for 'v'
        down = CGEventCreateKeyboardEvent(None, V_KEY, True)
        up = CGEventCreateKeyboardEvent(None, V_KEY, False)
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
