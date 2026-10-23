"""Find Hugging Face Spaces that make a talking head from a photo + audio TODAY (Spaces come and go), and test them.
Outside the pipeline: no job, no GPU on this PC. Results in F:\\videos_test\\poc\\talking_head.json and the clips next to it.
    app\\env\\Scripts\\python.exe scripts\\talking_head_probe.py [max_tests]
The working Spaces, fastest first, are written to settings.json talking_head_spaces (only if at least one worked)."""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from studio import config, media, talkinghead  # noqa: E402

OUT = Path(r"F:\videos_test\poc") if os.name == "nt" else Path.home() / "videos" / "poc"
SEARCH = ["sonic talking", "hallo", "echomimic", "sadtalker", "talking head", "lip sync", "float audio", "memo talking", "liveportrait audio"]


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(OUT / "talking_head.log", "a", encoding="utf-8") as f: f.write(line + "\n")


def sample_audio(cfg):
    """5 seconds of real narration from the newest job (or a spoken test line via espeak/SAPI if there is none)."""
    jobs = Path(cfg.get("jobs_dir") or ".")
    wavs = sorted(jobs.glob("*/short/voice/*.wav"), key=lambda p: p.stat().st_mtime, reverse=True)
    dest = OUT / "th_sample.wav"
    if wavs:
        media.ff("-t", 5, "-i", wavs[0], "-ac", 1, "-ar", 16000, dest); return dest
    raise RuntimeError("no narration found in the jobs folder to test with")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    max_tests = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    cfg = config.load()
    from huggingface_hub import HfApi
    api = HfApi(token=cfg.get("hf_token") or None)
    found = {}
    for q in SEARCH:
        try:
            for s in api.list_spaces(search=q, sort="likes", limit=8):
                found.setdefault(s.id, getattr(s, "likes", 0) or 0)
        except Exception as e: log(f"search '{q}' failed: {e}")
    cands = [k for k, _ in sorted(found.items(), key=lambda kv: -kv[1])]
    for k in talkinghead.SPACES:   # the built-in list is always looked at
        if k not in cands: cands.append(k)
    log(f"{len(cands)} Spaces found; checking which are running and take a photo + audio")
    usable = []
    for sid in cands[:40]:
        try:
            rt = api.get_space_runtime(sid)
            if str(getattr(rt, "stage", "")).upper() != "RUNNING": continue
            c = talkinghead._client(sid, cfg)
            ep, params = talkinghead.endpoint(c)
            if ep:
                usable.append({"space": sid, "likes": found.get(sid, 0), "api": ep, "inputs": len(params),
                               "hardware": str(getattr(rt, "hardware", ""))})
                log(f"  usable: {sid} {ep} ({len(params)} inputs, {getattr(rt, 'hardware', '')}, {found.get(sid, 0)} likes)")
        except Exception as e:
            log(f"  {sid}: {' '.join(str(e).split())[:120]}")
    img = talkinghead.presenter_photo(cfg, log)
    wav = sample_audio(cfg)
    results = []
    # CPU Spaces first: no ZeroGPU quota (the free quota is often spent on images by mid-morning), just slower
    usable.sort(key=lambda u: (u["hardware"].startswith("zero"), -u["likes"]))
    for u in usable[:max_tests]:
        t0 = time.time(); dest = OUT / f"th_{u['space'].replace('/', '_')}.mp4"
        try:
            talkinghead.call(u["space"], img, wav, dest, cfg, log, timeout=300)
            r = {**u, "ok": True, "secs": round(time.time() - t0), "file": str(dest), "dur": round(media.dur(dest), 1)}
        except Exception as e:
            r = {**u, "ok": False, "secs": round(time.time() - t0), "error": " ".join(str(e).split())[:300]}
        log(f"  TEST {u['space']}: {'OK' if r['ok'] else 'FAILED'} in {r['secs']}s {r.get('error', r.get('file', ''))}")
        results.append(r)
    good = [r["space"] for r in sorted((r for r in results if r["ok"]), key=lambda r: r["secs"])]
    if good:
        p = config.CFG; raw = json.loads(p.read_text(encoding="utf-8-sig")) if p.exists() else {}
        raw["talking_head_spaces"] = good; p.write_text(json.dumps(raw, indent=1), encoding="utf-8")
        log(f"settings.json talking_head_spaces = {good}")
    (OUT / "talking_head.json").write_text(json.dumps({"usable": usable, "tests": results, "chosen": good}, indent=1), encoding="utf-8")
    log("done")


if __name__ == "__main__":
    main()
