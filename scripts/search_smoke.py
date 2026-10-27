"""Smoke test for websearch.py: every route once on its own (Google only if --google), then search() three times to show the
round-robin. Output: <out_dir>\\search_smoke.json. Run: python scripts/search_smoke.py <out_dir> [--google]"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from studio import config, websearch  # noqa: E402

Q = "AI-assisted cyberattack on municipal water treatment plant"


def log(m): print(m, flush=True)


def main():
    out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
    cfg = config.load(); res = {"query": Q, "routes": {}, "rotation": []}
    names = ["wikipedia", "duckduckgo", "bing"]   # copilot not poked directly: it showed a human-verification check + (["google"] if "--google" in sys.argv else [])
    for n in names:
        t0 = time.time()
        try:
            s = websearch.ROUTES[n](cfg, Q); res["routes"][n] = {"ok": bool(s), "n": len(s), "first": s[:2], "secs": round(time.time() - t0, 1)}
        except Exception as e:
            res["routes"][n] = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}", "secs": round(time.time() - t0, 1)}
        log(f"{n}: {res['routes'][n]}")
    for k in range(3):
        s, used = websearch.search(cfg, Q, log); res["rotation"].append({"call": k + 1, "route": used, "n": len(s)})
    (out / "search_smoke.json").write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    log("ALL DONE")


if __name__ == "__main__":
    main()
