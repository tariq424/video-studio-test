"""Restart Video Studio at the first safe moment, then check that a job's editor beats load (owner, 2026-10-25).

Safe moment: no job running (idle, or a job paused at a review). A render is never interrupted: the full restart itself
refuses while a job runs. Jobs given with --hold that are only queued (not started) are held ("stopped" via the Stop button
behaviour, nothing lost) so Video Studio goes idle when the current render finishes; they are resumed right after the restart.

Usage: python scripts/restart_when_idle.py --job 20261025_bermuda --hold 20261025_175158 [--expect-short 18 --expect-long 57]
Result: F:/bermuda/_work/restart_idle_result.json (+ log restart_idle_log.txt)."""
import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

VS = "http://127.0.0.1:42021"
CODE = Path("F:/code")
JOBS = Path("F:/videos_test/jobs")
WORK = Path("F:/bermuda/_work")
LOG = WORK / "restart_idle_log.txt"
RES = WORK / "restart_idle_result.json"


def log(*a):
    line = time.strftime("[%Y-%m-%d %H:%M:%S] ") + " ".join(str(x) for x in a)
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f: f.write(line + "\n")


def call(path, body=None, timeout=20):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(VS + path, data=data, method="GET" if body is None else "POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r: return json.loads(r.read().decode("utf-8") or "{}")


def state(jid):
    try: return json.loads((JOBS / jid / "state.json").read_text(encoding="utf-8"))
    except Exception: return {}


def offline_check(jid):
    """The new code, run directly on the job folder (before the server has it)."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
    from studio import interview_edit as ie
    job = JOBS / jid; out = {}
    out["is_interview"] = bool(ie.is_interview(job))
    for k in ("short", "long"):
        m = json.loads((job / "iedit" / f"{k}.json").read_text(encoding="utf-8"))
        missing = [p["file"] for p in m["parts"] if not os.path.exists(p["file"])]
        out[k] = {"parts": len(m["parts"]), "missing": missing[:5]}
    cur = state(jid).get("edit_target", "short")
    for k in ("short", "long"):
        ie.set_target(job, k); out[k]["beats"] = len(ie.beats(job)["beats"])
    ie.set_target(job, cur)
    return out


def server_check(jid):
    out = {}
    cur = call(f"/api/jobs/{jid}/edit/beats").get("target") or "short"
    for k in ("short", "long"):
        r = call(f"/api/jobs/{jid}/edit/target", {"target": k})
        b = call(f"/api/jobs/{jid}/edit/beats")
        out[k] = {"target_ok": bool(r.get("ok")), "kind": b.get("kind"), "beats": len(b.get("beats") or []), "error": b.get("error", "")}
    call(f"/api/jobs/{jid}/edit/target", {"target": cur if cur in ("short", "long") else "short"})
    return out


def restart():
    """One plain full restart through the watcher -> (ok, text)."""
    only = CODE / ".restart-only"
    if only.exists(): return False, ".restart-only exists (another hook pending); retrying later"
    txt = CODE / ".restart-request-text"
    if txt.exists(): txt.write_text("", encoding="utf-8")   # never 'force'
    res = CODE / ".restart-result"; before = res.stat().st_mtime if res.exists() else 0
    (CODE / ".restart-request").write_text("plain restart: editor go-live", encoding="utf-8")
    t = time.time()
    while time.time() - t < 900:
        time.sleep(5)
        if res.exists() and res.stat().st_mtime > before:
            time.sleep(2); out = res.read_text(encoding="utf-8", errors="ignore")
            return ("SUCCESS" in out and "REFUSED" not in out), out[-600:]
    return False, "no restart result after 15 min"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True); ap.add_argument("--hold", nargs="*", default=[])
    ap.add_argument("--expect-short", type=int, default=0); ap.add_argument("--expect-long", type=int, default=0)
    ap.add_argument("--max-hours", type=float, default=8)
    a = ap.parse_args()
    res = {"job": a.job, "started": time.strftime("%Y-%m-%d %H:%M:%S"), "phase": "offline check"}
    save = lambda: RES.write_text(json.dumps(res, indent=1), encoding="utf-8")
    save()
    try: res["offline"] = offline_check(a.job)
    except Exception as e: res["offline"] = {"error": repr(e)[:500]}
    log("offline check:", json.dumps(res["offline"])); save()

    held = []
    try:
        res["phase"] = "waiting for a safe moment"; save()
        t0 = time.time(); tries = 0
        while time.time() - t0 < a.max_hours * 3600:
            for h in a.hold:   # hold the given jobs while they are only queued (never one that started)
                if h not in held and state(h).get("status") == "queued":
                    try: r = call(f"/api/jobs/{h}/stop", {}); held.append(h); log(f"held {h} (queued): {r}")
                    except Exception as e: log(f"hold {h} failed: {e}")
            try: cur = call("/api/status").get("current")
            except Exception as e: log("status:", e); time.sleep(20); continue
            if cur:
                time.sleep(15); continue
            log("Video Studio idle -> restarting"); tries += 1
            ok, txt = restart(); log("restart:", "OK" if ok else "not done", txt.replace("\n", " | ")[-400:])
            res["restart"] = {"ok": ok, "tries": tries, "out": txt[-600:], "at": time.strftime("%H:%M:%S")}; save()
            if ok: break
            if tries >= 12: break
            time.sleep(30)
        if not res.get("restart", {}).get("ok"):
            res["phase"] = "restart not done"; save(); return
        for _ in range(60):   # server back up
            try: call("/api/status"); break
            except Exception: time.sleep(5)
        res["phase"] = "server check"; save()
        try: res["server"] = server_check(a.job)
        except Exception as e: res["server"] = {"error": repr(e)[:500]}
        s = res.get("server", {})
        res["short_ok"] = s.get("short", {}).get("beats", 0) == (a.expect_short or s.get("short", {}).get("beats", -1)) and s.get("short", {}).get("beats", 0) > 0
        res["long_ok"] = s.get("long", {}).get("beats", 0) == (a.expect_long or s.get("long", {}).get("beats", -1)) and s.get("long", {}).get("beats", 0) > 0
        log("server check:", json.dumps(s))
    finally:
        for h in held:   # held jobs go back in the queue whatever happened
            try: call(f"/api/jobs/{h}/resume", {}); log(f"resumed {h}")
            except Exception as e: log(f"resume {h} failed: {e}")
        res["held_resumed"] = held; res["phase"] = "done"; res["ended"] = time.strftime("%Y-%m-%d %H:%M:%S"); save()


if __name__ == "__main__":
    main()
