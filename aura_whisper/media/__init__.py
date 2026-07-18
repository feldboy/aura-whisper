from __future__ import annotations

import subprocess

# Players we know how to pause/resume deterministically via AppleScript.
_APPS = ("Spotify", "Music")


def _osascript(script: str, timeout: float = 2.0) -> str:
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout.strip()
    except Exception:
        return ""


class MediaController:
    """Pause music players while dictating, then resume them afterward.

    Uses AppleScript so pause/resume is deterministic — unlike the play/pause
    media key, it never accidentally *starts* playback, and it only resumes the
    players it actually paused. Guards with ``is running`` so it never launches
    an app that was closed.
    """

    def __init__(self) -> None:
        self._paused: list[str] = []

    def pause(self) -> None:
        parts = ['set out to ""']
        for app in _APPS:
            parts.append(
                f'if application "{app}" is running then\n'
                f'  tell application "{app}"\n'
                f'    if player state is playing then\n'
                f'      pause\n'
                f'      set out to out & "{app},"\n'
                f'    end if\n'
                f'  end tell\n'
                f'end if'
            )
        parts.append("return out")
        result = _osascript("\n".join(parts))
        self._paused = [a for a in result.split(",") if a]

    def resume(self) -> None:
        if not self._paused:
            return
        lines = [
            f'if application "{app}" is running then '
            f'tell application "{app}" to play'
            for app in self._paused
        ]
        _osascript("\n".join(lines))
        self._paused = []
