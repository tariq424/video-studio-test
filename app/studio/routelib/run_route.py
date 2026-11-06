"""Run ONE media route in its own process, for Video Studio's visual ladder (studio/mediaroutes.py starts it).

    python -m studio.routelib.run_route r6 --desc "..." --aspect 16:9 [--image in.jpg] --out F:\\job\\x.jpg   (cwd: app)

Uses the signed-in browser profiles in VS_MEDIA_DATA (mediaroutes.py sets it). Prints ONE JSON line on stdout:
    {"status": "ok" | "blocker" | "failed", "output": <copied --out path or null>, "note": "...", "seconds": n}
Exit code 0 for ok, 2 for blocker / failed. Routes that would reuse an earlier output (r7 without --image) are told not to.
"""
import argparse, json, shutil, sys, time
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("route")
    ap.add_argument("--desc", required=True)
    ap.add_argument("--aspect", default="16:9")
    ap.add_argument("--image", default=None)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    from . import routes
    r = next((x for x in routes.ROUTES if x["id"] == a.route or x["name"] == a.route), None)
    if r is None:
        print(json.dumps({"status": "failed", "output": None, "note": f"unknown route {a.route}", "seconds": 0})); return 2
    ctx, t0 = {"no_fallback": True}, time.time()
    try:
        out = r["fn"](a.desc, a.aspect, a.image, ctx)
        dest = Path(a.out); dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out, dest)
        res = {"status": "ok", "output": str(dest), "note": ctx.get("card_note", "")}
    except routes.Blocker as b:
        res = {"status": "blocker", "output": None, "note": str(b)}
    except Exception as e:
        res = {"status": "failed", "output": None, "note": f"{type(e).__name__}: {str(e)[:300]}"}
    res["seconds"] = round(time.time() - t0, 1)
    print(json.dumps(res))
    return 0 if res["status"] == "ok" else 2


if __name__ == "__main__":
    sys.exit(main())
