"""Open an interview edit (app/studio/interview.py) as a Video Studio job you can scrub, edit and chat about.
Usage: python scripts/interview_to_job.py <short_parts.json> <long_parts.json> [job_id]
Copies (hard-links where possible) the finished Short and documentary into a new job folder, with the parts manifests;
pieces whose picture was a guess (mostly blurred / covered / on its side) are marked "check" (owner: stop if not sure)."""
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from studio import config, interview_edit  # noqa: E402


def main():
    cfg = config.load()
    sm, lm = (json.loads(Path(x).read_text(encoding="utf-8")) for x in sys.argv[1:3])
    jid = sys.argv[3] if len(sys.argv) > 3 else time.strftime("%Y%m%d_%H%M%S")
    jd = Path(cfg.get("jobs_dir") or "F:/videos_test/jobs") / jid
    if (jd / "state.json").exists(): print("job exists:", jd); return
    outs = interview_edit.adopt(jd, {"short": sys.argv[1], "long": sys.argv[2]})
    st = {"kind": "interview", "title": lm.get("title") or sm.get("title") or "Interview", "status": "finished", "stage": "done", "mode": "both",
          "output": outs["long"], "short_output": outs["short"], "edit_target": "short", "created": time.time(), "updated": time.time(),
          "url": "", "src_title": lm.get("title", ""), "captions": True, "done": ["interview"], "visual_review": "never"}
    (jd / "state.json").write_text(json.dumps(st, indent=1), encoding="utf-8")
    (jd / "log.txt").write_text(f"Interview edit opened as a job from {sys.argv[1]} and {sys.argv[2]}\n", encoding="utf-8")
    print("job", jid, jd)


if __name__ == "__main__": main()
