"""Transcribe extra interview clips (owner, 2026-10-24: the two other clips with Mr. Clinton, for version 16).
Run: python scripts/transcribe_clips.py <out_dir> <clip> [<clip> ...]   -> <out_dir>/<clip stem>/transcript.json + transcript.txt"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from studio import interview  # noqa: E402


def main():
    try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
    out = Path(sys.argv[1])
    for c in sys.argv[2:]:
        w = out / Path(c).stem.rstrip(".")
        w.mkdir(parents=True, exist_ok=True)
        segs = interview.transcribe(c, w, print)
        (w / "transcript.txt").write_text("\n".join(f"[{s['i']}] {s['start']:.0f}-{s['end']:.0f}: {s['text']}" for s in segs), encoding="utf-8")
        print(f"done: {c} -> {len(segs)} segments", flush=True)


if __name__ == "__main__":
    main()
