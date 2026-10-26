"""Smoke test for QC repair-by-ladder (app/studio/qc_repair.py) on the QC smoke specimen B (black injected at 50-60 s).
Works only on copies in <smoke>\\repair\\; the specimens themselves are never touched.
  1. every rung once, on its own, for B's black span (no splice): did it produce a clip that passes the frame check?
  2. the full repair (ladder order, first passing rung wins) on a copy of B, spliced
  3. the repaired copy re-checked from scratch by qc_part (report mode): the span must be gone; length and audio unchanged
Run: python scripts/qc_repair_smoke.py <smoke_dir> [rung,rung,...]  -> <smoke_dir>\\repair\\repair_smoke.json"""
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from studio import config, media, qc, qc_repair  # noqa: E402

VO = ("Security researchers say attackers used AI tools to plan intrusions into water treatment systems, "
      "probing the control software that runs pumps and chemical dosing at municipal water plants.")


def log(m): print(m, flush=True)


def audio_md5(p):
    r = subprocess.run([media._bin("ffmpeg"), "-v", "error", "-i", str(p), "-map", "0:a", "-c", "copy", "-f", "md5", "-"],
                       capture_output=True, text=True, timeout=300)
    return r.stdout.strip()


def fresh_copy(src, dst):
    shutil.copy2(src, dst)
    shutil.copy2(src.with_suffix(".qc.json"), dst.with_suffix(".qc.json"))   # the round-7 markers (report mode)
    return dst


def main():
    try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
    smoke = Path(sys.argv[1]); only = sys.argv[2].split(",") if len(sys.argv) > 2 and sys.argv[2] else None
    cfg = config.load(); B = smoke / "specimen_B.mp4"
    out = smoke / "repair"; out.mkdir(exist_ok=True); job = out / "job"; job.mkdir(exist_ok=True)
    res = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "specimen_B_sha": hashlib.sha256(B.read_bytes()).hexdigest(),
           "narration": VO, "rungs": [], "full": None, "recheck": None}
    if not qc.available(cfg): log("vision model not running; stop"); return
    sp = qc_repair.spans(B); log(f"markers in specimen_B: {sp}"); res["markers"] = sp
    if not sp: log("no markers; stop"); return
    a, b, faults = sp[0]
    W, H, fps = qc_repair._probe(B)
    # 1. each rung alone
    for name, fn in qc_repair.RUNGS:
        if only and name not in only: continue
        if name == "static_image": continue   # needs images left by the image rungs; exercised inside the full run
        work = out / f"rung_{name}"; work.mkdir(exist_ok=True)
        ctx = {"cfg": cfg, "log": log, "mp4": B, "job": job, "vert": False, "W": W, "H": H, "a": a, "b": b, "need": b - a,
               "key": f"smoke_{name}", "work": work, "images": [], "vo": VO}
        log(f"== rung {name}"); t0 = time.time()
        try: clip, img, why = fn(ctx)
        except Exception as e: clip, img, why = None, None, f"error: {type(e).__name__}: {str(e)[:200]}"
        row = {"rung": name, "ok": bool(clip), "note": why, "clip": str(clip) if clip else "", "secs": round(time.time() - t0, 1)}
        if clip:
            try: row["clip_secs"] = round(media.dur(clip), 2)
            except Exception: pass
        if ctx.get("research"): row["research"] = ctx["research"]
        log(f"   -> {'OK' if clip else 'no'}: {why} ({row['secs']}s)"); res["rungs"].append(row)
        (out / "repair_smoke.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    # 2. the full repair, ladder order
    if not only or "full" in only:
        C = fresh_copy(B, out / "specimen_B_fix.mp4"); before = media.dur(C); a0 = audio_md5(C)
        log("== full repair (ladder order)")
        rep = qc_repair.repair(C, cfg, job, log, vert=False, narration_text=VO)
        res["full"] = rep
        after = media.dur(C); a1 = audio_md5(C)
        res["full_checks"] = {"dur_before": round(before, 2), "dur_after": round(after, 2), "audio_identical": a0 == a1 and bool(a0)}
        log(f"   duration {before:.2f} -> {after:.2f}s; audio identical: {a0 == a1 and bool(a0)}")
        # 3. re-check from scratch
        C.with_suffix(".qc.json").unlink(missing_ok=True)
        qc.qc_part(C, dict(cfg, qc_mode="report"), log, every=6.0, label="B_fixed", kind="documentary")
        rc = json.loads(C.with_suffix(".qc.json").read_text(encoding="utf-8"))
        res["recheck"] = {k: rc.get(k) for k in ("status", "unchecked", "would_fix", "soft")}
        log(f"   recheck: would_fix {rc.get('would_fix')} status {rc.get('status')}")
        for t in (52.0, 55.0, 58.0):   # frames from inside the repaired span, for the eye
            media.ff("-ss", f"{t:.2f}", "-i", C, "-frames:v", 1, "-vf", "scale=640:-2", out / f"fixed_{int(t)}s.jpg", check=False)
    res["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    (out / "repair_smoke.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    log("ALL DONE")


if __name__ == "__main__":
    main()
