"""
app.py — Parakeet Dictate (macOS)

Push-to-talk dictation: hold a hotkey, speak, release. The speech is transcribed
locally with NVIDIA Parakeet TDT v3 (MLX) and inserted at the cursor via Cmd+V.
100% local after the one-time model download. Menu-bar app (rumps).

Required macOS permissions: Microphone, Accessibility (paste), Input Monitoring (hotkey).
"""

import os

# Privacy: keep HuggingFace quiet and offline-capable. Must be set BEFORE the first
# huggingface_hub import (i.e. before parakeet_mlx). HF_HUB_OFFLINE is set later, once
# the model is cached, so a normal launch makes zero network calls.
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("HF_HUB_DISABLE_HF_TRANSFER", "1")

import json
import queue
import subprocess
import sys
import threading
import time

import mlx.core as mx
import numpy as np
import pyperclip
import sounddevice as sd
from pynput import keyboard
from pynput.keyboard import Controller, Key

from parakeet_mlx import from_pretrained
from parakeet_mlx.audio import get_logmel

# ─── Configuration ───────────────────────────────────────────────────────────
MODEL_ID = "mlx-community/parakeet-tdt-0.6b-v3"
SAMPLE_RATE = 16000
CHANNELS = 1
MIN_DURATION_S = 0.3        # ignore shorter recordings (accidental tap)
MAX_RECORDING_S = 120       # safety cap so a missed key-release can't record forever
PASTE_SETTLE_S = 0.4        # wait for the paste to land before restoring the clipboard
SILENCE_RMS = 0.002         # below this the buffer is treated as "no mic signal"

START_SOUND = "/System/Library/Sounds/Pop.aiff"
DONE_SOUND = "/System/Library/Sounds/Glass.aiff"
FAIL_SOUND = "/System/Library/Sounds/Tink.aiff"

# Curated, safe global trigger keys (name -> (label, pynput Key)).
HOTKEYS = {
    "alt_r": ("Right Option", Key.alt_r),
    "cmd_r": ("Right Command", Key.cmd_r),
    "ctrl_r": ("Right Control", Key.ctrl_r),
    "f5": ("F5", Key.f5),
    "f6": ("F6", Key.f6),
}

ICONS = {
    "loading": "⏳", "downloading": "⤓", "idle": "🎙️",
    "recording": "🔴", "transcribing": "✍️", "error": "⚠️", "restart": "↻",
}

APP_DIR = os.path.expanduser("~/Library/Application Support/ParakeetDictate")
SETTINGS_PATH = os.path.join(APP_DIR, "settings.json")
ONBOARDED_FLAG = os.path.join(APP_DIR, ".onboarded")
FIRST_READY_FLAG = os.path.join(APP_DIR, ".first_ready")
LOG_PATH = os.path.expanduser("~/Library/Logs/ParakeetDictate.log")

DEFAULTS = {
    "hotkey": "alt_r",
    "mode": "hold",                 # "hold" | "toggle"
    "play_sounds": True,
    "show_inserted_banner": False,
    "auto_format": False,
}

SETTINGS_PANES = {
    "Microphone": "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone",
    "Accessibility": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
    "Input Monitoring": "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent",
}

# Shared, cross-thread download progress (plain numbers -> safe to read from the UI).
_dl = {"active": False, "downloaded": 0, "total": 0, "started": 0.0}
# ──────────────────────────────────────────────────────────────────────────────


def load_settings():
    s = dict(DEFAULTS)
    try:
        with open(SETTINGS_PATH) as f:
            s.update({k: v for k, v in json.load(f).items() if k in DEFAULTS})
    except Exception:
        pass
    return s


def save_settings(s):
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        with open(SETTINGS_PATH, "w") as f:
            json.dump(s, f, indent=2)
    except Exception:
        pass


def play(sound_path):
    try:
        subprocess.Popen(["afplay", sound_path],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def open_url(url):
    try:
        subprocess.Popen(["open", url])
    except Exception:
        pass


def _model_is_cached():
    try:
        from huggingface_hub import try_to_load_from_cache
        return bool(try_to_load_from_cache(MODEL_ID, "config.json"))
    except Exception:
        return True


def tidy_text(text):
    """Light, opt-in cleanup: collapse whitespace, capitalize the first letter."""
    text = " ".join(text.split())
    if text:
        text = text[0].upper() + text[1:]
    return text


# ─── Permission checks (read-only; never prompt) ─────────────────────────────
def mic_ok():
    try:
        import AVFoundation
        return AVFoundation.AVCaptureDevice.authorizationStatusForMediaType_(
            AVFoundation.AVMediaTypeAudio) == 3
    except Exception:
        return True


def input_monitoring_ok():
    try:
        from Quartz import CGPreflightListenEventAccess
        return bool(CGPreflightListenEventAccess())
    except Exception:
        return True


def accessibility_ok():
    try:
        from ApplicationServices import AXIsProcessTrusted
        return bool(AXIsProcessTrusted())
    except Exception:
        return True


def request_permissions():
    """Trigger the native system dialogs and register the app in the privacy lists."""
    try:
        import AVFoundation
        mt = AVFoundation.AVMediaTypeAudio
        if AVFoundation.AVCaptureDevice.authorizationStatusForMediaType_(mt) == 0:
            AVFoundation.AVCaptureDevice.requestAccessForMediaType_completionHandler_(
                mt, lambda granted: None)
    except Exception as e:
        print(f"[Perm/Mic] {e}", file=sys.stderr)
    try:
        from Quartz import CGPreflightListenEventAccess, CGRequestListenEventAccess
        if not CGPreflightListenEventAccess():
            CGRequestListenEventAccess()
    except Exception as e:
        print(f"[Perm/Input] {e}", file=sys.stderr)
    try:
        from ApplicationServices import AXIsProcessTrustedWithOptions
        AXIsProcessTrustedWithOptions({"AXTrustedCheckOptionPrompt": True})
    except Exception as e:
        print(f"[Perm/AX] {e}", file=sys.stderr)


# ─── Open at Login (SMAppService) ─────────────────────────────────────────────
def login_item_enabled():
    try:
        import ServiceManagement as SM
        return SM.SMAppService.mainAppService().status() == 1  # 1 = enabled
    except Exception:
        return False


def set_login_item(enabled):
    try:
        import ServiceManagement as SM
        svc = SM.SMAppService.mainAppService()
        if enabled:
            svc.registerAndReturnError_(None)
        else:
            svc.unregisterAndReturnError_(None)
    except Exception as e:
        print(f"[LoginItem] {e}", file=sys.stderr)


# ─── Download progress bridge ────────────────────────────────────────────────
from huggingface_hub.utils import tqdm as _hf_tqdm  # the tqdm hf actually uses


class _ProgressTqdm(_hf_tqdm):
    """Mirror the big-file download progress into the shared _dl dict."""

    def update(self, n=1):
        r = super().update(n)
        try:
            if self.total and self.total > 100_000_000:  # the ~2.5 GB weights file
                _dl["downloaded"] = self.n
                _dl["total"] = self.total
        except Exception:
            pass
        return r


class Dictation:
    """Holds the warm model and drives recording -> transcription -> paste."""

    def __init__(self, settings):
        self.settings = settings
        self.status = "loading"
        self.recording = False
        self.frames = []
        self.stream = None
        self.kb = Controller()
        self.model = None
        self.jobs = queue.Queue()
        self.last_transcripts = []     # in-memory only, newest last
        self.load_error = None
        self.offline = False           # True once running fully offline (cached)
        self._press_active = False     # toggle-mode auto-repeat guard
        self._rec_started = 0.0
        self.notifications = queue.Queue()  # posted on the main thread by the menu Timer

        threading.Thread(target=self._worker_loop, daemon=True).start()

    @property
    def hotkey(self):
        return HOTKEYS.get(self.settings.get("hotkey"), HOTKEYS["alt_r"])[1]

    def notify(self, title, message):
        self.notifications.put((title, message))

    # ─── Worker thread: download (with progress) + load + serve jobs ──────────
    def _worker_loop(self):
        if _model_is_cached():
            os.environ["HF_HUB_OFFLINE"] = "1"   # privacy: no network on a normal launch
            self.offline = True
            print(f"Loading model {MODEL_ID} ...")
        else:
            self.status = "downloading"
            self.notify("Setting up Parakeet",
                        "Downloading the speech model once (~2.5 GB). I'll chime when ready.")
            try:
                from huggingface_hub import snapshot_download
                _dl["active"] = True
                _dl["started"] = time.time()
                snapshot_download(MODEL_ID, tqdm_class=_ProgressTqdm)
                _dl["active"] = False
                os.environ["HF_HUB_OFFLINE"] = "1"
                self.offline = True
            except Exception as e:
                _dl["active"] = False
                self.status = "error"
                self.load_error = e
                print(f"[Error] Model download failed: {e}", file=sys.stderr)
                return

        t0 = time.perf_counter()
        try:
            self.model = from_pretrained(MODEL_ID)
        except Exception as e:
            self.status = "error"
            self.load_error = e
            print(f"[Error] Could not load model: {e}", file=sys.stderr)
            return
        self.status = "idle"
        print(f"Model loaded in {time.perf_counter() - t0:.1f}s — ready.")
        if not os.path.exists(FIRST_READY_FLAG):
            self.notify("Parakeet is ready",
                        f"Click into a text box, then hold the {self._hotkey_label()} key and speak.")
            try:
                os.makedirs(APP_DIR, exist_ok=True)
                open(FIRST_READY_FLAG, "w").close()
            except Exception:
                pass

        while True:
            stream, frames = self.jobs.get()
            try:
                self._process(stream, frames)
            except Exception as e:
                print(f"[Error] {e}", file=sys.stderr)
            finally:
                self.status = "idle"

    def retry_load(self):
        if self.model is None:
            self.status = "loading"
            self.load_error = None
            threading.Thread(target=self._worker_loop, daemon=True).start()

    def _hotkey_label(self):
        return HOTKEYS.get(self.settings.get("hotkey"), HOTKEYS["alt_r"])[0]

    # ─── Recording ────────────────────────────────────────────────────────────
    def start_recording(self):
        if self.recording or self.model is None:
            return
        self.recording = True
        self.frames = []
        self._rec_started = time.time()
        buf = self.frames

        def callback(indata, n_frames, time_info, status_flags):
            if status_flags:
                print(f"[Audio] {status_flags}", file=sys.stderr)
            buf.append(indata.copy())

        try:
            self.stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS,
                                         dtype="float32", callback=callback)
            self.stream.start()
        except Exception as e:
            self.recording = False
            print(f"[Error] Could not start recording: {e}", file=sys.stderr)
            self.notify("Microphone blocked",
                        "Parakeet couldn't access the microphone. Open Microphone settings to fix it.")
            return
        self.status = "recording"
        if self.settings.get("play_sounds", True):
            play(START_SOUND)

    def stop_recording(self):
        if not self.recording:
            return
        self.recording = False
        self.status = "transcribing"
        self.jobs.put((self.stream, self.frames))

    def _process(self, stream, frames):
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass

        if not frames:
            return
        audio = np.concatenate(frames, axis=0)
        duration = audio.shape[0] / SAMPLE_RATE
        if duration < MIN_DURATION_S:
            return

        rms = float(np.sqrt(np.mean(np.square(audio)))) if audio.size else 0.0
        text = self._transcribe(audio, duration)
        if self.settings.get("auto_format"):
            text = tidy_text(text)

        if not text:
            if rms < SILENCE_RMS:
                self._fail("No sound from the microphone — is the right input device selected?")
            else:
                self._fail("Nothing recognized — hold the key a moment longer and speak clearly.")
            return

        self.last_transcripts.append(text)
        del self.last_transcripts[:-10]
        self.paste(text)

    def _transcribe(self, audio, duration):
        """Audio buffer straight to mel -> model (no ffmpeg, no temp WAV)."""
        try:
            samples = mx.array(audio.reshape(-1).astype(np.float32))
            mel = get_logmel(samples, self.model.preprocessor_config)
            t0 = time.perf_counter()
            result = self.model.generate(mel)[0]
            dt = time.perf_counter() - t0
            text = (result.text or "").strip()
            # Privacy: log metadata only, never the transcript text.
            print(f"📝 transcribed {duration:.1f}s audio in {dt:.2f}s ({len(text)} chars)")
            return text
        except Exception as e:
            print(f"[Error] Transcription failed: {e}", file=sys.stderr)
            self._fail("Transcription failed — see the log for details.")
            return ""

    def _fail(self, message):
        if self.settings.get("play_sounds", True):
            play(FAIL_SOUND)
        self.notify("Parakeet", message)

    # ─── Inserting at the cursor (guarded clipboard restore) ──────────────────
    def paste(self, text):
        if not isinstance(text, str) or not text.strip():
            return
        try:
            previous = pyperclip.paste()
        except Exception:
            previous = ""
        if not isinstance(previous, str):
            previous = ""
        pasted_ok = False
        try:
            pyperclip.copy(text)
            with self.kb.pressed(Key.cmd):
                time.sleep(0.02)
                self.kb.press("v")
                self.kb.release("v")
            time.sleep(PASTE_SETTLE_S)
            pasted_ok = True
        except Exception as e:
            print(f"[Error] Paste failed: {e}", file=sys.stderr)
            self.notify("Couldn't insert text",
                        "Accessibility may be off. The text is on your clipboard — press Cmd+V. "
                        "Or use 'Copy last transcript' in the menu.")
        # Only restore the previous clipboard if it is still exactly the text we wrote
        # (so we never clobber a clipboard manager's change, and never erase the
        # transcript if the paste did not land).
        try:
            current = pyperclip.paste()
        except Exception:
            current = text
        if pasted_ok and isinstance(current, str) and current == text:
            try:
                pyperclip.copy(previous)
            except Exception:
                pass
        else:
            # Leave the transcript on the clipboard as the safety net.
            pass

        if pasted_ok:
            if self.settings.get("play_sounds", True):
                play(DONE_SOUND)
            if self.settings.get("show_inserted_banner"):
                preview = text if len(text) <= 80 else text[:77] + "…"
                self.notify("Inserted", preview)

    def copy_last(self):
        if self.last_transcripts:
            try:
                pyperclip.copy(self.last_transcripts[-1])
                self.notify("Copied", "Last transcript is on your clipboard — press Cmd+V.")
            except Exception:
                pass


def make_listener(dictation):
    def on_press(key):
        if key != dictation.hotkey:
            return
        if dictation.settings.get("mode") == "toggle":
            if not dictation._press_active:           # ignore key auto-repeat
                dictation._press_active = True
                if dictation.recording:
                    dictation.stop_recording()
                else:
                    dictation.start_recording()
        else:
            dictation.start_recording()

    def on_release(key):
        if key != dictation.hotkey:
            return
        if dictation.settings.get("mode") == "toggle":
            dictation._press_active = False
        else:
            dictation.stop_recording()

    return keyboard.Listener(on_press=on_press, on_release=on_release)


def restart_app():
    """Relaunch the bundled .app (used after permission grants)."""
    if not getattr(sys, "frozen", False):
        return
    p = sys.executable
    while p and not p.endswith(".app") and p != "/":
        p = os.path.dirname(p)
    if p.endswith(".app"):
        subprocess.Popen(["open", "-n", p])
        time.sleep(0.4)
    os._exit(0)


def run_headless(listener):
    listener.start()
    print("(headless mode — Ctrl+C to quit)")
    try:
        listener.join()
    except KeyboardInterrupt:
        print("\nStopped.")
        listener.stop()


def run_menubar(rumps, dictation, listener):
    HK_ITEMS = {}   # hotkey name -> MenuItem
    MODE_ITEMS = {}

    class MenuApp(rumps.App):
        def __init__(self):
            super().__init__(ICONS["loading"], quit_button="Quit")
            s = dictation.settings

            self.hdr = rumps.MenuItem("Hold a key to dictate")
            self.statusline = rumps.MenuItem("Starting…")
            self.mic = rumps.MenuItem("Microphone", callback=lambda _: open_url(SETTINGS_PANES["Microphone"]))
            self.inp = rumps.MenuItem("Input Monitoring", callback=lambda _: open_url(SETTINGS_PANES["Input Monitoring"]))
            self.acc = rumps.MenuItem("Accessibility", callback=lambda _: open_url(SETTINGS_PANES["Accessibility"]))
            self.restart = rumps.MenuItem("Restart Parakeet Dictate", callback=lambda _: restart_app())
            self.copylast = rumps.MenuItem("Copy last transcript", callback=lambda _: dictation.copy_last())
            self.netline = rumps.MenuItem("Network: checking…")

            # Trigger key submenu
            trigger = rumps.MenuItem("Trigger key")
            for name, (label, _k) in HOTKEYS.items():
                mi = rumps.MenuItem(label, callback=self._make_set_hotkey(name))
                HK_ITEMS[name] = mi
                trigger.add(mi)
            # Mode submenu
            mode = rumps.MenuItem("Mode")
            for key, label in (("hold", "Hold to talk"), ("toggle", "Tap to start / stop")):
                mi = rumps.MenuItem(label, callback=self._make_set_mode(key))
                MODE_ITEMS[key] = mi
                mode.add(mi)

            self.snd = rumps.MenuItem("Play sounds", callback=self._toggle("play_sounds"))
            self.banner = rumps.MenuItem("Show 'inserted' banner", callback=self._toggle("show_inserted_banner"))
            self.fmt = rumps.MenuItem("Tidy up text", callback=self._toggle("auto_format"))
            self.login = rumps.MenuItem("Open at Login", callback=self._toggle_login)

            settings_menu = rumps.MenuItem("Settings")
            for it in (trigger, mode, self.snd, self.banner, self.fmt, self.login):
                settings_menu.add(it)

            self.menu = [
                self.hdr, self.statusline, None,
                self.mic, self.inp, self.acc, self.restart, None,
                self.copylast, settings_menu, None,
                self.netline,
                rumps.MenuItem("How to use", callback=self._how_to),
            ]

            self._granted_prev = None
            self._needs_restart = False

            self._icon_timer = rumps.Timer(self._refresh_icon, 0.25)
            self._icon_timer.start()
            self._menu_timer = rumps.Timer(self._refresh_menu, 1.0)
            self._menu_timer.start()
            self._onboard_timer = rumps.Timer(self._maybe_onboard, 1.0)
            self._onboard_timer.start()
            self._notif_timer = rumps.Timer(self._drain_notifs, 0.5)
            self._notif_timer.start()

        # ── callbacks factories ──
        def _make_set_hotkey(self, name):
            def cb(_):
                dictation.settings["hotkey"] = name
                save_settings(dictation.settings)
            return cb

        def _make_set_mode(self, m):
            def cb(_):
                dictation.settings["mode"] = m
                save_settings(dictation.settings)
            return cb

        def _toggle(self, key):
            def cb(_):
                dictation.settings[key] = not dictation.settings.get(key)
                save_settings(dictation.settings)
            return cb

        def _toggle_login(self, _):
            set_login_item(not login_item_enabled())

        def _how_to(self, _):
            rumps.alert(
                title="How to use Parakeet Dictate",
                message=(f"1. Click into any text field.\n"
                         f"2. Hold the {dictation._hotkey_label()} key and speak.\n"
                         f"3. Let go — your words appear at the cursor.\n\n"
                         f"German and English are detected automatically. Everything stays on "
                         f"your Mac. Change the trigger key or switch to tap-to-toggle under Settings."),
                ok="Got it",
            )

        # ── timers ──
        def _refresh_icon(self, _):
            if self._needs_restart:
                self.title = ICONS["restart"]
                return
            st = dictation.status
            if st == "downloading" and _dl["total"]:
                self.title = f"⤓ {int(100 * _dl['downloaded'] / _dl['total'])}%"
            else:
                self.title = ICONS.get(st, ICONS["idle"])

        def _drain_notifs(self, _):
            while True:
                try:
                    title, msg = dictation.notifications.get_nowait()
                except queue.Empty:
                    break
                try:
                    rumps.notification(title, "", msg)
                except Exception:
                    pass

        def _download_line(self):
            d, t = _dl["downloaded"], _dl["total"]
            if not t:
                return "Preparing download…"
            line = f"Downloading model… {d / 1e6:.0f}/{t / 1e6:.0f} MB"
            el = time.time() - _dl["started"]
            if d > 0 and el > 1:
                rem = (t - d) / (d / el)
                line += f" · ~{rem / 60:.0f} min left" if rem > 90 else f" · ~{int(rem)}s left"
            return line

        def _refresh_menu(self, _):
            m, i, a = mic_ok(), input_monitoring_ok(), accessibility_ok()
            # Detect a permission flipping to granted this session -> needs restart.
            if self._granted_prev is not None:
                pm, pi, pa = self._granted_prev
                if (i and not pi) or (a and not pa):
                    self._needs_restart = True
            self._granted_prev = (m, i, a)

            self.hdr.title = f"🎙  Hold {dictation._hotkey_label()} to dictate"
            self._set_perm(self.mic, "Microphone", m)
            self._set_perm(self.inp, "Input Monitoring", i)
            self._set_perm(self.acc, "Accessibility", a)

            self.restart.title = ("↻  Restart now to finish setup" if self._needs_restart
                                  else "Restart Parakeet Dictate")

            # status line
            st = dictation.status
            if st == "downloading":
                self.statusline.title = self._download_line()
            elif st == "error":
                self.statusline.title = "⚠  Couldn't load the model — see below"
            elif st == "loading":
                self.statusline.title = "Loading the speech model…"
            elif self._needs_restart:
                self.statusline.title = "Almost done — click 'Restart now' below"
            elif not (m and i and a):
                self.statusline.title = "⚠  Grant the permissions below to start"
            elif st == "recording":
                self.statusline.title = f"● Recording… ({int(time.time() - dictation._rec_started)}s)"
            elif st == "transcribing":
                self.statusline.title = "✍️  Transcribing…"
            else:
                self.statusline.title = "Ready — hold the key and speak"

            self.copylast.title = ("Copy last transcript" if dictation.last_transcripts
                                   else "Copy last transcript (none yet)")
            self.netline.title = ("🔒  Network: offline · nothing sent" if dictation.offline
                                  else "Network: online (one-time setup)")

            # toggles -> checkmarks
            self.snd.state = 1 if dictation.settings.get("play_sounds") else 0
            self.banner.state = 1 if dictation.settings.get("show_inserted_banner") else 0
            self.fmt.state = 1 if dictation.settings.get("auto_format") else 0
            self.login.state = 1 if login_item_enabled() else 0
            for name, it in HK_ITEMS.items():
                it.state = 1 if dictation.settings.get("hotkey") == name else 0
            for key, it in MODE_ITEMS.items():
                it.state = 1 if dictation.settings.get("mode") == key else 0

            # safety cap: auto-stop a runaway recording
            if dictation.recording and (time.time() - dictation._rec_started) > MAX_RECORDING_S:
                dictation.stop_recording()

        def _set_perm(self, item, label, ok):
            item.title = f"✓  {label}" if ok else f"⚠  {label} — click to grant"

        def _maybe_onboard(self, sender):
            sender.stop()
            try:
                if mic_ok() and input_monitoring_ok() and accessibility_ok():
                    return
                if not os.path.exists(ONBOARDED_FLAG):
                    rumps.alert(
                        title="Welcome — three quick permissions",
                        message=("Push-to-talk: hold a key, speak, release — the text appears at "
                                 "your cursor.\n\nI'll request three permissions now; please confirm "
                                 "the system dialogs:\n  •  Microphone → Allow\n  •  Input Monitoring "
                                 "→ enable the toggle\n  •  Accessibility → enable the toggle\n\n"
                                 "The menu shows ✓ / ⚠ for each, and offers a one-click restart when "
                                 "you're done."),
                        ok="Request",
                    )
                    try:
                        os.makedirs(APP_DIR, exist_ok=True)
                        open(ONBOARDED_FLAG, "w").close()
                    except Exception:
                        pass
                request_permissions()
            except Exception as e:
                print(f"[Onboarding] {e}", file=sys.stderr)

    listener.start()
    MenuApp().run()
    listener.stop()


def _setup_frozen_logging():
    if not getattr(sys, "frozen", False):
        return
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        f = open(LOG_PATH, "a", buffering=1)
        sys.stdout = f
        sys.stderr = f
    except Exception:
        pass


def main():
    _setup_frozen_logging()
    settings = load_settings()
    dictation = Dictation(settings)
    listener = make_listener(dictation)
    try:
        import rumps
    except Exception as e:
        print(f"rumps unavailable ({e}) — running headless.", file=sys.stderr)
        run_headless(listener)
        return
    run_menubar(rumps, dictation, listener)


if __name__ == "__main__":
    main()
