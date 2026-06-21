# Parakeet Dictation Tool (macOS, v1)

Minimales lokales Diktier-Tool für macOS auf Apple Silicon.

**Push-to-talk:** Hotkey gedrückt halten, sprechen, loslassen — das Gesprochene wird
lokal mit **NVIDIA Parakeet TDT v3** (`mlx-community/parakeet-tdt-0.6b-v3`, multilingual,
automatische Spracherkennung für Deutsch/Englisch u. a.) transkribiert und per
Clipboard-Paste (`Cmd+V`) an der aktuellen Cursor-Position in der aktiven App eingefügt.

**100 % lokal.** Nach dem einmaligen Modell-Download (HuggingFace) verlässt zur Laufzeit
kein Audio das Gerät — funktioniert auch offline / im Flugmodus.

---

## Installation (Endnutzer)

1. **`ParakeetDictate.dmg`** vom [neuesten Release](../../releases/latest) laden.
2. DMG öffnen und **Parakeet Dictate** in den **Programme**-Ordner ziehen.
3. App starten — beim ersten Start führt sie dich durch die drei nötigen Berechtigungen
   (Mikrofon, Bedienungshilfen, Eingabeüberwachung) und lädt einmalig das Sprachmodell
   (~1–2 GB) herunter.
4. **Rechte Option-Taste** gedrückt halten, sprechen, loslassen — der Text erscheint an
   der Cursor-Position.

Die App ist signiert und notarisiert und öffnet ohne Gatekeeper-Warnung.

> Der Rest dieser Datei beschreibt den Betrieb **aus dem Source** (Entwicklung).
> Ein Release bauen: siehe [`packaging/RELEASE.md`](packaging/RELEASE.md).

---

## Voraussetzungen

- Apple Silicon Mac (M-Serie), **macOS 14+**
- [`uv`](https://github.com/astral-sh/uv) oder Python **3.11+**
- `ffmpeg` (wird von `parakeet-mlx` zum Einlesen von Audio benötigt)

---

## Setup

```bash
# 1. ffmpeg (falls noch nicht vorhanden)
brew install ffmpeg

# 2. Environment anlegen + Dependencies installieren (mit uv)
uv venv --python 3.12 .venv
uv pip install -r requirements.txt
```

Alternativ ohne `uv`:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## Kern-Check zuerst (empfohlen)

Bevor Hotkey & Paste relevant werden, einmal prüfen, dass Modell + Transkription auf der
Maschine sauber laufen. Eine kurze deutsche Test-WAV lässt sich mit dem macOS-`say`-Befehl
erzeugen:

```bash
say -v Anna -o sample.aiff "Guten Tag, dies ist ein Test mit Umlauten wie schön und größer."
ffmpeg -y -i sample.aiff -ar 16000 -ac 1 sample.wav

.venv/bin/python test_transcribe.py sample.wav
```

Beim **ersten** Lauf wird das Modell (~0.6 B Parameter) von HuggingFace geladen
(einige Minuten, je nach Verbindung). Danach ist es lokal gecacht und der Modell-Load
dauert nur noch ~1 s. Eine ~7-sekündige Aufnahme wird in unter 1 s transkribiert.

---

## macOS-Berechtigungen (häufigste Fehlerquelle!)

Das Tool — bzw. der **Terminal-/Python-Prozess**, der es startet — braucht drei Rechte
unter **Systemeinstellungen → Datenschutz & Sicherheit**:

| Berechtigung | Wofür | Wo |
|---|---|---|
| **Mikrofon** | Aufnahme | Datenschutz & Sicherheit → *Mikrofon* |
| **Bedienungshilfen** (Accessibility) | simuliertes `Cmd+V` | Datenschutz & Sicherheit → *Bedienungshilfen* |
| **Eingabeüberwachung** (Input Monitoring) | globaler Hotkey-Listener | Datenschutz & Sicherheit → *Eingabeüberwachung* |

Dort jeweils die App eintragen/aktivieren, aus der du startest — z. B. **Terminal**,
**iTerm** oder die genutzte IDE.

> **Wichtig:** Nach dem Vergeben der Rechte das Terminal (bzw. den Host-Prozess) **einmal
> komplett neu starten**, sonst greifen die Berechtigungen nicht.

---

## Benutzung

```bash
source .venv/bin/activate
python app.py
```

1. Warten, bis im Log `Bereit.` steht (Modell ist geladen und warm).
2. In einer beliebigen App den Cursor setzen (TextEdit, Browser, Slack …).
3. **Rechte Option-Taste gedrückt halten** → kurzer Ton, Aufnahme läuft (🔴).
4. Sprechen.
5. **Loslassen** → Transkription (✍️), dann wird der Text am Cursor eingefügt + Ton.

Das Menüleisten-Icon zeigt den Status: 🎙️ idle · 🔴 Aufnahme · ✍️ Transkription.
Beenden über **„Beenden"** im Menü (oder `Strg+C`, falls headless).

Deutsch und Englisch funktionieren ohne Umschalten — die Sprache wird automatisch erkannt.

---

## Konfiguration

Alles über Konstanten oben in `app.py`:

| Konstante | Default | Bedeutung |
|---|---|---|
| `HOTKEY` | `Key.alt_r` | Push-to-talk-Taste (z. B. `Key.cmd_r`, `Key.ctrl_r`) |
| `MODEL_ID` | `mlx-community/parakeet-tdt-0.6b-v3` | ASR-Modell (nicht ändern für v1) |
| `SAMPLE_RATE` | `16000` | Parakeet erwartet 16 kHz mono |
| `USE_MENUBAR` | `True` | Menüleisten-Icon; auf `False` für rein headless (Log + Ton) |
| `MIN_DURATION_S` | `0.3` | kürzere Aufnahmen (versehentlicher Tipp) ignorieren |
| `PASTE_SETTLE_S` | `0.2` | Wartezeit vor Clipboard-Wiederherstellung |

---

## Troubleshooting

- **Hotkey reagiert nicht / keine Reaktion beim Drücken** → *Eingabeüberwachung* nicht
  gewährt oder Terminal nicht neu gestartet.
- **Text wird nicht eingefügt** (Log zeigt Transkription, aber nichts erscheint) →
  *Bedienungshilfen* nicht gewährt.
- **Stille / leere Transkription** → *Mikrofon* nicht gewährt oder falsches Eingabegerät
  als System-Default ausgewählt.
- **`ffmpeg not found`** → `brew install ffmpeg`.
- **Warnung `You are sending unauthenticated requests to the HF Hub`** → harmlos, betrifft
  nur die Download-Rate beim ersten Mal. Optional `HF_TOKEN` setzen.

---

## Lizenz-Hinweis

Die Parakeet-Gewichte stehen unter der **NVIDIA Community Model License**; die
MLX-Konvertierung kommt über `mlx-community`. Für lokale, interne Nutzung unproblematisch.
Vor einer etwaigen Weitergabe/Distribution die Lizenzbedingungen prüfen.

---

## Bekannter Upgrade-Pfad (Kontext, nicht in v1)

Für eine spätere produktive Variante ist der native Weg **FluidAudio** (Swift SDK,
Parakeet TDT v3 via CoreML auf der Apple Neural Engine, energieeffizienter, sehr hoher
Realtime-Faktor) — derselbe Unterbau, den VoiceInk und Spokenly für Parakeet nutzen.
v1 bleibt bewusst Python + `parakeet-mlx`, um schnell etwas Lauffähiges zu haben.
