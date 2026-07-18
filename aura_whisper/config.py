from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any


APP_SUPPORT_DIR = Path.home() / "Library" / "Application Support" / "AuraWhisper"
CONFIG_PATH = APP_SUPPORT_DIR / "config.json"
MODELS_DIR = APP_SUPPORT_DIR / "models"


def default_modes() -> list[dict]:
    return [
        {
            "name": "Cleanup",
            "prompt": (
                "Clean up this dictated text: remove filler words and false starts, "
                "fix punctuation and casing, keep the meaning and wording as close "
                "to the original as possible."
            ),
            "ollama_model": "",
            "enabled": True,
            "hotkey": "",
        },
        {
            "name": "Email",
            "prompt": (
                "The user dictated a rough idea of an email. Write the email they "
                "intended: clear, polite, well structured, ready to send. Infer a "
                "natural greeting and sign-off if appropriate."
            ),
            "ollama_model": "",
            "enabled": True,
            "hotkey": "",
        },
        {
            "name": "Summarize",
            "prompt": (
                "Summarize the dictated text into its key points. Be concise and "
                "keep all concrete details (names, times, numbers)."
            ),
            "ollama_model": "",
            "enabled": True,
            "hotkey": "",
        },
    ]


@dataclass
class Config:
    model_path: str = ""
    # Optional second model used only when auto-detect finds English speech.
    # Empty = disabled (the main model handles every language).
    english_model_path: str = ""
    language: str = "auto"
    hotkey: str = "<cmd>+<shift>+<space>"
    device: str = "auto"
    compute_type: str = "auto"
    auto_paste: bool = True
    beam_size: int = 1
    vad_filter: bool = True
    initial_prompt: str = ""
    ai_hotkey: str = "<cmd>+<shift>+<alt>+<space>"
    active_mode: str = "Cleanup"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "gemma4:12b"
    modes: list = field(default_factory=default_modes)
    hold_to_talk: bool = False
    keep_mic_warm: bool = False
    pause_media_while_recording: bool = True
    idle_unload_minutes: int = 5
    cue_sounds: bool = True
    cue_sound: str = "harp"

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "Config":
        if not path.exists():
            return cls()
        try:
            data: dict[str, Any] = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self, path: Path = CONFIG_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2))

    @property
    def is_configured(self) -> bool:
        return bool(self.model_path) and Path(self.model_path).exists()

    def get_active_mode(self) -> dict | None:
        for mode in self.modes:
            if mode.get("name") == self.active_mode and mode.get("enabled", True):
                return mode
        for mode in self.modes:
            if mode.get("enabled", True):
                return mode
        return None
