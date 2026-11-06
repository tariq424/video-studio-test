"""Run ONE media route from the command line, for Video Studio's visual ladder (studio/mediaroutes.py).

    venv\\Scripts\\python.exe run_route.py r6 --desc "..." --aspect 16:9 [--image in.jpg] --out F:\\job\\x.jpg

Uses this folder's signed-in browser profiles and secrets. Prints ONE JSON line on stdout:
    {"status": "ok" | "blocker" | "failed", "output": <copied --out path or null>, "note": "...", "seconds": n}
Exit code 0 for ok, 2 for blocker / failed. Routes that fall back to an earlier output (r7 without --image) are told not to.
"""
import argparse, json, shutil, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("route")
    ap.add_argument("--desc", required=True)
    ap.add_argument("--aspect", default="16:9")
    ap.add_argument("--image", default=None)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    import routes
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
