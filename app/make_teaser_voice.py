"""Narration + word timings for the teaser short (runs on the PC in the studio env)."""
import json, sys, time
from pathlib import Path
from studio import config, render, captions
from studio.wangp import WanGP
J = Path(r"F:\videos\explainer_studio\shorts\moonshots_teaser")
cfg = config.load(); plan = json.loads((J / "plan.json").read_text(encoding="utf-8"))
log = lambda m: print(time.strftime("%H:%M:%S"), m, flush=True)
wg = WanGP(cfg["wangp_mcp"])
if not wg.alive(): sys.exit("WanGP is not running")
render.do_voice(J, plan, cfg, wg, log, lambda: False)
out = {}
for s in plan["sections"]:
    wt = captions.word_times(J / "voice" / f"{s['id']}.wav", s["vo"])
    from studio import media
    out[s["id"]] = {"dur": media.dur(J / "voice" / f"{s['id']}.wav"), "words": [[w, round(a, 3), round(b, 3)] for w, a, b in wt]}
    log(f"{s['id']}: {out[s['id']]['dur']:.1f}s")
(J / "timings.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
log("TEASER_VOICE_DONE")
