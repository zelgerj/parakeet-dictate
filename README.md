# Parakeet Dictate

Minimal, 100% local push-to-talk dictation for macOS on Apple Silicon.

Hold the right Option key, speak, release — your speech is transcribed locally with
**NVIDIA Parakeet TDT v3** (`mlx-community/parakeet-tdt-0.6b-v3`, multilingual with
automatic language detection for German/English and more) and inserted at the current
cursor position via clipboard paste (`Cmd+V`).

**100% local.** After the one-time model download (HuggingFace), no audio leaves the
device at runtime — it works offline / in airplane mode too.

---

## Install (end users)

1. Download **`ParakeetDictate.dmg`** from the [latest release (v1.2.1)](../../releases/tag/v1.2.1).
2. Open the DMG and drag **Parakeet Dictate** into the **Applications** folder.
3. Launch it — on first start it walks you through the three required permissions
   (Microphone, Input Monitoring, Accessibility) and downloads the speech model
   (~1–2 GB) once.
4. Hold the **right Option key**, speak, release — the text appears at your cursor.

The app is signed and notarized, so it opens without a Gatekeeper warning.

> The rest of this file describes running **from source** (development).
> To build a release, see [`packaging/RELEASE.md`](packaging/RELEASE.md).

---

## Requirements (from source)

- Apple Silicon Mac (M-series), **macOS 14+**
- [`uv`](https://github.com/astral-sh/uv) or Python **3.11+**
- `ffmpeg` — **only** for the optional core-check script (`test_transcribe.py`).
  The app itself decodes audio in-process and does **not** need ffmpeg.

---

## Setup

```bash
# 1. Create an environment + install dependencies (with uv)
uv venv --python 3.12 .venv
uv pip install -r requirements.txt
```

Alternatively without `uv`:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## Core check first (recommended)

Before the hotkey & paste matter, verify the model + transcription run cleanly on your
machine. A short test WAV can be created with the macOS `say` command:

```bash
say -v Daniel -o sample.aiff "Hello, this is a test with a few words."
ffmpeg -y -i sample.aiff -ar 16000 -ac 1 sample.wav   # needs ffmpeg

.venv/bin/python test_transcribe.py sample.wav
```

On the **first** run the model (~0.6 B parameters) is downloaded from HuggingFace
(a few minutes, depending on your connection). After that it is cached locally and the
model load takes ~1 s. A ~7-second clip is transcribed in under a second.

---

## Usage

```bash
source .venv/bin/activate
python app.py
```

1. Wait until the log says `ready` (the model is loaded and warm).
2. Place the cursor in any text field (TextEdit, browser, Slack, …).
3. **Hold the right Option key** → a short sound, recording is live (🔴).
4. Speak.
5. **Release** → transcription (✍️), then the text is inserted at the cursor + a sound.

The menu-bar icon shows the status: 🎙️ idle · 🔴 recording · ✍️ transcribing.
Quit via **"Quit"** in the menu (or `Ctrl+C` if headless).

German and English work without switching — the language is detected automatically.

---

## macOS permissions

The app — i.e. the **process** that launches it — needs three permissions under
**System Settings → Privacy & Security**:

| Permission | For | Where |
|---|---|---|
| **Microphone** | recording | Privacy & Security → *Microphone* |
| **Accessibility** | simulated `Cmd+V` | Privacy & Security → *Accessibility* |
| **Input Monitoring** | global hotkey listener | Privacy & Security → *Input Monitoring* |

The bundled app requests these via native dialogs on first launch (and the menu has
**"Request permissions…"** to re-trigger them). When running from source, grant the
permissions to your **terminal** / IDE instead.

> **Important:** Input Monitoring and Accessibility only take effect after a restart
> (Microphone is immediate). The menu shows a live ✓/⚠ checklist, and a one-click
> **"Restart now"** does the relaunch for you the moment you've granted them.

---

## Settings

Most options live in the menu-bar **Settings** submenu (persisted to
`~/Library/Application Support/ParakeetDictate/settings.json`):

| Setting | Options | Default |
|---|---|---|
| **Trigger key** | Right Option · Right Command · Right Control · F5 · F6 | Right Option |
| **Mode** | Hold to talk · Tap to start / stop | Hold to talk |
| **Play sounds** | on / off | on |
| **Show 'inserted' banner** | on / off | off |
| **Tidy up text** | light cleanup (capitalize, collapse spaces) | off |
| **Open at Login** | on / off | off |

The menu also shows a live **permission checklist** (✓/⚠ per permission, each links to
its own Settings pane), a **download-progress** line on first run, a one-click
**Restart** after granting permissions, and **Copy last transcript** as a
paste-failure safety net. A few low-level constants remain at the top of `app.py`
(`MODEL_ID`, `SAMPLE_RATE`, `MIN_DURATION_S`, `PASTE_SETTLE_S`, `MAX_RECORDING_S`).

## Privacy

Your audio and transcripts stay on your Mac: after the one-time model download the app
sets `HF_HUB_OFFLINE` (no transcription network), disables HuggingFace telemetry, and
**never writes transcript text to disk** (the log keeps metadata only). The only routine
outbound call is a **daily check to GitHub for app updates** — it sends nothing about you,
verifies the download's Apple notarization + Developer-ID signature before installing, and
can be turned off under **Settings → Updates**. The menu discloses this.

---

## Troubleshooting

- **Hotkey does nothing** (no sound on press) → *Input Monitoring* not granted, or the
  app/terminal wasn't restarted after granting it.
- **Text is not inserted** (log shows the transcription, but nothing appears) →
  *Accessibility* not granted.
- **Silence / empty transcription** → *Microphone* not granted, or the wrong input
  device is selected as the system default.
- **App not in the Microphone list** → it only appears after it has requested access;
  use the menu **"Request permissions…"**.
- **`ffmpeg not found`** (only for `test_transcribe.py`) → `brew install ffmpeg`.

---

## License note

The Parakeet weights are under the **NVIDIA Community Model License**; the MLX
conversion comes via `mlx-community`. Unproblematic for local, internal use. Check the
license terms before any redistribution.

---

## Known upgrade path (context, not implemented)

For a future, production variant the native route is **FluidAudio** (Swift SDK,
Parakeet TDT v3 via CoreML on the Apple Neural Engine, more energy-efficient, very high
realtime factor) — the same foundation VoiceInk and Spokenly use for Parakeet. This v1
deliberately stays Python + `parakeet-mlx` to get something working quickly.
