# AuraWhisper — Settings Redesign Plan

Goal: restyle the **Settings window** to match the Stitch "macOS Sonoma / Aura"
mockups — modern, friendly, glassy — **without removing or changing any existing
capability**. Inspiration, not a pixel-perfect clone. Scope for now: the Settings
dialog only (HUD, transcription window and tray keep their current look).

---

## 1. What changes visually (mockup vs. current)

| Area | Current | Target (mockups) |
|------|---------|------------------|
| **Palette** | ad-hoc `#6e7dff` accent, `#1a1b24` bg | Aura tokens: `primary #bdc2ff`, `primary-container #7886ff`, `surface #12131b`, layered translucent surfaces |
| **Sidebar** | `QListWidget` with emoji + title + tooltip | Branding header ("AuraWhisper / Settings") + icon-and-label nav rows; active row = periwinkle plate with filled icon |
| **Section titles** | Bold title *inside* each card | Uppercase tracked `section-header` caption *above* each inset-grouped card |
| **Cards** | Rounded panel, title inside | "Inset grouped" cards: 12px radius, `white/8` hairline border, `white/3` fill, rows split by 0.5px dividers |
| **Setting rows** | Form rows / stacked checkboxes | `label + sub-caption` on the left, control on the right, justified, consistent padding |
| **Toggles** | Square `QCheckBox` indicator | Pill toggle switch (36×20), periwinkle track when on, white knob |
| **Footer** | `QDialogButtonBox` in the layout | Fixed footer bar with top border: translucent **Cancel** + periwinkle **Save** on the right |
| **Model rows** | Text + button in a column | Row with title, "Recommended" badge, size, description, and a green "Installed" pill / periwinkle "Download" button |
| **Ollama status** | Plain hint text | Colored dot + pill ("Connected — N models available") |
| **Shortcut keys** | Mod-key buttons (already close) | Keycap chips (⌘ ⇧ Z) with active-key styling + Record button |
| **Icons** | Emoji | Bundled monochrome SVGs, tinted per state |

---

## 2. Capabilities to preserve (must all keep working)

**General page**
- Language dropdown (14 languages) · optional English model dropdown
- Dictate hotkey · Dictate-with-AI hotkey (record/edit) · Hold-to-talk
- Instant start (keep mic warm) · Pause media · Cue sounds toggle + sound picker + preview ▶
- Skip silent parts (VAD) · Type-at-cursor (auto-paste)

**AI Modes page**
- Ollama URL + Refresh · Default model dropdown · connection status
- Mode list · New / Delete / Set-as-active · per-mode Name, Prompt, Model, Shortcut, Enabled

**Models page**
- Active model dropdown · Add model file… · curated download rows with live progress + retry
- Ollama URL + check · Model path (advanced)

**Advanced page**
- Device · Compute type · Free-memory-when-idle

Every `Config` field written in `SettingsDialog._accept()` stays wired to a control.

---

## 3. Implementation approach (PySide6 + QSS, incremental)

### Step 1 — Design tokens & stylesheet foundation
- Add the Aura color tokens as the single source of truth in `styles.qss`.
- Update accent usages to `primary #bdc2ff` / `primary-container #7886ff`, surfaces to the
  layered `surface-*` values, hairline borders to `white/8`.

### Step 2 — New reusable widgets in `ui_kit.py`
- `ToggleSwitch(QAbstractButton)` — painted pill toggle; exposes `isChecked()/setChecked()`
  so it is a drop-in for the current checkboxes.
- `inset_card(...)` — card with an **external** uppercase section caption + hairline body.
- `setting_row(label, subtitle, control)` — left text block + right control, with divider support.
- `pill(text, tone)` — status/badge pill (green "Installed", accent "Recommended", etc.).
- SVG icon loader + tinting helper.

### Step 3 — Sidebar + window shell
- Replace the emoji nav with branding header + icon/label nav rows and the new active-plate style.
- Add a fixed footer action bar (Cancel / Save) with a top divider; keep the existing
  accept/reject wiring.

### Step 4 — Port each page to the new building blocks
- **General**: language/English-model as rows; behavior toggles as `setting_row` + `ToggleSwitch`;
  keep cue sound picker + preview.
- **Advanced**: performance + memory rows.
- **AI Modes**: external captions, connection card with status pill, mode list card with
  action bar, detail editor; keep all handlers.
- **Models**: active-model card, download rows with badges/pills/buttons + progress, Ollama
  card with status pill, advanced path.

### Step 5 — Icons
- Add small SVGs under `resources/icons/` (settings, sparkles, models, sliders, mic, link,
  download, check, star, etc.) and tint them for default/active states.

### Step 6 — Verify
- Launch the app, open Settings, click through all four pages.
- Confirm every control still reads/writes its `Config` value (toggle round-trip, mode CRUD,
  download start, ollama refresh, cue preview).
- `ruff check` clean.

---

## 4. Notes / decisions
- **Scope**: Settings window only for now (HUD etc. unchanged). Palette changes are scoped so
  they don't regress the rest of the app.
- **Icons**: bundled SVGs (no font dependency).
- **Native window chrome** kept (the mockup traffic-lights are illustrative); no move to a
  frameless custom title bar in this pass.
- **Behavioral parity is the hard requirement** — this is a restyle, not a rewrite.

---

## 5. Suggested commit slices
1. tokens + `ui_kit` widgets (ToggleSwitch, inset_card, setting_row, pill) + icons
2. sidebar + footer shell
3. General + Advanced pages ported
4. AI Modes + Models pages ported
5. polish pass + verification
