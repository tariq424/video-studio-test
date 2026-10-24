"""Talking-head render test (the feature is optional; this proves it works when someone ticks "presenter").
Takes a finished Short (default: the newest smoke-test Short), waits until Video Studio is idle (the running job is never
touched), holds the Newsroom so no new job grabs the GPU, lays the talking head over the hook with the configured engine
(talking_head: wangp = this PC's WanGP, hf = Hugging Face), releases the hold and writes:
  F:\\videos_test\\smoke\\talkinghead\\<name>_talkinghead.mp4 + result.json
Run: python scripts/talking_head_test.py [--job <jobs dir>\\<job id>] [--engine wangp|hf]"""
import argparse
import json
import shutil
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from studio import config, talkinghead  # noqa: E402

HOLD = Path(r"F:\videos\newsroom\hold")
OUT = Path(r"F:\videos_test\smoke\talkinghead")


def log(m): print(time.strftime("%H:%M:%S"), m, flush=True)


def newest_short(jobs):
    for j in sorted((p for p in Path(jobs).iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True):
        f = sorted((j / "output").glob("*_short.mp4")) if (j / "output").is_dir() else []
        if f and (j / "short" / "public" / "teaser.json").exists(): return j, f[0]
    raise RuntimeError("no finished Short found")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--job", default=""); ap.add_argument("--engine", default=""); a = ap.parse_args()
    cfg = config.load()
    if a.engine: cfg["talking_head"] = a.engine
    job, mp4 = (Path(a.job), sorted((Path(a.job) / "output").glob("*_short.mp4"))[0]) if a.job else newest_short(cfg["jobs_dir"])
    OUT.mkdir(parents=True, exist_ok=True)
    tj = OUT / "job"; (tj / "short" / "public").mkdir(parents=True, exist_ok=True)
    shutil.copy2(job / "short" / "public" / "teaser.json", tj / "short" / "public" / "teaser.json")
    dst = OUT / (mp4.stem + "_talkinghead.mp4"); shutil.copy2(mp4, dst)
    held = False; t0 = time.time()
    try:
        def current():
            try: return requests.get("http://127.0.0.1:42021/api/status", timeout=10).json().get("current")
            except Exception: return None
        for i in range(1440):   # up to 12 h; the pipeline keeps working while we wait (no hold until Video Studio is idle)
            cur = current()
            if not cur:
                if not HOLD.exists(): HOLD.write_text("talking head test", encoding="utf-8"); held = True; log("Video Studio idle: Newsroom held")
                time.sleep(5)
                if not current(): break
                if held: HOLD.unlink(); held = False   # a job started in the gap: let it run, wait again
            if i % 20 == 0: log(f"waiting for job {cur} to finish (not touched)")
            time.sleep(30)
        log(f"engine: {talkinghead.engine(cfg)}; Short: {mp4.name}")
        t1 = time.time(); talkinghead.overlay_short(tj, None, cfg, dst, log)
        res = json.loads((tj / "short" / "talkinghead" / "talkinghead.json").read_text(encoding="utf-8"))
        res.update(short=str(dst), source=str(mp4), render_secs=round(time.time() - t1), waited_secs=round(t1 - t0))
    except Exception as e:
        res = {"ok": False, "error": str(e)[:600]}
    finally:
        if held and HOLD.exists() and HOLD.read_text(encoding="utf-8").strip() == "talking head test": HOLD.unlink(); log("Newsroom hold released")
    (OUT / "result.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    log(f"result: {res}")


if __name__ == "__main__":
    main()
