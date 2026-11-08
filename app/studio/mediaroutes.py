"""Media routes for the visual ladder (2026-11-06). The route code lives in Video Studio (studio/routelib, moved in from the
media-poc setup page) and runs in its own process on Video Studio's Python, so a stuck browser can be timed out and killed:

    python -m studio.routelib.run_route <route> --desc ... --aspect ... [--image ...] --out <file>      (cwd: app)

Signed-in browser profiles, route outputs and logs live in the data folder (setting media_routes_data; default
<jobs_dir parent>\\media_routes). OPEN LOGIN for a site = scripts\\media-login.ps1 <site>.
Used by: imagegen ("meta" service = r6), rung 3a chain (r12 Copilot describe, r13 Meta image -> video), rung 3b (r11 Blender),
rung 5 (r7 Meta video, r8 Flow). run() never raises (cancel aside): it returns the output or None, and logs why."""
import json, os, subprocess, sys, time
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
_down = {}   # route -> reason it is off for the rest of this process (signed out ...)


def data_dir(cfg):
    if cfg.get("media_routes_data"): return Path(cfg["media_routes_data"])
    jobs = cfg.get("jobs_dir")
    return (Path(jobs).parent if jobs else APP.parent) / "media_routes"


def routes_dir(cfg):   # where a route leaves its own output files (r13_meta_chain.jpg ...)
    return data_dir(cfg)


def available(cfg, route=None):
    return (APP / "studio" / "routelib" / "run_route.py").is_file() and (data_dir(cfg) / "profiles").is_dir() \
        and not (route and route in _down)


def run(cfg, route, desc, aspect, out, log, image=None, timeout=None):
    """-> {"output": Path, "note": str} or None."""
    d = data_dir(cfg)
    if not available(cfg):
        log(f"  {route}: no signed-in browser profiles at {d / 'profiles'} (setting media_routes_data)"); return None
    if route in _down:
        log(f"  {route} skipped ({_down[route]})"); return None
    cmd = [sys.executable, "-m", "studio.routelib.run_route", route, "--desc", str(desc)[:1500], "--aspect", aspect, "--out", str(out)]
    if image: cmd += ["--image", str(image)]
    env = dict(os.environ, VS_MEDIA_DATA=str(d), PYTHONIOENCODING="utf-8")
    t0 = time.time()
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    limit = int(timeout or cfg.get("media_routes_timeout", 900))
    proc = subprocess.Popen(cmd, cwd=str(APP), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace", creationflags=flags)
    try:
        out_s, err_s = proc.communicate(timeout=limit)
    except subprocess.TimeoutExpired:
        # never hang the ladder: kill the route AND the Chrome it started (an orphaned Chrome keeps the profile locked)
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=30)
        else:
            proc.kill()
        try: proc.communicate(timeout=30)
        except Exception: pass
        log(f"  {route}: no answer within {limit} s (stopped); next rung"); return None
    p = subprocess.CompletedProcess(cmd, proc.returncode, out_s, err_s)
    line = next((l for l in reversed((p.stdout or "").splitlines()) if l.startswith("{")), "")
    try: res = json.loads(line)
    except ValueError: res = {"status": "failed", "note": ((p.stderr or p.stdout or "no output").strip().splitlines() or ["?"])[-1][:200]}
    if res.get("status") == "ok" and res.get("output") and Path(res["output"]).is_file():
        log(f"  {route}: done in {time.time() - t0:.0f}s" + (f" ({res['note'][:160]})" if res.get("note") else ""))
        return {"output": Path(res["output"]), "note": res.get("note", "")}
    note = str(res.get("note") or "")
    if any(k in note.lower() for k in ("login wall", "sign-in needed", "not installed", "no token", "signed out", "verify you are human")):
        _down[route] = note[:160]   # needs a person: don't retry it for every beat
    log(f"  {route}: {res.get('status', 'failed')} ({note[:200]}); next rung")
    return None


def known_person(sec, ents=()):
    """Why the describe -> Meta chain must not run ("" = it may): the beat is about a known, named person."""
    from .cloudgen import has_person
    if (sec.get("subject") or {}).get("kind") == "person": return "the beat's subject is a person"
    try:
        if has_person(str(sec.get("vo") or ""), ents): return "the narration names a real person"
    except Exception:
        pass
    return ""


def chain_rung(cfg, sd, sec, key, log, snapshot, aspect="16:9", ents=()):
    """Rung 3a (Tariq, 2026-11-06), for a beat with a source snapshot and no public media: Copilot describes the snapshot
    (people described as they look, never a rebuilt screen layout) -> Meta makes an image from it -> Meta animates THAT image.
    Never for a known person. -> {"video", "image", "prompt"} or None."""
    from . import media
    if not cfg.get("meta_chain_on", True) or not snapshot or not Path(snapshot).is_file(): return None
    # named people (owner, 2026-11-06): allowed by default - synthetic depictions of public figures are common on YouTube; the
    # clip is tagged GENERATED (burned in) and the Publisher answers YouTube's "Altered content" question with Yes for it
    named_ok = bool(cfg.get("meta_chain_named_people", True))
    why = "" if named_ok else known_person(sec, ents)
    if why:
        log(f"  {sec.get('id', key)}: describe -> Meta chain skipped ({why})"); return None
    if not (available(cfg, "r12") and available(cfg, "r13")): return None
    d = Path(sd) / "chain"; d.mkdir(parents=True, exist_ok=True)
    vid, img, txt = d / f"{key}.mp4", d / f"{key}.jpg", d / f"{key}.prompt.txt"
    if media.ok(vid) and img.is_file(): return {"video": vid, "image": img, "prompt": txt.read_text(encoding="utf-8") if txt.is_file() else ""}
    cap = int(cfg.get("meta_chain_max_per_video", 3))   # ~6 min each: a story with little public footage must not add an hour
    if len([x for x in d.glob("*.mp4") if media.ok(x)]) >= cap:
        log(f"  chain: {cap} snapshot clip(s) already made for this video; next rung"); return None
    if not txt.is_file():
        r = run(cfg, "r12", "describe", aspect, txt, log, image=snapshot, timeout=300)
        if not r:   # Copilot blocked (its human check) or failed: Meta describes the snapshot itself, in the chain's own chat
            log("  chain: Copilot gave no description; Meta describes the snapshot instead")
            r = run(cfg, "r13", "describe", aspect, vid, log, image=snapshot, timeout=720)
            if not r or not media.ok(vid): return None
            pf = routes_dir(cfg) / "output" / "r13_meta_chain.prompt.txt"
            prompt = pf.read_text(encoding="utf-8").strip() if pf.is_file() else ""
            if not named_ok and known_person({"vo": prompt}, ents):   # setting off: never this method for a named person
                log("  chain: Meta's description names a real person; clip not used"); vid.unlink(missing_ok=True); return None
            if prompt: txt.write_text(prompt, encoding="utf-8")
            src_img = routes_dir(cfg) / "output" / "r13_meta_chain.jpg"
            if src_img.is_file():
                import shutil
                shutil.copyfile(src_img, img)
            return {"video": vid, "image": img if img.is_file() else None, "prompt": prompt, "describer": "meta"}
    prompt = txt.read_text(encoding="utf-8").strip()
    try:
        if not named_ok and known_person({"vo": prompt}, ents):   # setting off: the describer named someone, not this method
            log("  chain: the description names a real person; skipped"); return None
    except Exception:
        pass
    from . import people
    ppl = people.names(sec.get("vo", ""), ents)
    if people.rebuilds_layout(prompt):   # a split screen / video call of strangers is not a scene (owner, 2026-11-07)
        log("  chain: the description rebuilds the show's screen layout, not a scene; next rung"); txt.unlink(missing_ok=True); return None
    prompt = people.scrub(prompt) + (" " + people.rule(ppl) if ppl else (" " + people.SNAP_RULE if people.shows_person(prompt) else ""))
    r = run(cfg, "r13", prompt, aspect, vid, log, timeout=600)
    if not r or not media.ok(vid): return None
    src_img = routes_dir(cfg) / "output" / "r13_meta_chain.jpg"   # the image Meta animated (saved by the route)
    if src_img.is_file():
        import shutil
        shutil.copyfile(src_img, img)
    return {"video": vid, "image": img if img.is_file() else None, "prompt": prompt}


def blender_rung(cfg, sd, sec, key, log, aspect="16:9"):
    """Rung 3b: a Blender scene (Media Routes r11: MCP, Poly Haven assets, Cycles) for a subject-locked beat the image services
    missed. Only a COMPLETE scene counts: a "partial" one (the subject had no model, e.g. an aircraft) drops to the next rung.
    -> clip path or None."""
    from . import media
    from .flow import visual_prompt
    if not cfg.get("blender_on", True) or not available(cfg, "r11"): return None
    d = Path(sd) / "blender"; d.mkdir(parents=True, exist_ok=True)
    out = d / f"{key}.mp4"
    if media.ok(out): return out
    if (d / f"{key}.partial").exists(): return None   # already tried for this beat
    r = run(cfg, "r11", visual_prompt(cfg, sec, log), aspect, out, log, timeout=int(cfg.get("media_routes_timeout", 900)))
    if not r: return None
    if "PARTIAL" in (r.get("note") or "").upper():
        log("  blender: partial scene (" + r["note"].split("PARTIAL", 1)[1][:120].strip(" -") + "); not used, next rung")
        (d / f"{key}.partial").write_text(r["note"], encoding="utf-8"); out.unlink(missing_ok=True)
        return None
    return out if media.ok(out) else None


def video_rung(cfg, sd, sec, key, log, aspect="16:9"):
    """Visual ladder rung 5 for a beat nothing above could fill: 5a Meta video (meta.ai, free) -> 5b Google Flow (paid credits,
    capped by flow_max_per_video). -> (clip path, tag, rung) or (None, None, None). Never raises (cancel aside)."""
    from . import media
    from .flow import visual_prompt
    d = Path(sd) / "flow"; d.mkdir(parents=True, exist_ok=True)
    prompt = None
    meta_cap = int(cfg.get("meta_video_max_per_video", 3))
    meta_made = len([x for x in d.glob("*_meta.mp4") if media.ok(x)])
    if cfg.get("meta_video_on", True) and available(cfg, "r7") and (meta_made < meta_cap or media.ok(d / f"{key}_meta.mp4")):
        out = d / f"{key}_meta.mp4"
        if media.ok(out): return out, "GENERATED · META", "meta video"
        prompt = prompt or visual_prompt(cfg, sec, log)
        r = run(cfg, "r7", prompt, aspect, out, log, timeout=600)
        if r and media.ok(out): return out, "GENERATED · META", "meta video"
    if cfg.get("flow_on", True):
        out = d / f"{key}.mp4"
        if media.ok(out): return out, "GENERATED · FLOW", "flow"
        if cfg.get("flow_via_routes", True) and available(cfg, "r8"):
            cap = int(cfg.get("flow_max_per_video", 1))
            made = [x for x in d.glob("*.mp4") if not x.stem.endswith("_meta")]
            if len(made) >= cap:
                log(f"  flow: {cap} clip(s) already made for this video; next rung"); return None, None, None
            prompt = prompt or visual_prompt(cfg, sec, log)
            r = run(cfg, "r8", prompt, aspect, out, log, timeout=int(cfg.get("flow_timeout", 480)) + 240)
            if r and media.ok(out):
                log(f"  flow: {r.get('note', '')[-80:]}")
                return out, "GENERATED · FLOW", "flow"
        else:
            from . import flow
            clip = flow.generate(cfg, sd, sec, key, log, aspect=aspect)
            if clip: return clip, "GENERATED · FLOW", "flow"
    return None, None, None
