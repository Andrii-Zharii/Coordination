"""Transcribe voice notes of recorded cases (cases/**/note*.wav) to note text.

Runs in the cloud session (not in Revit):
    pip install faster-whisper
    HF_HUB_DISABLE_XET=1 python3 tools/transcribe_cases.py [cases_dir]

For each <name>.wav without a matching <name>.transcript.txt, writes the Ukrainian
transcript next to it. Audio is decoded with ffmpeg (must be installed).
"""
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel

MODEL = "large-v3-turbo"


def load_audio(path):
    raw = subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(path),
         "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
        check=True, capture_output=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0


def main():
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "cases"
    todo = [w for w in sorted(root.rglob("*.wav"))
            if not w.with_suffix(".transcript.txt").exists()]
    if not todo:
        print("Nothing to transcribe.")
        return
    model = WhisperModel(MODEL, device="cpu", compute_type="int8")
    for wav in todo:
        started = time.time()
        segments, _ = model.transcribe(load_audio(wav), language="uk", vad_filter=True)
        text = " ".join(s.text.strip() for s in segments).strip()
        wav.with_suffix(".transcript.txt").write_text(text + "\n", encoding="utf-8")
        print(f"{wav.relative_to(root)} ({time.time() - started:.0f}s): {text}")


if __name__ == "__main__":
    main()
