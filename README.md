# AuraWhisper

A local-first Whisper dictation app for macOS, modeled after MacWhisper /
Superwhisper / Wispr Flow. 100% offline inference via whisper.cpp using
Whisper models on disk (Hebrew + English work great with large-v3-turbo).
PySide6 UI with a Siri-style animated waveform, push-to-talk global hotkey,
and paste-into-active-app.

New in v2:

- **Model manager** — Settings → Models lists every whisper model on disk
  (including your SuperWhisper models), lets you switch with one click, add a
  file, or download curated models (incl. an ivrit.ai Hebrew-tuned turbo)
  with a progress bar.
- **AI modes** — hold the AI hotkey (default **⌘⇧⌥Space**), ramble, and a
  local LLM via [Ollama](https://ollama.com) rewrites the transcript per the
  active mode: Cleanup (remove fillers), Email (turn rough speech into a
  ready-to-send email), Summarize, or your own custom prompt. Replies in the
  language you spoke — Hebrew in, Hebrew out. Manage modes in
  Settings → AI Modes.

## Requirements

- macOS 12+ (Apple Silicon or Intel).
- Python 3.10+.
- A CTranslate2-format Whisper model folder on disk. If you have `.pt` /
  OpenAI-format weights, convert them once with
  `ct2-transformers-converter` (ships with `faster-whisper`).

## Install

```bash
cd /Users/yaronfeldboy/Documents/whisper
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Run

```bash
python main.py
```

On first launch, the settings dialog opens. Click **Browse…** and point
AuraWhisper at the folder containing your CTranslate2 model (the folder
with `model.bin` and `config.json`).

## Use

1. Place the cursor in any text field in any app (Notes, Slack, your IDE).
2. Tap your dictation hotkey once, speak, tap again — the transcript is
   typed where your cursor is. (Prefer push-to-talk? Enable "Hold-to-talk"
   in Settings → General.)
3. Or tap the AI hotkey — speak roughly ("I don't know exactly what to
   write but tell him I'm coming home soon…") and the active mode's LLM
   prompt turns it into the finished text before pasting.

Speed: the app keeps the mic warm (recording starts in ~20 ms) and runs a
persistent `whisper-server` so the model loads once and stays on the GPU —
transcription of a few seconds of speech returns in about a second. With
language set to Auto, each dictation is detected as Hebrew or English on
its own, so you can switch languages freely between messages.

The title bar shows the active AI mode. Change hotkeys, language, models,
and AI modes in **Settings** (⚙ icon).

AI modes need Ollama running (`ollama serve` or the Ollama menu-bar app)
with at least one local model pulled (e.g. `ollama pull gemma4:12b`). If it
isn't running, AuraWhisper shows "Ollama is not running" instead of hanging.

## macOS permissions

First launch will trigger prompts for:

- **Microphone** — required for audio capture.
- **Accessibility** — required for the global hotkey and for synthesizing
  ⌘V into the target app. Grant this to whatever is running Python
  (Terminal.app, iTerm, your IDE, or the packaged `.app`).
- **Input Monitoring** — may also be requested by `pynput`.

If the hotkey does nothing, it's almost always this — re-grant
Accessibility to the exact binary in
*System Settings → Privacy & Security → Accessibility*.

## How it works

```
hotkey (pynput) ─press──▶ Recorder (sounddevice, 16kHz mono)
                              │
                              │ float32 frames
                              ▼
                         Waveform widget (FFT → 48 glowing bars)
                              │
hotkey ─release──▶ Recorder.stop() ──buffer──▶ TranscribeWorker (QThread)
                                                      │
                                                      │ faster-whisper
                                                      ▼
                                               text ready
                                                      │
                                         ┌────────────┴──────────┐
                                         ▼                       ▼
                                 TranscriptionView        Paste (NSPasteboard
                                 + copy button             + synthetic ⌘V into
                                                           remembered app)
```

## Project layout

```
aura_whisper/
├── __main__.py             # QApplication entry
├── config.py               # JSON settings in ~/Library/Application Support
├── vibrancy.py             # NSVisualEffectView bridge (optional)
├── audio/
│   ├── recorder.py         # sounddevice capture with Qt signals
│   └── meter.py            # FFT → log-spaced band magnitudes
├── transcribe/
│   ├── engine.py           # whisper.cpp subprocess wrapper (lazy-loaded)
│   └── worker.py           # QThread-side worker
├── models/
│   └── manager.py          # scan disk for models, curated HF downloads
├── llm/
│   ├── ollama_client.py    # Ollama HTTP API (stdlib urllib)
│   └── worker.py           # QThread-side AI rewrite worker
├── ui/
│   ├── main_window.py      # frameless translucent window + orchestration
│   ├── waveform.py         # Siri-style animated spectrum
│   ├── transcription_view.py
│   ├── models_page.py      # Settings → Models tab
│   ├── modes_page.py       # Settings → AI Modes tab
│   └── settings_dialog.py  # tabbed: Models / AI Modes / General
├── hotkey/
│   └── global_hotkey.py    # true hold-to-talk using pynput
├── paste/
│   └── active_app.py       # remember frontmost → paste via CGEventPost
└── resources/
    └── styles.qss
```

## Troubleshooting

**"Model path does not exist"** — the model folder must contain
`model.bin` and `config.json` from CTranslate2. Verify with `ls` on the
path you pasted into Settings.

**Hotkey doesn't fire** — Accessibility permission. See above.

**Waveform stays flat while I'm speaking** — Microphone permission.
Check System Settings → Privacy & Security → Microphone.

**First transcription is slow** — the model is loaded lazily on the first
run. Subsequent calls stay warm.

**No sound pasted into target app** — the app needs focus. Some apps
(password managers, secure fields) block synthetic ⌘V; the text is still
on the clipboard and can be pasted manually.

## Out of scope (for now)

- Live streaming / partial results.
- Screen-context awareness (feeding what's on screen to the AI mode) —
  planned; the LLM client already accepts a `context` argument for it.
- Windows / Linux ports.
- Notarized `.app` bundle.
