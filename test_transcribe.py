"""
test_transcribe.py — Kern-Check: lädt Parakeet v3 und transkribiert eine WAV-Datei.

Zweck: Modell-/Umgebungsprobleme isolieren, BEVOR Hotkey & Paste gebaut werden.
So trennen wir Modell-Probleme sauber von Hotkey/Paste-Problemen.

Nutzung:
    python test_transcribe.py [pfad/zur/aufnahme.wav]

Ohne Argument wird "sample.wav" im aktuellen Verzeichnis erwartet.
"""

import sys
import time

from parakeet_mlx import from_pretrained

MODEL_ID = "mlx-community/parakeet-tdt-0.6b-v3"


def main() -> None:
    wav_path = sys.argv[1] if len(sys.argv) > 1 else "sample.wav"

    print(f"Lade Modell {MODEL_ID} ...")
    t0 = time.perf_counter()
    model = from_pretrained(MODEL_ID)
    print(f"Modell geladen in {time.perf_counter() - t0:.1f}s")

    print(f"Transkribiere {wav_path} ...")
    t1 = time.perf_counter()
    result = model.transcribe(wav_path)
    dt = time.perf_counter() - t1

    print("-" * 60)
    print(result.text)
    print("-" * 60)
    print(f"Transkription in {dt:.2f}s")


if __name__ == "__main__":
    main()
