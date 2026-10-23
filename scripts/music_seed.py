"""Make the starting music library with Gemini: one original track per mood that the library doesn't have yet.
Slow on purpose (a pause between requests); outside any job. Log and screenshots in the music folder.
    app\\env\\Scripts\\python.exe scripts\\music_seed.py [max_tracks]     (default 10; 1 = a quick check that it works)"""
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from studio import config, music, music_gen  # noqa: E402


def main():
    cfg = config.load()
    root = music.folder(cfg); root.mkdir(parents=True, exist_ok=True)
    logf = root / "seed.log"
    def log(m):
        line = f"[{time.strftime('%H:%M:%S')}] {m}"; print(line, flush=True)
        with open(logf, "a", encoding="utf-8") as f: f.write(line + "\n")
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    have = {x["mood"] for x in music.library(cfg)}
    todo = [m for m in music.MOODS if m not in have][:n]
    log(f"library: {len(music.library(cfg))} track(s); making {len(todo)}: {', '.join(todo) or 'nothing'}")
    ok = 0
    for i, mood in enumerate(todo):
        kind, desc = music.MOODS[mood]
        out = root / kind / f"{mood}_{time.strftime('%Y%m%d_%H%M%S')}.mp3"
        try:
            music_gen.generate(dict(cfg, music_generate_per_day=99), desc, out, log, evidence_dir=root)
            music.add_to_library(cfg, out, kind, mood, desc); ok += 1
        except Exception as e:
            log(f"  {mood}: FAILED {' '.join(str(e).split())[:300]}")
            if i == 0: log("stopping: the first track failed (see the screenshot in this folder)"); break
        if i < len(todo) - 1: time.sleep(random.uniform(25, 45))
    log(f"done: {ok} new track(s); library now {len(music.library(cfg))}")


if __name__ == "__main__":
    main()
