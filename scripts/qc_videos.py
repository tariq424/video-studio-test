"""QC already-finished videos in place (owner, 2026-10-24: "check all the unstaged videos now and fix before horses leave
the barn"). Each original is kept in <backup>\\<job>\\ first; then qc.qc_part (fix) + qc.qc_final (sheet next to the backup).
Run: python scripts/qc_videos.py <list.json> <backup_dir>"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from studio import config, qc  # noqa: E402


def log(m): print(m, flush=True)


def main():
    try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
    files = [Path(x) for x in json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))]
    bdir = Path(sys.argv[2]); cfg = config.load()
    if not qc.available(cfg): log("the local vision model isn't running; nothing checked"); return
    for f in files:
        if not f.exists(): log(f"missing: {f}"); continue
        job = f.parent.parent.name; b = bdir / job; b.mkdir(parents=True, exist_ok=True)
        if not (b / f.name).exists(): shutil.copy2(f, b / f.name)   # the untouched original
        vert = "short" in f.stem.lower()
        log(f"== {job} {f.name}")
        try:
            qc.qc_part(f, cfg, log, every=4.0 if vert else 6.0, label=f.stem[:30], kind="short" if vert else "documentary")
            qc.qc_final(f, cfg, b, log, every=10.0 if vert else 30.0)
        except Exception as e:   # e.g. the video is open in a player: skip it, carry on
            log(f"   skipped ({type(e).__name__}: {str(e)[:150]})")
    log("ALL DONE")


if __name__ == "__main__":
    main()
