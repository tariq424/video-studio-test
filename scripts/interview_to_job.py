"""Open an interview edit (app/studio/interview.py) as a Video Studio job you can scrub, edit and chat about.
Usage: python scripts/interview_to_job.py <short_parts.json> <long_parts.json> [job_id]
Copies (hard-links where possible) the finished Short and documentary into a new job folder, with the parts manifests;
pieces whose picture was a guess (mostly blurred / covered / on its side) are marked "check" (owner: stop if not sure)."""
import json, os, shutil, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from studio import config, media, shots  # noqa: E402


def link(a, b):
    b.parent.mkdir(parents=True, exist_ok=True)
    try: os.link(a, b)
    except OSError: shutil.copy2(a, b)


def check(m, p):
    mm = p.get("m") or {}
    if mm.get("type") not in ("bite", "narr") or mm.get("si") is None: return False
    an_dir = m["sources"][int(mm["si"])][2]
    try: an = json.loads((Path(an_dir) / "faces.json").read_text(encoding="utf-8"))
    except Exception: return False
    by = {x["t"]: shots.kind_keep(x) for x in an.get("secs") or []}
    t0 = float(mm.get("t0") or 0); t1 = float(mm.get("t1") or t0 + float(p.get("dur") or 0))
    secs = list(range(int(t0), max(int(t0) + 1, int(t1))))
    bad = sum(1 for t in secs if by.get(t, "none") in ("blur",) or str(by.get(t, "")).startswith("turn"))
    return bad / max(1, len(secs)) >= 0.3


def main():
    cfg = config.load()
    sm, lm = (json.loads(Path(x).read_text(encoding="utf-8")) for x in sys.argv[1:3])
    jid = sys.argv[3] if len(sys.argv) > 3 else time.strftime("%Y%m%d_%H%M%S")
    jd = Path(cfg.get("jobs_dir") or "F:/videos_test/jobs") / jid
    if (jd / "state.json").exists(): print("job exists:", jd); return
    outs = {}
    for k, m in (("short", sm), ("long", lm)):
        dst = jd / "output" / Path(m["out"]).name; link(Path(m["out"]), dst); outs[k] = str(dst)
        for p in m["parts"]:
            p["dur"] = media.dur(p["file"]); p["check"] = check(m, p)
        (jd / "iedit").mkdir(parents=True, exist_ok=True)
        (jd / "iedit" / f"{k}.json").write_text(json.dumps(m, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"{k}: {len(m['parts'])} pieces, {sum(1 for p in m['parts'] if p['check'])} marked check")
    st = {"kind": "interview", "title": lm.get("title") or sm.get("title") or "Interview", "status": "finished", "stage": "done", "mode": "both",
          "output": outs["long"], "short_output": outs["short"], "edit_target": "short", "created": time.time(), "updated": time.time(),
          "url": "", "src_title": lm.get("title", ""), "captions": True, "done": ["interview"], "visual_review": "never"}
    (jd / "state.json").write_text(json.dumps(st, indent=1), encoding="utf-8")
    (jd / "log.txt").write_text(f"Interview edit opened as a job from {sys.argv[1]} and {sys.argv[2]}\n", encoding="utf-8")
    print("job", jid, jd)


if __name__ == "__main__": main()
