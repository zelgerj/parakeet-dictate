"""
app.py — Parakeet Dictation Tool (macOS)

Push-to-talk dictation: hold a hotkey, speak, release.
What you said is transcribed locally with NVIDIA Parakeet TDT v3 (MLX) and
inserted at the current cursor position via clipboard paste (Cmd+V).

100% local after the one-time model download. Deliberately minimal.

Required macOS permissions (System Settings > Privacy & Security):
  - Microphone        (recording)
  - Accessibility     (simulated Cmd+V)
  - Input Monitoring  (global hotkey listener)
After granting them, restart the app (or the terminal hosting it) once.

Start (from source):  python app.py
Quit: "Quit" in the menu-bar icon (or Ctrl+C in headless mode)
"""

import os
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

# ─── Configuration (tweak here) ──────────────────────────────────────────────
MODEL_ID = "mlx-community/parakeet-tdt-0.6b-v3"
SAMPLE_RATE = 16000        # Parakeet expects 16 kHz mono
CHANNELS = 1
HOTKEY = Key.alt_r         # hold the right Option/alt key (push-to-talk)
USE_MENUBAR = True         # rumps menu-bar icon; set to False for headless
MIN_DURATION_S = 0.3       # ignore shorter recordings (accidental tap)
PASTE_SETTLE_S = 0.4       # wait for the paste to land before restoring the clipboard
                           # (too short -> target app pastes the OLD clipboard instead)

START_SOUND = "/System/Library/Sounds/Pop.aiff"
DONE_SOUND = "/System/Library/Sounds/Glass.aiff"

ICONS = {
    "loading": "⏳",       # model is loading
    "downloading": "⤓",   # model is being downloaded (one-time)
    "idle": "🎙️",          # ready
    "recording": "🔴",     # recording
    "transcribing": "✍️",  # transcribing
    "error": "⚠️",         # error (e.g. model load failed)
}
# ──────────────────────────────────────────────────────────────────────────────


def play(sound_path):
    """Play a system sound without blocking (fire-and-forget)."""
    try:
        subprocess.Popen(
            ["afplay", sound_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def _model_is_cached():
    """True if the model is already in the HuggingFace cache (no download needed)."""
    try:
        from huggingface_hub import try_to_load_from_cache
        return bool(try_to_load_from_cache(MODEL_ID, "config.json"))
    except Exception:
        return True  # when unsure, don't show a download hint


class Dictation:
    """Holds the warm model and drives recording -> transcription -> paste."""

    def __init__(self):
        self.status = "loading"   # loading|downloading|idle|recording|transcribing|error
        self.recording = False
        self.frames = []
        self.stream = None
        self.kb = Controller()
        self.model = None
        self.jobs = queue.Queue()

        # Load the model WITHOUT blocking so the menu-bar icon appears immediately
        # (status "loading"/"downloading") and the app does not look frozen.
        # IMPORTANT: all MLX operations (loading the model AND transcribing) run on
        # the SAME worker thread — MLX GPU streams are thread-bound, otherwise you get
        # "There is no Stream(gpu, 0) in current thread.".
        threading.Thread(target=self._worker_loop, daemon=True).start()

    def _worker_loop(self):
        """Loads the model, then processes transcription jobs — all on this ONE
        thread (see the note in __init__)."""
        if _model_is_cached():
            print(f"Loading model {MODEL_ID} ...")
        else:
            self.status = "downloading"
            print("Downloading speech model (~1–2 GB, first run only) ...")
        t0 = time.perf_counter()
        try:
            self.model = from_pretrained(MODEL_ID)
        except Exception as e:
            self.status = "error"
            print(f"[Error] Could not load model: {e}", file=sys.stderr)
            print("  -> An internet connection is required on first run.", file=sys.stderr)
            return
        self.status = "idle"
        print(f"Model loaded in {time.perf_counter() - t0:.1f}s — ready. "
              f"Hold the right Option key ({HOTKEY}) and speak.")

        while True:
            stream, frames = self.jobs.get()
            try:
                self._process(stream, frames)
            except Exception as e:
                print(f"[Error] {e}", file=sys.stderr)
            finally:
                self.status = "idle"

    # ─── Recording ───────────────────────────────────────────────────────────
    def start_recording(self):
        if self.recording:
            return  # pynput fires on_press repeatedly while held -> ignore
        if self.model is None:
            return  # model still loading or load failed -> ignore the hotkey
        self.recording = True
        self.frames = []
        buf = self.frames  # closure binds THIS buffer to THIS recording

        def callback(indata, n_frames, time_info, status_flags):
            if status_flags:
                print(f"[Audio] {status_flags}", file=sys.stderr)
            buf.append(indata.copy())

        try:
            self.stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="float32",
                callback=callback,
            )
            self.stream.start()
        except Exception as e:
            self.recording = False
            print(f"[Error] Could not start recording: {e}", file=sys.stderr)
            print("  -> Check the Microphone permission.", file=sys.stderr)
            return
        self.status = "recording"
        print("● Recording ...")
        play(START_SOUND)

    def stop_recording(self):
        if not self.recording:
            return
        self.recording = False
        self.status = "transcribing"
        # Do NOT block the pynput callback (macOS disables the event tap otherwise):
        # just enqueue the job. The worker thread stops the stream, transcribes and
        # pastes.
        self.jobs.put((self.stream, self.frames))

    def _process(self, stream, frames):
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass

        if not frames:
            print("(nothing recorded)")
            return
        audio = np.concatenate(frames, axis=0)
        duration = audio.shape[0] / SAMPLE_RATE
        if duration < MIN_DURATION_S:
            print(f"(recording too short: {duration:.2f}s)")
            return

        text = self._transcribe(audio, duration)
        if not text:
            print("(no speech detected)")
            return

        self.paste(text)
        play(DONE_SOUND)

    def _transcribe(self, audio, duration):
        """Turn the audio buffer straight into a mel spectrogram -> model. Returns text.

        Replicates the core of parakeet_mlx.transcribe() but skips load_audio() — that
        shells out to ffmpeg (not on PATH inside a .app, and end users don't have it).
        We already have the samples in the exact format it would produce: float32,
        16 kHz mono, [-1, 1].
        """
        try:
            samples = mx.array(audio.reshape(-1).astype(np.float32))
            mel = get_logmel(samples, self.model.preprocessor_config)
            t0 = time.perf_counter()
            result = self.model.generate(mel)[0]
            dt = time.perf_counter() - t0
            text = (result.text or "").strip()
            if text:
                print(f"📝 ({duration:.1f}s audio, {dt:.2f}s): {text}")
            return text
        except Exception as e:
            print(f"[Error] Transcription failed: {e}", file=sys.stderr)
            return ""

    # ─── Inserting at the cursor ─────────────────────────────────────────────
    def paste(self, text):
        """Insert via clipboard + Cmd+V (reliable for any characters, no per-key typing).
        Save the previous clipboard content and restore it after the paste."""
        if not isinstance(text, str) or not text.strip():
            return  # never insert None or empty
        try:
            previous = pyperclip.paste()
        except Exception:
            previous = ""
        if not isinstance(previous, str):
            previous = ""  # never write back a non-string (-> "None")
        try:
            pyperclip.copy(text)
            with self.kb.pressed(Key.cmd):
                time.sleep(0.02)  # brief, so Cmd is registered for sure
                self.kb.press("v")
                self.kb.release("v")
            time.sleep(PASTE_SETTLE_S)  # let the target app read the clipboard
        except Exception as e:
            print(f"[Error] Paste failed: {e}", file=sys.stderr)
            print("  -> Check the Accessibility permission.", file=sys.stderr)
        finally:
            try:
                pyperclip.copy(previous)  # restore the clipboard
            except Exception:
                pass


def make_listener(dictation):
    def on_press(key):
        if key == HOTKEY:
            dictation.start_recording()

    def on_release(key):
        if key == HOTKEY:
            dictation.stop_recording()

    return keyboard.Listener(on_press=on_press, on_release=on_release)


def run_headless(listener):
    listener.start()
    print("(headless mode — Ctrl+C to quit)")
    try:
        listener.join()
    except KeyboardInterrupt:
        print("\nStopped.")
        listener.stop()


SETTINGS_PANES = [
    ("Microphone",
     "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone"),
    ("Accessibility",
     "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"),
    ("Input Monitoring",
     "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent"),
]


def _open_url(url):
    try:
        subprocess.Popen(["open", url])
    except Exception:
        pass


# ─── Permissions: request them actively via native macOS APIs ────────────────
# Advantage over "let the user hunt for the toggle": the app reliably registers
# itself in the three privacy lists (PortAudio alone does NOT do this for the
# microphone), and the grants are bound to the code signature -> stable.
def _mic_ok():
    try:
        import AVFoundation
        return AVFoundation.AVCaptureDevice.authorizationStatusForMediaType_(
            AVFoundation.AVMediaTypeAudio) == 3  # 3 = authorized
    except Exception:
        return True


def _input_monitoring_ok():
    try:
        from Quartz import CGPreflightListenEventAccess
        return bool(CGPreflightListenEventAccess())
    except Exception:
        return True


def _accessibility_ok():
    try:
        from ApplicationServices import AXIsProcessTrusted
        return bool(AXIsProcessTrusted())
    except Exception:
        return True


def _request_permissions():
    """Trigger the native system dialogs and register the app in the three privacy
    lists. Note: PortAudio alone does NOT register the microphone — so we request it
    explicitly via AVFoundation. The grants are signature-bound and therefore stay
    stable across restarts/updates."""
    try:
        import AVFoundation
        mt = AVFoundation.AVMediaTypeAudio
        st = AVFoundation.AVCaptureDevice.authorizationStatusForMediaType_(mt)
        print(f"[Perm/Mic] status before request: {st} (0=undetermined 2=denied 3=authorized)",
              file=sys.stderr)
        AVFoundation.AVCaptureDevice.requestAccessForMediaType_completionHandler_(
            mt, lambda granted: print(f"[Perm/Mic] granted={granted}", file=sys.stderr))
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


def run_menubar(rumps, dictation, listener):
    state_dir = os.path.expanduser("~/Library/Application Support/ParakeetDictate")
    onboarded_flag = os.path.join(state_dir, ".onboarded")
    log_path = os.path.expanduser("~/Library/Logs/ParakeetDictate.log")

    class MenuApp(rumps.App):
        def __init__(self):
            super().__init__(ICONS["loading"], quit_button="Quit")
            self.menu = [
                rumps.MenuItem("Request permissions…", callback=self._ask_perms),
                rumps.MenuItem("Open Settings…", callback=self._open_perms),
                rumps.MenuItem("Show log", callback=self._open_log),
                None,  # separator; "Quit" is appended automatically
            ]
            # rumps runs on the main thread; mirror status via a timer (main thread)
            # instead of touching the UI from the listener/worker thread.
            self._timer = rumps.Timer(self._refresh, 0.2)
            self._timer.start()
            # One-time onboarding shortly after start (on the main thread).
            self._onboard_timer = rumps.Timer(self._maybe_onboard, 1.0)
            self._onboard_timer.start()

        def _refresh(self, _):
            self.title = ICONS.get(dictation.status, ICONS["idle"])

        def _ask_perms(self, _):
            _request_permissions()

        def _open_perms(self, _):
            for _name, url in SETTINGS_PANES:
                _open_url(url)

        def _open_log(self, _):
            _open_url(log_path)

        def _maybe_onboard(self, sender):
            sender.stop()  # only once per launch
            try:
                if _mic_ok() and _input_monitoring_ok() and _accessibility_ok():
                    return  # all permissions present -> don't bother the user
                if not os.path.exists(onboarded_flag):
                    rumps.alert(
                        title="Welcome — three quick permissions",
                        message=(
                            "Push-to-talk: hold the right Option key, speak, release — "
                            "the text appears at the cursor position.\n\n"
                            "I'll now request three permissions. Please confirm the system "
                            "dialogs:\n"
                            "  •  Microphone  →  Allow\n"
                            "  •  Input Monitoring  →  enable the toggle in Settings\n"
                            "  •  Accessibility  →  enable the toggle in Settings\n\n"
                            "Then please restart Parakeet Dictate once."
                        ),
                        ok="Request",
                    )
                    try:
                        os.makedirs(state_dir, exist_ok=True)
                        open(onboarded_flag, "w").close()
                    except Exception:
                        pass
                _request_permissions()
            except Exception as e:
                print(f"[Onboarding] {e}", file=sys.stderr)

    listener.start()  # pynput listener on its own thread
    MenuApp().run()    # blocks on the AppKit run loop until "Quit"
    listener.stop()


def _setup_frozen_logging():
    """Inside the bundled .app there is no terminal — redirect output to a log file
    so problems stay diagnosable (~/Library/Logs/)."""
    if not getattr(sys, "frozen", False):
        return
    try:
        log_dir = os.path.expanduser("~/Library/Logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file = open(os.path.join(log_dir, "ParakeetDictate.log"), "a", buffering=1)
        sys.stdout = log_file
        sys.stderr = log_file
    except Exception:
        pass


def main():
    _setup_frozen_logging()
    dictation = Dictation()
    listener = make_listener(dictation)

    if USE_MENUBAR:
        try:
            import rumps
        except Exception as e:
            print(f"rumps unavailable ({e}) — running headless.", file=sys.stderr)
            run_headless(listener)
            return
        run_menubar(rumps, dictation, listener)
    else:
        run_headless(listener)


if __name__ == "__main__":
    main()
