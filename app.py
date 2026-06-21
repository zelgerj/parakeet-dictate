"""
app.py — Parakeet Dictation Tool (macOS)

Push-to-talk Diktat: Hotkey gedrückt halten, sprechen, loslassen.
Das Gesprochene wird lokal mit NVIDIA Parakeet TDT v3 (MLX) transkribiert
und per Clipboard-Paste (Cmd+V) an der aktuellen Cursor-Position eingefügt.

100% lokal nach dem einmaligen Modell-Download. Bewusst minimal.

Benötigte macOS-Berechtigungen (Systemeinstellungen > Datenschutz & Sicherheit):
  - Mikrofon            (Aufnahme)
  - Bedienungshilfen    (simuliertes Cmd+V)
  - Eingabeüberwachung  (globaler Hotkey-Listener)
Nach Vergabe der Rechte die App (bzw. das Terminal) einmal neu starten.

Start (aus dem Source):   python app.py
Beenden: "Beenden" im Menüleisten-Icon (oder Strg+C im headless-Modus)
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

# ─── Konfiguration (hier anpassen) ───────────────────────────────────────────
MODEL_ID = "mlx-community/parakeet-tdt-0.6b-v3"
SAMPLE_RATE = 16000        # Parakeet erwartet 16 kHz mono
CHANNELS = 1
HOTKEY = Key.alt_r         # rechte Option/alt-Taste gedrückt halten (Push-to-talk)
USE_MENUBAR = True         # rumps-Menüleisten-Icon; bei Friktion auf False (headless)
MIN_DURATION_S = 0.3       # kürzere Aufnahmen ignorieren (versehentlicher Tipp)
PASTE_SETTLE_S = 0.4       # warten, bis das Paste verarbeitet wurde, vor Clipboard-Restore
                           # (zu kurz -> Ziel-App fügt versehentlich den alten Clipboard ein)

START_SOUND = "/System/Library/Sounds/Pop.aiff"
DONE_SOUND = "/System/Library/Sounds/Glass.aiff"

ICONS = {
    "loading": "⏳",       # Modell wird geladen
    "downloading": "⤓",   # Modell wird (einmalig) heruntergeladen
    "idle": "🎙️",          # bereit
    "recording": "🔴",     # Aufnahme läuft
    "transcribing": "✍️",  # Transkription läuft
    "error": "⚠️",         # Fehler (z. B. Modell-Load fehlgeschlagen)
}
# ──────────────────────────────────────────────────────────────────────────────


def play(sound_path):
    """Systemsound nicht-blockierend abspielen (fire-and-forget)."""
    try:
        subprocess.Popen(
            ["afplay", sound_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def _model_is_cached():
    """True, wenn das Modell schon im HuggingFace-Cache liegt (kein Download nötig)."""
    try:
        from huggingface_hub import try_to_load_from_cache
        return bool(try_to_load_from_cache(MODEL_ID, "config.json"))
    except Exception:
        return True  # im Zweifel keinen Download-Hinweis zeigen


class Dictation:
    """Hält das warme Modell und steuert Aufnahme -> Transkription -> Paste."""

    def __init__(self):
        self.status = "loading"   # loading|downloading|idle|recording|transcribing|error
        self.recording = False
        self.frames = []
        self.stream = None
        self.kb = Controller()
        self.model = None
        self.jobs = queue.Queue()

        # Modell NICHT blockierend laden, damit das Menüleisten-Icon SOFORT erscheint
        # (Status "loading"/"downloading") und die App nicht "hängt".
        # WICHTIG: Alle MLX-Operationen (Modell laden UND transkribieren) laufen im
        # SELBEN Worker-Thread — MLX-GPU-Streams sind thread-gebunden, sonst kommt
        # "There is no Stream(gpu, 0) in current thread.".
        threading.Thread(target=self._worker_loop, daemon=True).start()

    def _worker_loop(self):
        """Lädt das Modell und arbeitet danach Transkriptions-Jobs ab — alles in
        diesem EINEN Thread (siehe Hinweis in __init__)."""
        if _model_is_cached():
            print(f"Lade Modell {MODEL_ID} ...")
        else:
            self.status = "downloading"
            print("Lade Sprachmodell herunter (~1–2 GB, nur beim ersten Start) ...")
        t0 = time.perf_counter()
        try:
            self.model = from_pretrained(MODEL_ID)
        except Exception as e:
            self.status = "error"
            print(f"[Fehler] Modell konnte nicht geladen werden: {e}", file=sys.stderr)
            print("  -> Beim ersten Start ist eine Internetverbindung nötig.", file=sys.stderr)
            return
        self.status = "idle"
        print(f"Modell geladen in {time.perf_counter() - t0:.1f}s — bereit. "
              f"Halte die rechte Option-Taste ({HOTKEY}) gedrückt und sprich.")

        while True:
            stream, frames = self.jobs.get()
            try:
                self._process(stream, frames)
            except Exception as e:
                print(f"[Fehler] {e}", file=sys.stderr)
            finally:
                self.status = "idle"

    # ─── Aufnahme ──────────────────────────────────────────────────────────────
    def start_recording(self):
        if self.recording:
            return  # pynput feuert on_press wiederholt bei gehaltener Taste -> ignorieren
        if self.model is None:
            return  # Modell lädt noch oder Load fehlgeschlagen -> Hotkey ignorieren
        self.recording = True
        self.frames = []
        buf = self.frames  # Closure bindet GENAU diesen Puffer an diese Aufnahme

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
            print(f"[Fehler] Aufnahme konnte nicht starten: {e}", file=sys.stderr)
            print("  -> Mikrofon-Berechtigung prüfen.", file=sys.stderr)
            return
        self.status = "recording"
        print("● Aufnahme läuft ...")
        play(START_SOUND)

    def stop_recording(self):
        if not self.recording:
            return
        self.recording = False
        self.status = "transcribing"
        # pynput-Callback NICHT blockieren (macOS deaktiviert sonst den Event-Tap):
        # nur den Job einreihen. Der Worker-Thread erledigt Stream-Stopp,
        # Transkription und Paste.
        self.jobs.put((self.stream, self.frames))

    def _process(self, stream, frames):
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass

        if not frames:
            print("(nichts aufgenommen)")
            return
        audio = np.concatenate(frames, axis=0)
        duration = audio.shape[0] / SAMPLE_RATE
        if duration < MIN_DURATION_S:
            print(f"(Aufnahme zu kurz: {duration:.2f}s)")
            return

        text = self._transcribe(audio, duration)
        if not text:
            print("(keine Sprache erkannt)")
            return

        self.paste(text)
        play(DONE_SOUND)

    def _transcribe(self, audio, duration):
        """Audio-Puffer direkt zu Mel -> Modell. Gibt Text zurück.

        Repliziert den Kern von parakeet_mlx.transcribe(), überspringt aber load_audio()
        — das ruft ffmpeg auf (in einer .app nicht im PATH, und Endnutzer haben es nicht).
        Wir haben die Samples schon im exakt passenden Format: float32, 16 kHz mono, [-1, 1].
        """
        try:
            samples = mx.array(audio.reshape(-1).astype(np.float32))
            mel = get_logmel(samples, self.model.preprocessor_config)
            t0 = time.perf_counter()
            result = self.model.generate(mel)[0]
            dt = time.perf_counter() - t0
            text = (result.text or "").strip()
            if text:
                print(f"📝 ({duration:.1f}s Audio, {dt:.2f}s): {text}")
            return text
        except Exception as e:
            print(f"[Fehler] Transkription fehlgeschlagen: {e}", file=sys.stderr)
            return ""

    # ─── Einfügen am Cursor ──────────────────────────────────────────────────────
    def paste(self, text):
        """Über Clipboard + Cmd+V einfügen (Umlaute/ß zuverlässig, kein Zeichen-Tippen).
        Vorherigen Clipboard-Inhalt sichern und nach dem Paste wiederherstellen."""
        if not isinstance(text, str) or not text.strip():
            return  # niemals None oder Leeres einfügen
        try:
            previous = pyperclip.paste()
        except Exception:
            previous = ""
        if not isinstance(previous, str):
            previous = ""  # nie einen Nicht-String (-> "None") zurückschreiben
        try:
            pyperclip.copy(text)
            with self.kb.pressed(Key.cmd):
                time.sleep(0.02)  # kurz, damit Cmd sicher registriert ist
                self.kb.press("v")
                self.kb.release("v")
            time.sleep(PASTE_SETTLE_S)  # Ziel-App den Clipboard-Inhalt lesen lassen
        except Exception as e:
            print(f"[Fehler] Einfügen fehlgeschlagen: {e}", file=sys.stderr)
            print("  -> Bedienungshilfen-Berechtigung prüfen.", file=sys.stderr)
        finally:
            try:
                pyperclip.copy(previous)  # Clipboard wiederherstellen
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
    print("(headless-Modus — Strg+C zum Beenden)")
    try:
        listener.join()
    except KeyboardInterrupt:
        print("\nBeendet.")
        listener.stop()


SETTINGS_PANES = [
    ("Mikrofon",
     "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone"),
    ("Bedienungshilfen",
     "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"),
    ("Eingabeüberwachung",
     "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent"),
]


def _open_url(url):
    try:
        subprocess.Popen(["open", url])
    except Exception:
        pass


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
    """Löst die nativen System-Dialoge aus und registriert die App in den drei
    Datenschutz-Listen. Wichtig: PortAudio allein registriert das Mikrofon NICHT —
    darum fragen wir es hier explizit über AVFoundation an. Die Freigaben sind
    signatur-gebunden und bleiben so über Neustarts/Updates stabil."""
    try:
        import AVFoundation
        mt = AVFoundation.AVMediaTypeAudio
        st = AVFoundation.AVCaptureDevice.authorizationStatusForMediaType_(mt)
        print(f"[Perm/Mic] Status vor Anfrage: {st} (0=unbestimmt 2=verweigert 3=erlaubt)",
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
            super().__init__(ICONS["loading"], quit_button="Beenden")
            self.menu = [
                rumps.MenuItem("Berechtigungen anfragen…", callback=self._ask_perms),
                rumps.MenuItem("Einstellungen öffnen…", callback=self._open_perms),
                rumps.MenuItem("Log anzeigen", callback=self._open_log),
                None,  # Trenner; „Beenden" wird automatisch ergänzt
            ]
            # rumps läuft auf dem Main-Thread; Status per Timer (Main-Thread) spiegeln,
            # statt die UI aus dem Listener-/Worker-Thread anzufassen.
            self._timer = rumps.Timer(self._refresh, 0.2)
            self._timer.start()
            # Onboarding einmalig kurz nach Start (auf dem Main-Thread).
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
            sender.stop()  # nur einmal pro Start
            try:
                if _mic_ok() and _input_monitoring_ok() and _accessibility_ok():
                    return  # alle Rechte vorhanden -> nicht stören
                if not os.path.exists(onboarded_flag):
                    rumps.alert(
                        title="Willkommen — drei kurze Freigaben",
                        message=(
                            "Push-to-talk: rechte Option-Taste halten, sprechen, loslassen — "
                            "der Text erscheint an der Cursor-Position.\n\n"
                            "Ich frage jetzt drei Berechtigungen an. Bitte die System-Dialoge "
                            "bestätigen:\n"
                            "  •  Mikrofon  →  »Erlauben«\n"
                            "  •  Eingabeüberwachung  →  Schalter in den Einstellungen an\n"
                            "  •  Bedienungshilfen  →  Schalter in den Einstellungen an\n\n"
                            "Danach Parakeet Dictate bitte einmal neu starten."
                        ),
                        ok="Anfragen",
                    )
                    try:
                        os.makedirs(state_dir, exist_ok=True)
                        open(onboarded_flag, "w").close()
                    except Exception:
                        pass
                _request_permissions()
            except Exception as e:
                print(f"[Onboarding] {e}", file=sys.stderr)

    listener.start()  # pynput-Listener in eigenem Thread
    MenuApp().run()    # blockiert auf der AppKit-Runloop bis "Beenden"
    listener.stop()


def _setup_frozen_logging():
    """In der gebündelten .app gibt es kein Terminal — Ausgaben in eine Logdatei
    umleiten, damit Probleme diagnostizierbar bleiben (~/Library/Logs/)."""
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
            print(f"rumps nicht verfügbar ({e}) — starte headless.", file=sys.stderr)
            run_headless(listener)
            return
        run_menubar(rumps, dictation, listener)
    else:
        run_headless(listener)


if __name__ == "__main__":
    main()
