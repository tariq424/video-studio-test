"""Clip check regression set: every mismatch the owner flags becomes a case here, and every change to the clip check runs it.
Cases: F:\\videos_test\\smoke\\clipcheck\\cases.json  [{"image", "narration", "expect": "KEEP|DROP", "neutral": false, "why"}]
(image = a clip's 4-frame contact sheet in cases\\). The beat's main subject / kind / place come from the live beat_mains call,
the frames from the live vision model, the verdict from contra_verdict: the same path a real job takes.
Report: clipcheck\\report.md + report.json. Run: python scripts/clipcheck_probe.py [--dir F:\\videos_test\\smoke\\clipcheck]"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from studio import config, footage  # noqa: E402
from studio.llm import parse_json  # noqa: E402


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--dir", default=r"F:\videos_test\smoke\clipcheck"); a = ap.parse_args()
    d = Path(a.dir); cases = json.loads((d / "cases.json").read_text(encoding="utf-8"))
    cfg = config.load()
    if cfg.get("vet_provider", "local") in ("off", "", None): cfg["vet_provider"] = "local"
    log = lambda m: print(m, flush=True)
    slots = [{"id": f"c{i}", "narration": c["narration"], "text": c["narration"], "cta": c.get("neutral", False)} for i, c in enumerate(cases)]
    mains = footage.beat_mains(cfg, slots, log)
    footage.ensure_vet_model(cfg, log)
    rows, good = [], 0
    for i, c in enumerate(cases):
        mv = mains.get(f"c{i}", {}); t = time.time()
        img = d / "cases" / c["image"]
        prompt = footage.CONTRA.format(main=mv.get("main") or "the thing the narration is about", kind=mv.get("kind") or "thing",
                                       narration=c["narration"][:300].replace('"', "'"))
        try:
            raw = footage._vision(cfg, img, prompt); j = parse_json(raw)
            ok, why = footage.contra_verdict(cfg, j, mv, mv.get("place", "") or c.get("place", ""), c.get("neutral", False), log, narration=c["narration"], story=c.get("story", ""))
        except Exception as e:
            raw, j, ok, why = str(e), {}, None, f"error: {str(e)[:120]}"
        verdict = "KEEP" if ok else "DROP"
        hit = None if c["expect"] == "?" else verdict == c["expect"]; good += bool(hit)   # "?" = for a human to judge
        rows.append({"image": c["image"], "expect": c["expect"], "verdict": verdict, "pass": hit, "why": why, "main": mv,
                     "seen": j.get("seen", "") if isinstance(j, dict) else "", "secs": round(time.time() - t, 1), "raw": raw[:600]})
        log(f"{'REVIEW' if hit is None else 'PASS' if hit else 'FAIL'} {c['image']}: expect {c['expect']}, got {verdict} {('(' + why + ')') if why else ''}")
    footage.unload_vet_model(cfg)
    (d / "report.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    scored = [r for r in rows if r["pass"] is not None]
    md = [f"# Clip check regression: {good}/{len(scored)} pass ({len(rows) - len(scored)} for review)", "", "| case | expect | got | why | main subject | seen |", "|---|---|---|---|---|---|"]
    md += [f"| {r['image']} | {r['expect']} | {r['verdict']}{' (review)' if r['pass'] is None else '' if r['pass'] else ' FAIL'} | {r['why']} | {r['main'].get('main', '')} / {r['main'].get('place', '')} | {r['seen'][:90]} |" for r in rows]
    (d / "report.md").write_text("\n".join(md), encoding="utf-8")
    print(f"{good}/{len(scored)} pass, {len(rows) - len(scored)} for review")


if __name__ == "__main__":
    main()
