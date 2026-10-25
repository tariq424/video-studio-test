"""Run an interview edit (app/studio/interview.py) on your own footage.
Args file (JSON): {"src": "F:\\\\bermuda\\\\clip.MOV", "work": "F:\\\\videos\\\\interview\\\\bermuda", "name": "bermuda",
                   "context": "who / where / what", "kinds": ["short", "documentary"], "flip": true,
                   "version": "v2" (subfolder for this plan), "notes": [{"fact": "...", "source": "url"}] (checked context facts)}
Run: python scripts/interview_edit.py <args.json>   (log: <work>\\interview.log)"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from studio import config, interview  # noqa: E402


def main():
    try: sys.stdout.reconfigure(encoding="utf-8", errors="replace"); sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass   # a Windows console in cp1252 can't print every letter (a Turkish i in a stock clip's title stopped a run)
    a = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    work = Path(a["work"]); work.mkdir(parents=True, exist_ok=True)
    lf = open(work / "interview.log", "a", encoding="utf-8")
    def log(m):
        line = f"[{time.strftime('%H:%M:%S')}] {m}"; print(line, flush=True); lf.write(line + "\n"); lf.flush()
    cfg = config.load()
    cfg.update(a.get("cfg") or {})   # per-video settings (keep-the-scene, Short length and topics, end-card line)
    lock = work / "interview.lock"   # one edit at a time per work folder (two runs once wrote the same file)
    if lock.exists() and time.time() - lock.stat().st_mtime < 4 * 3600:
        log(f"another interview edit is running here (lock {lock}); not starting"); return
    lock.write_text(str(time.time()), encoding="utf-8")
    try:
        outs = interview.build(cfg, a["src"], work, a.get("context", ""), log, tuple(a.get("kinds") or ("short", "documentary")),
                               bool(a.get("flip", True)), a.get("name", "interview"), a.get("version", ""), a.get("notes"),
                               extras=a.get("extras"))
        log(f"DONE: {outs}")
    except Exception as e:
        import traceback
        log(f"FAILED: {e}\n{traceback.format_exc()[-2000:]}")
    finally:
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
