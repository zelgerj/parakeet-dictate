# PRD / Prompt für Claude Code: Parakeet Dictation Tool (macOS, v1)

> Diesen kompletten Text als Start-Prompt in eine neue Claude Code Session geben.

## Rolle

Du bist ein Senior macOS/Python-Entwickler. Du baust ein **bewusst minimales** lokales Diktier-Tool für macOS auf Apple Silicon. Oberste Regel: **ruthless simplicity**. Lieber 150 Zeilen, die zuverlässig laufen, als ein Feature-Gerüst. Frag nicht nach Scope-Erweiterungen, halt dich exakt an die Must-haves unten.

## Kontext (wichtig, nicht "wegoptimieren")

- Zielrechner: Apple Silicon Mac (primär M4 Mac Mini, mind. M-Serie, macOS 14+).
- Nutzer diktiert überwiegend **Deutsch**, teils Englisch, gemischt. Eigennamen und Fachbegriffe sind häufig.
- Es geht bewusst um **NVIDIA Parakeet**, nicht Whisper, wegen Geschwindigkeit und nativer Mehrsprachigkeit.
- Heutiges Datum ist Juni 2026. Das aktuell zu verwendende Modell ist **`mlx-community/parakeet-tdt-0.6b-v3`** (multilingual, 25 EU-Sprachen, automatische Spracherkennung). Verwende exakt dieses Modell, "korrigiere" es nicht auf eine ältere v2- oder Whisper-Variante.
- Alles läuft **100% lokal**. Nach dem einmaligen Modell-Download (HuggingFace) darf zur Laufzeit kein Audio das Gerät verlassen.

## Ziel

Ein Hintergrund-Tool: Hotkey gedrückt halten, sprechen, loslassen. Das Gesprochene wird mit Parakeet v3 lokal transkribiert und der fertige Text **an der aktuellen Cursor-Position** in der gerade aktiven App eingefügt. Mehr nicht.

## Tech-Stack (verbindlich)

- **Sprache:** Python 3.11+
- **ASR:** `parakeet-mlx` (PyPI), Modell `mlx-community/parakeet-tdt-0.6b-v3`
- **Audioaufnahme:** `sounddevice` (Mikrofon, 16 kHz mono, float32)
- **WAV-Handling:** `soundfile` (temporäres WAV schreiben, danach löschen)
- **Globaler Hotkey + Tastatursimulation:** `pynput`
- **Clipboard:** `pyperclip`
- **Menüleisten-Icon (optional in v1):** `rumps`
- **System-Dependency:** `ffmpeg` (via Homebrew), wird von parakeet-mlx erwartet

Kern-API von parakeet-mlx, so verwenden:

```python
from parakeet_mlx import from_pretrained
model = from_pretrained("mlx-community/parakeet-tdt-0.6b-v3")
result = model.transcribe("aufnahme.wav")
print(result.text)
```

Das Modell **einmal beim Start** laden und warm halten, nicht pro Aufnahme neu laden.

## Scope v1 — Must-haves (genau das, nicht mehr)

1. **Push-to-talk Hotkey:** Eine konfigurierbare Taste als Konstante oben im Code (Default: rechte `Option`/`alt`-Taste gedrückt halten). Gedrückt = Aufnahme läuft, losgelassen = Aufnahme stoppt und Transkription startet.
2. **Aufnahme:** Mikrofon mit `sounddevice` in 16 kHz mono float32, solange der Hotkey gehalten wird, in einen Puffer.
3. **Transkription:** Puffer als temporäres WAV speichern, mit Parakeet v3 transkribieren (automatische Spracherkennung, DE und EN ohne Umschalten), `result.text` holen, temporäres WAV löschen.
4. **Einfügen am Cursor:** Den Text in die Zwischenablage legen und per simuliertem `Cmd+V` in die aktive App einfügen. **Bewusst über Clipboard-Paste**, damit Umlaute und ß zuverlässig funktionieren (kein Zeichen-für-Zeichen-Tippen). Vorherigen Clipboard-Inhalt vorher sichern und nach dem Paste wiederherstellen.
5. **Status-Feedback:** Mindestens ein klar erkennbares Signal für "Aufnahme läuft" vs. "fertig". Akzeptabel als simpelste Variante: kurzer System-Sound beim Start/Stopp und Konsolen-Log. Wenn ohne großen Aufwand machbar: `rumps`-Menüleisten-Icon, das zwischen Idle/Recording/Transcribing wechselt.

## Explizit NICHT in v1 (Non-Goals)

Diese Punkte bitte weglassen, auch wenn sie naheliegen:

- Keine Settings-GUI (Konfiguration nur über Konstanten im Code)
- Keine Transkript-Historie, kein Speichern von Aufnahmen oder Text
- Kein LLM-Cleanup / keine Nachformatierung
- Keine Speaker-Diarization
- Kein Datei- oder Video-Import
- Kein Windows/Linux, kein Intel-Mac
- Kein Code-Signing, keine Notarisierung, kein Bundling/Installer (läuft aus dem Source)
- Keine Echtzeit-Anzeige des Texts während des Sprechens (record-then-transcribe genügt)
- Keine Auswahl verschiedener Modelle (nur parakeet v3)

## Akzeptanzkriterien (so prüfen wir v1)

- `python app.py` startet, lädt das Modell einmal und zeigt einen "ready"-Zustand (Log oder Icon).
- Hotkey halten, einen deutschen Satz sprechen, loslassen: der korrekte **deutsche** Text inkl. Umlauten erscheint an der Cursor-Position in TextEdit, im Browser und in Slack.
- Danach einen englischen Satz ohne jede Umstellung: wird korrekt als Englisch erkannt und eingefügt.
- Nach dem Paste ist der vorherige Clipboard-Inhalt wiederhergestellt.
- Eine ca. 5-sekündige Äußerung wird nach warmem Modell in grob 1–2 Sekunden eingefügt (Parakeet ist sehr schnell auf Apple Silicon).
- Im Airplane-Mode / offline funktioniert alles (nach erfolgtem Erst-Download des Modells).

## Vorgehen (in dieser Reihenfolge, Kern zuerst absichern)

1. **Umgebung:** `uv` oder `python -m venv` Environment anlegen, Dependencies installieren, `ffmpeg` via Homebrew sicherstellen. Eine `requirements.txt` (oder `pyproject.toml`) anlegen.
2. **Kern de-risken zuerst:** Ein eigenständiges Skript `test_transcribe.py` schreiben, das eine kurze Beispiel-WAV mit `mlx-community/parakeet-tdt-0.6b-v3` transkribiert und den Text ausgibt. Erst wenn das auf der Maschine sauber läuft, weiterbauen. So trennen wir Modell-Probleme von Hotkey/Paste-Problemen.
3. Dann Mikrofon-Aufnahme mit `sounddevice` implementieren und gegen `test_transcribe` validieren.
4. Dann den globalen Hotkey-Listener (`pynput`) für Press/Release einbauen.
5. Dann das Clipboard-Paste (`pyperclip` + `pynput` `Cmd+V`, Clipboard sichern/wiederherstellen).
6. Optional zuletzt das `rumps`-Menüleisten-Icon mit Statuswechsel. Hinweis: `rumps.App` läuft auf dem Main-Thread (AppKit-Runloop), den `pynput`-Listener daher in einem eigenen Thread starten. Wenn das Friktion macht, v1 erstmal headless mit Konsolen-Log und System-Sound ausliefern und das Icon als kleinen Folgeschritt notieren.
7. `README.md` mit Setup, Start und vor allem den nötigen macOS-Berechtigungen schreiben.

## Projektstruktur (flach halten)

```
parakeet-dictate/
  app.py              # gesamte v1-Logik
  test_transcribe.py  # Kern-Check Modell+WAV
  requirements.txt
  README.md
```

Konfiguration als Konstanten oben in `app.py`, z. B. `HOTKEY`, `SAMPLE_RATE = 16000`, `MODEL_ID = "mlx-community/parakeet-tdt-0.6b-v3"`.

## macOS-Berechtigungen (häufigste Fehlerquelle, im README erklären)

Das Tool braucht für das Terminal bzw. den Python-Prozess:

- **Mikrofon** (Aufnahme)
- **Bedienungshilfen / Accessibility** (simuliertes `Cmd+V`)
- **Eingabeüberwachung / Input Monitoring** (globaler Hotkey-Listener)

Im README klar dokumentieren, wo das in den Systemeinstellungen gesetzt wird, und dass das Terminal nach Vergabe der Rechte einmal neu gestartet werden muss.

## Stolpersteine, die du aktiv vermeiden sollst

- Modell pro Aufnahme neu laden: nein, einmal beim Start.
- Zeichen-für-Zeichen tippen statt Paste: nein, sonst brechen Umlaute/ß.
- Falsche Sample-Rate: Parakeet erwartet 16 kHz mono.
- Hardcodierte Sprache: nein, automatische Spracherkennung von v3 nutzen.
- Über-Engineering: keine zusätzlichen Features, keine Abstraktionsschichten, kein Plugin-System.

## Lizenz-Hinweis

Die Parakeet-Gewichte stehen unter der NVIDIA Community Model License, die MLX-Konvertierung kommt über `mlx-community`. Für lokale, interne Nutzung unproblematisch. Falls später Weitergabe/Distribution geplant ist, vorher die Lizenzbedingungen prüfen. Im README kurz vermerken.

## Bekannter Upgrade-Pfad (NICHT in v1 umsetzen, nur als Kontext)

Für eine spätere v2 / produktive Variante ist der native Weg **FluidAudio** (Swift SDK, Parakeet TDT v3 via CoreML auf der Apple Neural Engine, energieeffizienter, ~real-time-Faktor sehr hoch). Das ist der gleiche Unterbau, den VoiceInk und Spokenly für Parakeet nutzen. v1 bleibt aber bewusst Python + parakeet-mlx, um schnell etwas Lauffähiges zu haben.

---

**Erste Aktion für dich (Claude Code):** Lege die Projektstruktur an, richte das Environment ein und bringe `test_transcribe.py` zum Laufen. Zeig mir das Ergebnis des Kern-Checks, bevor du Hotkey und Paste baust.
