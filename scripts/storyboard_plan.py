"""Storyboard plan for a Video Studio job, printed without generating anything (no credits, no GPU).

Usage (from the repo root):  app\\env\\Scripts\\python.exe scripts\\storyboard_plan.py <job_id> [beat ids, e.g. b2 b4]
Shows the locked visual style, how each beat's narration is cut (~4 s pieces) and the standalone prompt for every piece.
Used by the storyboard skill's check step; generation itself goes through the running app (POST /api/jobs/<id>/review/<beat>
{"action": "storyboard"}), so the GPU interlock and the editor see it."""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from studio import config, storyboard, tts  # noqa: E402
from studio.pipeline import Job  # noqa: E402


def main(argv):
    if not argv: print(__doc__); return 2
    cfg = config.load(); jd = Path(cfg["jobs_dir"]) / argv[0]
    j = Job(jd); sp = j.short_plan()
    if not sp: print(f"no Short plan in {jd}"); return 1
    if j.state.get("kokoro_voice"): cfg["kokoro_voice"] = j.state["kokoro_voice"]
    secs = [s for s in sp["sections"] if not s.get("cta") and (len(argv) < 2 or s["id"] in argv[1:])]
    story = " ".join(s.get("vo", "") for s in sp["sections"] if not s.get("cta"))
    prof = storyboard.style_profile(cfg, jd / "short", print)
    out = {"style": prof, "beats": {}}
    for s in secs:
        parts = storyboard.pieces(s.get("vo", ""), tts.wpm(cfg))[: int(cfg.get("storyboard_max_shots", 6))]
        try: out["beats"][s["id"]] = storyboard.write_prompts(cfg, s, parts, prof, story, print) if len(parts) >= 2 else "too short to split"
        except Exception as e: out["beats"][s["id"]] = f"prompt writing failed: {e}"
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
