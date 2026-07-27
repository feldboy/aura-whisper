"""py2app build script.

Build with:  python setup.py py2app
Produces:    dist/AuraWhisper.app
"""

import subprocess
import sys

from py2app.build_app import py2app as py2app_command
from setuptools import setup

# onnxruntime/ctranslate2 ship generated modules with deeply nested if-chains
# that overflow modulegraph's AST walk at the default recursion limit.
sys.setrecursionlimit(10_000)

# py2app only ad-hoc-signs the bundle (no stable Team ID). macOS does not
# reliably persist the Accessibility grant for ad-hoc-signed apps across
# relaunches, so the hotkey's permission prompt (see
# aura_whisper/hotkey/global_hotkey.py) reappears every restart. Re-signing
# with a real (even self-signed) identity gives the bundle a stable
# designated requirement that TCC remembers. Create the identity once with:
#   security find-identity -v -p codesigning
CODESIGN_IDENTITY = "AuraWhisper Local Dev"


class py2app_and_codesign(py2app_command):
    def run(self):
        super().run()
        app_path = f"dist/{self.distribution.get_name()}.app"
        subprocess.run(
            ["codesign", "--force", "--deep", "--sign", CODESIGN_IDENTITY, app_path],
            check=True,
        )

APP = ["main.py"]
OPTIONS = {
    "argv_emulation": False,
    # _sounddevice_data ships libportaudio.dylib as package data, so it
    # needs a full directory copy (packages), not just the includes graph.
    # ctranslate2/onnxruntime ship compiled per-platform shared libraries
    # that py2app's modulegraph walk can miss — force a full copy for those
    # too. Unverified: run an actual CTranslate2 transcription from the
    # packaged .app before shipping this.
    "packages": [
        "aura_whisper",
        "_sounddevice_data",
        "faster_whisper",
        "ctranslate2",
        "onnxruntime",
    ],
    "includes": ["AppKit", "Quartz", "objc", "sounddevice", "cffi", "_cffi_backend"],
    "excludes": ["tkinter"],
    "plist": {
        "CFBundleName": "AuraWhisper",
        "CFBundleDisplayName": "AuraWhisper",
        "CFBundleIdentifier": "com.aurawhisper.app",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "0.1.0",
        "NSHumanReadableCopyright": "AuraWhisper",
        # Menu-bar-only app: no Dock icon, no app switcher entry.
        "LSUIElement": True,
        "NSMicrophoneUsageDescription": (
            "AuraWhisper needs microphone access to transcribe your speech."
        ),
        "NSAppleEventsUsageDescription": (
            "AuraWhisper uses this to paste transcribed text into other apps."
        ),
    },
}

setup(
    app=APP,
    name="AuraWhisper",
    options={"py2app": OPTIONS},
    cmdclass={"py2app": py2app_and_codesign},
)
