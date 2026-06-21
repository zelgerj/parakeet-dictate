"""
test_transcribe.py — core check: load Parakeet v3 and transcribe a WAV file.

Purpose: isolate model/environment problems BEFORE building the hotkey & paste.
This cleanly separates model issues from hotkey/paste issues.

Usage:
    python test_transcribe.py [path/to/recording.wav]

Without an argument it expects "sample.wav" in the current directory.
"""

import sys
import time

from parakeet_mlx import from_pretrained

MODEL_ID = "mlx-community/parakeet-tdt-0.6b-v3"


def main() -> None:
    wav_path = sys.argv[1] if len(sys.argv) > 1 else "sample.wav"

    print(f"Loading model {MODEL_ID} ...")
    t0 = time.perf_counter()
    model = from_pretrained(MODEL_ID)
    print(f"Model loaded in {time.perf_counter() - t0:.1f}s")

    print(f"Transcribing {wav_path} ...")
    t1 = time.perf_counter()
    result = model.transcribe(wav_path)
    dt = time.perf_counter() - t1

    print("-" * 60)
    print(result.text)
    print("-" * 60)
    print(f"Transcribed in {dt:.2f}s")


if __name__ == "__main__":
    main()
