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
    a = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    work = Path(a["work"]); work.mkdir(parents=True, exist_ok=True)
    lf = open(work / "interview.log", "a", encoding="utf-8")
    def log(m):
        line = f"[{time.strftime('%H:%M:%S')}] {m}"; print(line, flush=True); lf.write(line + "\n"); lf.flush()
    cfg = config.load()
    try:
        outs = interview.build(cfg, a["src"], work, a.get("context", ""), log, tuple(a.get("kinds") or ("short", "documentary")),
                               bool(a.get("flip", True)), a.get("name", "interview"), a.get("version", ""), a.get("notes"))
        log(f"DONE: {outs}")
    except Exception as e:
        import traceback
        log(f"FAILED: {e}\n{traceback.format_exc()[-2000:]}")


if __name__ == "__main__":
    main()
