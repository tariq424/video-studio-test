"""Marble rung smoke test. Writes into <out_dir>; reads <out_dir>\\job.txt for what to do:
  record <world_url> [secs]   record a short walk-through of an existing world (costs no generation)
  scene <secs> <narration>    the full rung: prompt -> generate (spends ONE generation) -> record
Run: python scripts/marble_smoke.py <out_dir>"""
import json
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from studio import config, marble, media, qc_repair  # noqa: E402


def log(m): print(m, flush=True)


def main():
    out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
    job = (out / "job.txt").read_text(encoding="utf-8").strip().split(None, 2)
    cfg = config.load(); res = {"job": job, "started": time.strftime("%H:%M:%S")}
    try:
        if job[0] == "record":
            secs = float(job[2]) if len(job) > 2 else 4.0
            clip = marble.record(cfg, job[1], out / "marble_record.mp4", secs, (1920, 1080), log)
        else:
            secs = float(job[1]); clip = marble.scene(cfg, job[2], out / "marble_scene.mp4", secs, (1920, 1080), log)
        res["clip"] = str(clip); res["secs"] = round(media.dur(clip), 2)
        ok, why = qc_repair.clip_ok(cfg, clip, out / "chk", "marble")
        res["frame_check"] = "pass" if ok else f"fail: {why}"
        for k, t in enumerate((0.5, res["secs"] / 2, max(0.5, res["secs"] - 0.5))):
            media.ff("-ss", f"{t:.2f}", "-i", clip, "-frames:v", 1, "-vf", "scale=640:-2", out / f"frame_{k}.jpg", check=False)
    except Exception as e:
        res["error"] = f"{type(e).__name__}: {str(e)[:400]}"; log(traceback.format_exc())
    res["finished"] = time.strftime("%H:%M:%S")
    (out / "result.json").write_text(json.dumps(res, indent=1), encoding="utf-8"); log(json.dumps(res))


if __name__ == "__main__":
    main()
