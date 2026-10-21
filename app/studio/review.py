"""Visual review for Shorts: every beat's available treatments (stock, real photo, AI still, animation, parallax, reconstruction,
headline card, your own file) as candidates, with the pipeline's auto-pick as the default.

Auto mode pauses only when a beat is uncertain; Review every beat pauses always (and the ladder ran every treatment).
State lives in short/review/review.json, so a paused job survives restarts:
  {"mode", "status": "open"|"closed", "next": n,
   "beats": {bid: {"vo", "secs", "auto": [cid], "cands": [cid], "decision": None|"auto"|"chosen"|"skip", "chosen": [cid],
                   "skip_item", "uncertain", "why", "history": [{"label", "cands"}], "busy", "msg", "notes": [...]}},
   "cands": {cid: {"id", "beat", "rung", "ok", "why", "item", "thumb", "worst", "secs", "key"}}}
Thumbnails are coarse stills; 2-second previews (the middle of the treatment) are rendered only when clicked."""
import json, re, shutil, subprocess, threading, time
from pathlib import Path
from . import media

FPS = 30
RUNG = {"source": "Source evidence + commentary", "own": "Your footage", "stock": "Stock footage", "photo": "Real photo", "cloud": "Cloud still", "illustration": "Illustration", "silhouette": "Silhouette", "simulation": "Simulation", "still": "AI still", "animate": "AI animation", "parallax": "Parallax",
        "reconstruction": "3D reconstruction", "headline": "Headline card", "map": "Map", "supplied": "Your file", "parallax (fill)": "Parallax",
        "graphics": "Remotion graphics", "capcut": "CapCut",
        "imagegen": "Generated image (Gemini)", "flow": "Google Flow"}
STATIC = {"still", "headline", "photo"}          # click enlarges instead of playing
_locks, _gpu = {}, threading.Lock()

def _p(job): sd = Path(job) / "short"; return sd, sd / "review"
def _sp(sd):
    from .ladder import space
    return space(sd)
def _fsize(sd): sp = _sp(sd); return (sp["w"], sp["h"])
def _tsize(sd): w, h = _fsize(sd); return (270, 480) if h > w else (480, 270)
def _lock(job): return _locks.setdefault(str(job), threading.RLock())

def load(job):
    f = _p(job)[1] / "review.json"
    try: return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
    except Exception: return None

def save(job, rv):
    rd = _p(job)[1]; rd.mkdir(parents=True, exist_ok=True)
    tmp = rd / "review.json.tmp"; tmp.write_text(json.dumps(rv, indent=1), encoding="utf-8"); tmp.replace(rd / "review.json")

def _rel(p, sd): return str(Path(p).resolve().relative_to(Path(sd).resolve())).replace("\\", "/")

def _key(it):
    t = it["type"]
    if t in ("stock", "stock_rejected"): return "stock:" + str(it["clip"]["id"])
    if t in ("image", "video"): return t + ":" + it["src"]
    if t == "layers": return "layers:" + it["layers"][0]
    return "g:" + json.dumps(it.get("g"), sort_keys=True)

def _add(rv, bid, item, rung, ok, why, **extra):
    """Add a candidate to a beat's current set (or update the existing one with the same media). -> cid"""
    k = _key(item); b = rv["beats"][bid]
    for cid in b["cands"]:
        c = rv["cands"][cid]
        if c["key"] == k:
            if extra.get("auto"): c["ok"], c["why"] = ok, why
            return cid
    cid = f"c{rv['next']}"; rv["next"] += 1
    rv["cands"][cid] = {"id": cid, "beat": bid, "rung": rung, "ok": bool(ok), "why": str(why or "")[:160], "item": item, "key": k, "thumb": "",
                        "worst": extra.get("worst", 0), "secs": extra.get("secs") or item.get("secs") or 0}
    b["cands"].append(cid); return cid

def _skip_item(sec):
    bd = sec.get("backdrop") or {}
    g = bd if bd.get("kind") == "headline" else {"kind": "headline", "kicker": "", "text": sec["vo"][:70], "sub": ""}
    return {"type": "graphic", "g": g, "rung": "headline"}

# ---------------------------------------------------------------- candidates from what the pipeline made
def _slot_cands(rv, sec, key, r, sd, full, log):
    """Candidates from one ladder slot: the still, its animation, its parallax."""
    from . import short, depth
    bid = sec["id"]; fd = sd / "fallback"
    cloud = r.get("src") == "cloud"; gtag = "GENERATED · CLOUD" if cloud else "GENERATED"
    if r.get("cloud") and not cloud and (sd / r["cloud"]).exists():   # a cloud still that failed its check: still offered to the reviewer
        pre = fd / f"{key}_cloudx"
        lay = [Path(f"{pre}_L0.jpg")] if Path(f"{pre}_L0.jpg").exists() else short.depth_free(sd / r["cloud"], pre, _fsize(sd))
        _add(rv, bid, {"type": "layers", "layers": [_rel(p, sd) for p in lay], "tag": "GENERATED · CLOUD"}, "cloud", False,
             f"cloud still ({r.get('cloud_provider')}): {r.get('cloud_why') or 'failed its check'}")
    if r.get("still") and (sd / r["still"]).exists():
        img = sd / r["still"]
        pre = fd / f"{key}_still"
        lay = [Path(f"{pre}_L0.jpg")] if Path(f"{pre}_L0.jpg").exists() else short.depth_free(img, pre, _fsize(sd))
        _add(rv, bid, {"type": "layers", "layers": [_rel(p, sd) for p in lay], "tag": gtag}, "cloud" if cloud else "still", r.get("still_ok"),
             "matches the narration" if r.get("still_ok") else (r.get("still_why") or "not checked"))
        if r.get("clip") and (sd / r["clip"]).exists():
            _add(rv, bid, {"type": "video", "src": r["clip"], "secs": round((r.get("clip_secs") or 7) / 0.85, 2), "tag": "GENERATED"}, "animate",
                 r.get("clip_ok"), "matches the narration, no garbling" if r.get("clip_ok") else (r.get("clip_why") or "not checked"),
                 worst=(0 if r.get("clip_ok") else r.get("clip_worst", 2)), secs=round((r.get("clip_secs") or 7) / 0.85, 2))
        par = Path(f"{fd / key}_L0.jpg")
        if not par.exists() and full:
            try: depth.layers(img, fd / key, log, size=_fsize(sd))
            except Exception as e: log(f"  parallax for {key} failed ({str(e)[:80]})")
        if par.exists():
            lays = [par] + [Path(f"{fd / key}_L{i}.png") for i in (1, 2) if Path(f"{fd / key}_L{i}.png").exists()]
            _add(rv, bid, {"type": "layers", "layers": [_rel(p, sd) for p in lays], "tag": "GENERATED · CLOUD" if cloud else "GENERATED · PARALLAX"},
                 "parallax", r.get("still_ok"),
                 f"depth layers of the {'cloud' if cloud else 'AI'} still" + ("" if r.get("still_ok") else f" (still: {r.get('still_why') or 'not checked'})"))

def _cheap_cands(rv, sec, job, phases, cfg=None):
    """Treatments that cost nothing to offer: the map (if the script has one) and the reconstruction / headline card.
    Ladder v2 has no reconstruction rung, so it isn't offered there."""
    from . import coherence
    bid = sec["id"]; bd = sec.get("backdrop") or {}
    if bd.get("kind") == "map": _add(rv, bid, {"type": "graphic", "g": bd}, "map", True, "the route / places in this beat")
    ef = Path(job) / "entities.json"; ents = json.loads(ef.read_text(encoding="utf-8")) if ef.exists() else []
    from . import illustrate
    for it in illustrate.variants(sec, ents, phases.get(bid)):   # flat illustration / silhouette (each aircraft named): free, CPU only
        g = it["g"]; what = f"flat {g['scene']} illustration" + (f" ({g['aircraft']})" if g.get("aircraft") else "") if g["kind"] == "illustration" else f"{g['shape']} silhouette against the sky"
        _add(rv, bid, {"type": "graphic", "g": g, "tag": it["tag"]}, it["rung"], True, what)
    if sec.get("subject") and not (cfg or {}).get("ladder_v2"):
        cap = bd.get("text", "") if bd.get("kind") == "headline" else bd.get("title", "")
        _add(rv, bid, {"type": "graphic", "g": coherence.recon(sec["subject"], ents, sec["vo"], 0, cap, moment=phases.get(bid, ""))},
             "reconstruction", True, "3D reconstruction from the narration")
    _add(rv, bid, _skip_item(sec), "headline", True, "text card summing up the beat")

def _capcut_pending(job):
    from . import capcut
    return capcut.pending(job)

def _stock_cands(rv, sec, picked, rejected, story_subjects, auto=False):
    out = []
    for c in picked:
        if c.get("own"):   # your own footage, placed by the clip matcher (clips.py)
            out.append(_add(rv, sec["id"], {"type": "stock", "clip": c, "tag": ""}, "own", True, str(c.get("seen") or "your clip")[:100], auto=auto)); continue
        out.append(_add(rv, sec["id"], {"type": "stock", "clip": c, "tag": "ILLUSTRATIVE" if story_subjects else ""}, "stock", True,
                        "matches the narration: " + str(c.get("seen") or c.get("desc") or "")[:80], auto=auto))
    for r in rejected:
        c = r.get("clip") or {"id": r["id"], "src": r.get("src", ""), "desc": r.get("desc", "")}
        _add(rv, sec["id"], {"type": "stock_rejected", "clip": c, "sheet": r.get("sheet", ""), "tag": "ILLUSTRATIVE" if story_subjects else ""},
             "stock", False, r.get("why", "rejected"))
    return out

def collect(job, plan, cfg, log, mode="auto", debug_beats=None):
    """Build/refresh review.json after short_fallback. -> (rv, pause?)
    debug_beats: a debugger pause mid-run: only these beats, every cheap treatment plus the rejected real photos, no auto decisions,
    no thumbnails (the panel makes them on request), never pauses by itself."""
    from . import short, coherence
    job = Path(job); sd, rd = _p(job); rd.mkdir(parents=True, exist_ok=True)
    with _lock(job):
        rv = load(job)
        if rv and rv.get("status") == "closed": return rv, False
        rv = rv or {"mode": mode, "status": "open", "next": 1, "beats": {}, "cands": {}}
        rv["mode"] = mode
        tm = json.loads((sd / "timings.json").read_text(encoding="utf-8"))
        pick = json.loads((sd / "stock" / "pick.json").read_text(encoding="utf-8"))
        ff = sd / "fallback.json"; fallback = json.loads(ff.read_text(encoding="utf-8")) if ff.exists() else {}
        lf = sd / "fallback" / "ladder.json"; lad = json.loads(lf.read_text(encoding="utf-8")) if lf.exists() else {}
        fs = sd / "stock" / "footage.json"; fst = json.loads(fs.read_text(encoding="utf-8")) if fs.exists() else {}
        ef = job / "entities.json"
        story_subjects = any(e.get("kind") != "person" for e in (json.loads(ef.read_text(encoding="utf-8")) if ef.exists() else []))
        phases = coherence.beat_phases([x for x in plan["sections"] if not x.get("cta")])
        full = mode == "every"
        dbg_ch = {}
        if debug_beats is not None:
            from . import debug as _dbg
            dbg_ch = _dbg.chains(job)
        for sec in plan["sections"]:
            bid = sec["id"]
            if sec.get("cta") or bid not in tm: continue
            if debug_beats is not None and bid not in debug_beats: continue
            d = tm[bid]["dur"] + short.GAP
            b = rv["beats"].setdefault(bid, {"vo": sec["vo"], "secs": round(d, 2), "auto": [], "cands": [], "decision": None, "chosen": [],
                                             "uncertain": False, "why": "", "history": [], "busy": "", "msg": "", "notes": []})
            b["vo"] = sec["vo"]; b["skip_item"] = _skip_item(sec)
            clips = [c for c in pick.get(bid, []) if short._clip_len(sd, c) > 0]
            covered = sum(short._clip_len(sd, c) / 0.85 for c in clips) >= d - 0.5
            auto = _stock_cands(rv, sec, clips, [], story_subjects, auto=True)
            if not covered:
                for it in fallback.get(bid, []):
                    it = dict(it)
                    rung = it.get("rung") or ("photo" if it["type"] == "image" else "headline")
                    auto.append(_add(rv, bid, it, "parallax" if rung == "parallax (fill)" else rung, True, "pipeline pick", auto=True))
            _stock_cands(rv, sec, [], fst.get("rejected", {}).get(bid, []), story_subjects)
            slots = {k: r for k, r in lad.items() if k.rsplit("_", 1)[0] == bid}
            for k, r in slots.items(): _slot_cands(rv, sec, k, r, sd, full, log)
            if full or debug_beats is not None: _cheap_cands(rv, sec, job, phases, cfg)
            for pr in dbg_ch.get(bid, {}).get("photos_rejected", []):   # the debugger shows rejected real photos too
                if pr.get("path") and Path(pr["path"]).exists():
                    _add(rv, bid, {"type": "image", "src": _rel(pr["path"], sd), "fit": "frame", "tag": "FILE", "photo": pr.get("id")}, "photo", False,
                         pr.get("why", "rejected"))
            b["auto"] = auto
            # uncertain: the check couldn't judge, or every generated option failed and the beat fell back to the last resort
            why = []
            if any("unavailable" in str(r.get("still_why", "")) + str(r.get("clip_why", "")) for r in slots.values()): why.append("the coherence check couldn't run")
            rungs = [rv["cands"][c]["rung"] for c in auto]
            if dbg_ch.get(bid, {}).get("capcut") == "pending" or bid in _capcut_pending(job): why.append("graphics hard-failed: CapCut will cover this beat after the render")
            if not covered and any(x in ("reconstruction", "headline") for x in rungs) and any(r.get("still") and not r.get("still_ok") for r in slots.values()):
                why.append("the AI still failed the check, so it fell back to " + ", ".join(sorted({RUNG.get(x, x).lower() for x in rungs if x in ('reconstruction', 'headline')})))
            if not auto: why.append("no visual found")
            b["uncertain"], b["why"] = bool(why), "; ".join(why)
            if mode == "auto" and not why and not b["decision"] and debug_beats is None: b["decision"] = "auto"
            if mode == "never" and not b["decision"] and debug_beats is None:   # decide on my own, never pause
                b["decision"] = "auto" if auto else "skip"   # nothing usable at all: the beat's headline card
                if why:
                    b["msg"] = f"Decided without pausing: {'used the pipeline pick' if auto else 'used the headline card'} ({'; '.join(why)})."
                    log(f"  {bid}: unsure ({'; '.join(why)}) - decided on my own: {'pipeline pick' if auto else 'headline card'}")
        pause = any(not b["decision"] for b in rv["beats"].values()) and debug_beats is None
        save(job, rv)
    if pause:
        n = sum(1 for b in rv["beats"].values() if b["uncertain"])
        log(f"Visual review: {len(rv['beats'])} beat(s), {len(rv['cands'])} treatment(s)" + (f", {n} uncertain" if n else ""))
        thumbs(job, cfg, log)
    return rv, pause

# ---------------------------------------------------------------- thumbnails and previews
def _card(text, sub, out, size=(270, 480)):
    from PIL import Image, ImageDraw
    from .photos import _font
    k = min(size) / 270
    im = Image.new("RGB", size, (14, 20, 32)); dr = ImageDraw.Draw(im)
    f1, f2 = _font(int(16 * k), True), _font(int(13 * k))
    dr.text((14 * k, 16 * k), sub.upper()[:28], font=f2, fill=(245, 165, 36))
    words, lines, cur = str(text).split(), [], ""
    for w in words:
        if len(cur) + len(w) > 20: lines.append(cur); cur = w
        else: cur = (cur + " " + w).strip()
    if cur: lines.append(cur)
    for i, ln in enumerate(lines[:9]): dr.text((14 * k, (60 + i * 24) * k), ln, font=f1, fill=(230, 237, 243))
    im.save(out, quality=85)

def _cover(src, out, size=(270, 480), crop=None):
    from PIL import Image
    im = Image.open(src).convert("RGB")
    if crop: im = im.crop(crop)
    W, H = size; r = max(W / im.width, H / im.height)
    im = im.resize((max(1, int(im.width * r + 0.5)), max(1, int(im.height * r + 0.5))))
    x0, y0 = (im.width - W) // 2, (im.height - H) // 2
    im.crop((x0, y0, x0 + W, y0 + H)).save(out, quality=85)

def _contain(src, out, size=(270, 480)):
    from PIL import Image
    im = Image.open(src).convert("RGB"); im.thumbnail(size)
    bg = Image.new("RGB", size, (0, 0, 0)); bg.paste(im, ((size[0] - im.width) // 2, (size[1] - im.height) // 2)); bg.save(out, quality=85)

def _frame(src, t, out, w=540):
    media.ff("-ss", f"{max(0.0, t):.2f}", "-i", src, "-frames:v", 1, "-vf", f"scale={w}:-2", out)

_bundle_lock = threading.Lock()

def _bundle(log):
    """One pre-built Remotion bundle for all previews (rebuilt when remotion/src changes): bundling is most of a render's
    start-up time, and previews load their media over http from Video Studio itself, so no per-job public dir is needed."""
    from . import short, config
    rdir = short._ensure_remotion(log); out = rdir / "_preview_bundle"; stamp = out / "_src_mtime.txt"
    newest = str(max(f.stat().st_mtime for f in (rdir / "src").rglob("*") if f.is_file() and "gen" not in f.relative_to(rdir / "src").parts[:1]))   # src/gen: temporary v2 components
    with _bundle_lock:
        if not (stamp.exists() and stamp.read_text() == newest):
            log("  preparing the preview renderer (once after each update)...")
            p = subprocess.run([short._npx(), "remotion", "bundle", "src/Root.tsx", f"--out-dir={out}", "--log=error"], cwd=rdir,
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
            if p.returncode != 0: raise RuntimeError("preview bundle failed: " + (p.stdout + p.stderr).strip()[-300:])
            stamp.write_text(newest)
    return rdir, out

def files_url(path):
    """http URL (Video Studio's /files/<job>/<path>) for a file inside a job folder."""
    import os
    from . import config
    rel = Path(path).resolve().relative_to(Path(config.load()["jobs_dir"]).resolve()).as_posix()
    return f"http://127.0.0.1:{os.environ.get('PORT') or 42020}/files/{rel}"

def _urlify(bg, sd):
    """Media paths (relative to the workspace's short folder) -> http URLs served by Video Studio."""
    base = files_url(sd) + "/"
    bg = json.loads(json.dumps(bg))
    if bg.get("src"): bg["src"] = base + bg["src"]
    if bg.get("layers"): bg["layers"] = [base + x for x in bg["layers"]]
    return bg

def _remotion(sd, bg, secs, out, cfg, log, frame=None, frames=None, scale=0.25, crf=26, timeout=900):
    from . import short
    rdir, bundle = _bundle(log); out = Path(out); out.parent.mkdir(parents=True, exist_ok=True)
    w, h = _fsize(sd)
    pf = out.with_name(out.stem + "_props.json"); pf.write_text(json.dumps({"bg": _urlify(bg, sd), "secs": secs, "w": w, "h": h}), encoding="utf-8")
    cmd = [short._npx(), "remotion", "still" if frame is not None else "render", str(bundle), "ShotPreview", str(out), f"--props={pf}",
           f"--gl={short._gl(cfg)}", f"--scale={scale}", "--log=error"]
    cmd += [f"--frame={frame}"] if frame is not None else [f"--frames={frames[0]}-{frames[1]}", f"--crf={crf}", "--concurrency=2"]
    for attempt in range(2):
        p = subprocess.run(cmd, cwd=rdir, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        if p.returncode == 0 and out.exists(): break
        if short.BROWSER_FLAKE not in (p.stdout + p.stderr): break
        time.sleep(5)
    try: pf.unlink()
    except Exception: pass
    if p.returncode != 0 or not out.exists(): raise RuntimeError(" / ".join((p.stdout + p.stderr).strip().splitlines()[-3:])[:300])
    return out

def _thumb(job, c, cfg, log):
    sd, rd = _p(job); td = rd / "thumbs"; td.mkdir(parents=True, exist_ok=True); ts = _tsize(sd)
    out = td / f"{c['id']}.jpg"
    if out.exists(): return _rel(out, sd)
    it = c["item"]; t = it["type"]
    try:
        if t == "stock":
            src = sd / "stock" / "clips" / f"{it['clip']['id']}.mp4"; _frame(src, media.dur(src) / 2, out.with_suffix(".tmp.jpg"))
            _cover(out.with_suffix(".tmp.jpg"), out, ts); out.with_suffix(".tmp.jpg").unlink()
        elif t == "stock_rejected": _contain(it["sheet"], out, ts)
        elif t == "video":
            src = sd / it["src"]; D = media.dur(src)
            tt = D * c["worst"] / 4 if c.get("worst") else D / 2   # garbled: the frame the check judged worst
            _frame(src, tt, out.with_suffix(".tmp.jpg")); _cover(out.with_suffix(".tmp.jpg"), out, ts); out.with_suffix(".tmp.jpg").unlink()
        elif t == "image": _contain(sd / it["src"], out, ts) if it.get("fit") == "frame" else _cover(sd / it["src"], out, ts)
        elif t == "layers": _cover(sd / it["layers"][0], out, ts)
        elif t == "graphic" and it["g"].get("kind") in ("recon", "illustration", "silhouette", "sim", "simmap", "motion", "tpl"):
            _remotion(sd, it, 6, out, cfg, log, frame=FPS * 3, scale=0.25)
        elif t == "graphic" and it["g"].get("kind") == "map":
            _card(it["g"].get("title") or "Map", "map: " + ", ".join(p["name"] for p in it["g"].get("points", []))[:28], out)
        else:
            g = it.get("g", {}); _card(g.get("text", ""), g.get("kicker") or "headline card", out, ts)
    except Exception as e:
        log(f"  thumbnail for {c['id']} ({c['rung']}) failed ({str(e)[:100]}); using a text card")
        _card(c["why"], RUNG.get(c["rung"], c["rung"]), out, ts)
    return _rel(out, sd)

def thumbs(job, cfg, log, cids=None):
    with _lock(job): rv = load(job)
    todo = [c for c in rv["cands"].values() if not c.get("thumb") and (cids is None or c["id"] in cids)]
    done = {c["id"]: _thumb(job, c, cfg, log) for c in todo}
    with _lock(job):
        rv = load(job)
        for cid, th in done.items(): rv["cands"][cid]["thumb"] = th
        save(job, rv)

def preview(job, cid, cfg, log):
    """-> {"video": rel} (2 s from the middle of the treatment) or {"image": rel} for static ones. Rendered once, then cached."""
    sd, rd = _p(job); rv = load(job); c = rv["cands"][cid]; it = c["item"]; t = it["type"]
    pd = rd / "previews"; pd.mkdir(parents=True, exist_ok=True)
    out = pd / f"{cid}.mp4"
    if c["rung"] in STATIC or (t == "graphic" and it["g"].get("kind") in ("headline",)):
        src = sd / (it["src"] if t == "image" else it["layers"][0] if t == "layers" else c["thumb"])
        if t == "graphic":   # a headline card: drawn larger here (no renderer needed for a static card)
            big = pd / f"{cid}.jpg"; g = it.get("g", {})
            if not big.exists(): _card(g.get("text", ""), g.get("kicker") or "headline card", big, size=tuple(2 * x for x in _tsize(sd)))
            src = big
        return {"image": _rel(src, sd)}
    if out.exists(): return {"video": _rel(out, sd)}
    if t == "stock_rejected":
        _ensure_clip(job, cid, cfg, log); rv = load(job); c = rv["cands"][cid]; it = c["item"]; t = it["type"]
    if t in ("stock", "video"):
        src = sd / "stock" / "clips" / f"{it['clip']['id']}.mp4" if t == "stock" else sd / it["src"]
        D = media.dur(src); a = max(0.0, D / 2 - 1.0)
        media.ff("-ss", f"{a:.2f}", "-t", "2", "-i", src, "-vf", "scale=360:-2", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", 28, out)
    else:
        secs = c.get("secs") or 7.0; mid = int(secs * FPS / 2)
        _remotion(sd, it, secs, out, cfg, log, frames=(max(0, mid - FPS), mid + FPS - 1), scale=0.5)
    return {"video": _rel(out, sd)}

def _ensure_clip(job, cid, cfg, log):
    """A stock clip the check rejected is only a contact sheet; download it when it's previewed or chosen."""
    from . import footage
    sd, _ = _p(job)
    with _lock(job):
        rv = load(job); c = rv["cands"][cid]
        if c["item"]["type"] != "stock_rejected": return
        clip = c["item"]["clip"]
    if not clip.get("file"): raise RuntimeError("this rejected clip can't be downloaded (no file link was kept)")
    footage.fetch(clip, sd / "stock" / "clips" / f"{clip['id']}.mp4", 10.0)
    with _lock(job):
        rv = load(job); c = rv["cands"][cid]
        c["item"] = {"type": "stock", "clip": clip, "tag": c["item"].get("tag", "")}; save(job, rv)

# ---------------------------------------------------------------- decisions
def decide(job, bid, action, cids=None, cfg=None, log=print):
    if action == "choose":
        for cid in cids or []:
            if (load(job)["cands"][cid]["item"]["type"]) == "stock_rejected": _ensure_clip(job, cid, cfg, log)
    with _lock(job):
        rv = load(job); b = rv["beats"][bid]
        if action == "auto": b["decision"], b["chosen"] = "auto", []
        elif action == "skip": b["decision"], b["chosen"] = "skip", []
        elif action == "choose":
            if not cids: raise ValueError("pick at least one treatment")
            b["decision"], b["chosen"] = "chosen", [c for c in cids if c in rv["cands"]]
        elif action == "undo": b["decision"], b["chosen"] = None, []
        elif action == "revert":
            i = int(cids)
            h = b["history"].pop(i); b["history"].append({"label": "before revert", "cands": b["cands"]}); b["cands"] = h["cands"]
        save(job, rv); return rv

def approve_all(job):
    with _lock(job):
        rv = load(job)
        for b in rv["beats"].values():
            if not b["decision"]: b["decision"] = "auto"
        save(job, rv); return rv

def close(job):
    with _lock(job):
        rv = load(job)
        if any(not b["decision"] for b in rv["beats"].values()): raise ValueError("some beats still need a decision")
        rv["status"] = "closed"; save(job, rv); return rv

def final_items(rv, sec):
    b = (rv or {}).get("beats", {}).get(sec["id"])
    if not b or rv.get("status") != "closed": return None
    if b["decision"] == "skip": return [b.get("skip_item") or _skip_item(sec)]
    if b["decision"] == "chosen" and b["chosen"]: return [rv["cands"][c]["item"] for c in b["chosen"] if rv["cands"][c]["item"]["type"] != "stock_rejected"] or None
    return None

# ---------------------------------------------------------------- your own file / URL
VIDEO_EXT = (".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi")

def _vsize(p):
    import subprocess
    o = subprocess.run([media._bin("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(p)],
                       capture_output=True, text=True).stdout.strip().split("\n")[0]
    try: w, h = (int(x) for x in o.strip(",").split("x")[:2]); return w, h
    except Exception: return 1920, 1080

def supply(job, bid, src, tag, cfg, log):
    import requests
    from PIL import Image
    from . import short
    sd, rd = _p(job); sup = rd / "supplied"; sup.mkdir(parents=True, exist_ok=True)
    src = src.strip().strip('"').strip("'")
    n = len(list(sup.glob(f"sup_{bid}_*.*"))) + 1
    if re.match(r"https?://", src, re.I):
        r = requests.get(src, timeout=90, headers={"User-Agent": "VideoStudio/1.0"})
        if r.status_code != 200: raise RuntimeError(f"download failed (HTTP {r.status_code})")
        ct = r.headers.get("content-type", "")
        ext = Path(src.split("?")[0]).suffix.lower() or (".mp4" if "video" in ct else ".jpg")
        if "text/html" in ct: raise RuntimeError("that link is a web page, not an image or video file (copy the image/video address instead)")
        raw = sup / f"sup_{bid}_{n}_raw{ext}"; raw.write_bytes(r.content)
    else:
        p = Path(src)
        if not p.exists(): raise RuntimeError(f"file not found on this PC: {src}")
        raw = sup / f"sup_{bid}_{n}_raw{p.suffix.lower()}"; shutil.copy2(p, raw)
    tag = tag if tag in ("", "FILE", "ILLUSTRATIVE", "GENERATED", "RECONSTRUCTION") else ""
    # fit-and-render (default for your own media): the file is used as it is - no vision check, no AI animation, no substitute,
    # no rejection, no automatic pan / zoom / parallax. edit.layout fits it to the beat mechanically (trim, loop, freeze, speed,
    # segment) and Remotion renders it. Labelled YOUR FOOTAGE (video) / FILE (picture) unless you picked another label.
    W, H = _fsize(sd)
    if raw.suffix.lower() in VIDEO_EXT:
        out = sup / f"sup_{bid}_{n}.mp4"
        vw, vh = _vsize(raw)
        same = (vw > vh) == (W > H)
        vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}" if same else "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2"
        media.ff("-i", raw, "-t", 180, "-vf", vf + ",fps=30,format=yuv420p", "-an", "-c:v", "libx264", "-crf", 18, "-bf", 0, "-g", 30, out, timeout=1800)   # no B-frames, a keyframe a second: Remotion seeks it frame-exactly at any speed
        item = {"type": "video", "src": _rel(out, sd), "secs": round(media.dur(out), 2), "tag": tag or "YOUR FOOTAGE", "rate": 1.0, "user": True,
                **({} if same else {"fit": "frame"})}   # other orientation: shown whole over a blurred copy
    else:
        im = Image.open(raw).convert("RGB"); out = sup / f"sup_{bid}_{n}.jpg"; im.save(out, quality=93)
        item = {"type": "image", "src": _rel(out, sd), "fit": "frame" if (im.width > im.height) != (W > H) else "still", "tag": tag or "FILE", "user": True}
    try: raw.unlink()
    except Exception: pass
    with _lock(job):
        rv = load(job); cid = _add(rv, bid, item, "supplied", True, "your file: " + Path(src).name[:60])
        b = rv["beats"][bid]; b["decision"], b["chosen"] = "chosen", [cid]; b["msg"] = f"Added your file and selected it ({RUNG['supplied']}: fitted to the beat as it is, no AI changes)."
        save(job, rv)
    thumbs(job, cfg, log, [cid]); return cid

# ---------------------------------------------------------------- GPU work for one beat: show all options / refine
REFINE = """You help an editor fix the visuals of ONE beat of a news YouTube Short.
Narration of the beat: "{vo}"
Subject of the beat: {subject}
Current AI image prompt: "{still}"
Current animation prompt: "{motion}"
Current stock-footage searches: {queries}
The editor says: "{text}"

Decide what the editor wants:
- "descriptive": they describe what the picture should show -> new prompts and searches that show exactly that.
- "correction": they point out something wrong (e.g. "the plane is nose-up but should be diving") -> keep what was right, fix exactly what they say.
- "supply": they give a file path or a URL of their own picture or clip to use.
Image prompt rules (30-50 words, photorealistic, vertical framing): the subject, setting, mood and the exact moment. NEVER ask for any
text, letters, numbers, logos, brand or airline names, livery lettering, flags, registrations, signs or real people's faces; describe a
branded subject by type, shape and colours only. Stock searches: 3-5 words each, subject + action + setting, no brand names unless the
beat has a subject.
Reply with ONLY JSON: {{"intent": "descriptive|correction|supply", "understood": "one short sentence: what you will change",
"still_prompt": "...", "motion": "8-15 words: how things move and how the camera moves", "queries": ["...", "..."], "supply": "path or URL (supply only)"}}"""

def _section(job, bid):
    from .pipeline import Job
    sp = Job(job).short_plan(); return sp, next(s for s in sp["sections"] if s["id"] == bid)

def _busy(job, bid, msg):
    with _lock(job):
        rv = load(job); rv["beats"][bid]["busy"] = msg; save(job, rv)

def start(studio, jid, bid, kind, payload=None, ws=None):
    """Run 'expand' (show all options) or 'refine' for one beat in the background. -> error text or ''"""
    if studio.current: return "Another job is using the GPU right now; try again when it has finished."
    if not _gpu.acquire(blocking=False): return "Already generating options for a beat; wait for it to finish."
    job = ws or studio.job(jid).dir
    _busy(job, bid, {"expand": "Generating options...", "animate": "Animating (several minutes)...", "more_stock": "Searching more stock footage..."}.get(kind, "Working on your instruction..."))
    def run():
        log = studio.job(jid).log
        try:
            from . import config
            from .wangp import WanGP
            cfg = config.load(); wg = WanGP(cfg)
            {"expand": expand, "refine": refine, "animate": add_animation, "more_stock": more_stock}[kind](job, bid, cfg, wg, log, payload or {})
        except Exception as e:
            log(f"  {bid}: {kind} failed: {str(e)[:300]}")
            with _lock(job):
                rv = load(job); rv["beats"][bid]["msg"] = f"Failed: {str(e)[:200]}"; save(job, rv)
        finally:
            _busy(job, bid, ""); _gpu.release()
    threading.Thread(target=run, daemon=True).start(); return ""

def _run_slots(job, sec, keys, cfg, wg, log, prompt=None, motion=None, animate=False):
    from . import ladder
    sd, _ = _p(job)
    slots = [{"key": k, "beat": sec["id"], "vo": sec["vo"], "still_prompt": prompt or sec.get("still_prompt", ""),
              "motion": motion if motion is not None else sec.get("motion", ""), "subject": sec.get("subject")} for k in keys]
    gpu = wg.alive()
    if not gpu: log("  WanGP isn't reachable: no AI stills or animations")
    return ladder.run(cfg, wg, sd, sd / "fallback", slots, log, lambda: False, gpu, seed=7000 + int(time.time()) % 1000, full=True, animate=animate)

def _extra_stock(job, sec, queries, tag, cfg, log, n=2):
    from . import footage
    sd, rd = _p(job); sf = rd / f"stock_{sec['id']}_{tag}.json"
    slot = {"id": sec["id"], "text": sec["vo"], "queries": queries, "avoid": sec.get("avoid") or []}
    picked = footage.fill(cfg, [slot], _sp(sd)["orient"], {sec["id"]: n}, sd / "stock", log, lambda: False, want_long_side=2560, max_secs=10.0,
                          state_file=sf, fallback=True)
    st = json.loads(sf.read_text(encoding="utf-8")) if sf.exists() else {}
    return picked.get(sec["id"], []), st.get("rejected", {}).get(sec["id"], [])

def _story_subjects(job):
    ef = Path(job) / "entities.json"
    return any(e.get("kind") != "person" for e in (json.loads(ef.read_text(encoding="utf-8")) if ef.exists() else []))

def expand(job, bid, cfg, wg, log, payload):
    """Show all options for this beat: generate the treatments the ladder didn't get to."""
    from . import coherence, photos
    sd, rd = _p(job); sp, sec = _section(job, bid)
    lf = sd / "fallback" / "ladder.json"; lad = json.loads(lf.read_text(encoding="utf-8")) if lf.exists() else {}
    keys = [k for k in lad if k.rsplit("_", 1)[0] == bid] or [f"{bid}_9"]
    log(f"{bid}: generating all treatments (slots {', '.join(keys)})")
    st = _run_slots(job, sec, keys[:1] if not any(lad.get(k, {}).get("still") for k in keys) else keys, cfg, wg, log, animate=True)
    with _lock(job): rv = load(job); have = {rv["cands"][c]["rung"] for c in rv["beats"][bid]["cands"]}
    picked, rejected, pics = [], [], []
    if not sec.get("subject") and "stock" not in have:
        try: picked, rejected = _extra_stock(job, sec, sec.get("queries") or [], "x", cfg, log)
        except Exception as e: log(f"  stock search failed ({str(e)[:100]})")
    if sec.get("subject") and "photo" not in have:
        try: pics = photos.find(cfg, sec["subject"], sd / "photos", log, want=10)
        except Exception as e: log(f"  photo search failed ({str(e)[:100]})")
    phases = coherence.beat_phases([x for x in sp["sections"] if not x.get("cta")])
    with _lock(job):
        rv = load(job)
        for k in keys:
            if k in st: _slot_cands(rv, sec, k, st[k], sd, True, log)
        _stock_cands(rv, sec, picked, rejected, _story_subjects(job))
        for pc in pics:
            dst = sd / "fallback" / f"{pc['id']}.jpg"
            if not dst.exists(): shutil.copy2(pc["path"], dst)
            ok = coherence.phase_ok(phases.get(bid, ""), pc.get("phase"))
            _add(rv, bid, {"type": "image", "src": _rel(dst, sd), "fit": "frame", "photo": pc["id"], "credit": photos.credit(pc),
                           "short_credit": photos.short_credit(pc), "tag": "FILE"}, "photo", ok,
                 "real photo of the subject" if ok else f"real photo, but it shows the subject {pc.get('phase') or 'at another moment'}")
        _cheap_cands(rv, sec, job, phases)
        rv["beats"][bid]["msg"] = "All treatments generated."
        save(job, rv)
    thumbs(job, cfg, log)
    log(f"{bid}: all treatments ready")

def more_stock(job, bid, cfg, wg, log, payload):
    """Panel chat: more stock footage for this beat (no GPU generation, never an animation)."""
    sd, rd = _p(job); sp, sec = _section(job, bid)
    qs = [q for q in (payload.get("queries") or []) if isinstance(q, str) and q.strip()][:3] or sec.get("queries") or []
    n = max(1, min(4, int(payload.get("count") or 2)))
    k = len(list(rd.glob(f"stock_{bid}_m*.json"))) + 1
    log(f"{bid}: searching {n} more stock clip(s): {'; '.join(qs)}")
    picked, rejected = _extra_stock(job, sec, qs, f"m{k}", cfg, log, n=n)
    with _lock(job):
        rv = load(job); new = _stock_cands(rv, sec, picked, rejected, _story_subjects(job))
        rv["beats"][bid]["msg"] = f"{len(picked)} more stock clip(s) found" + (f", {len(rejected)} rejected" if rejected else "") + "."
        save(job, rv)
    thumbs(job, cfg, log)

def add_animation(job, bid, cfg, wg, log, payload):
    """Add animation: animate this beat's AI still(s) (making a still first if there is none)."""
    sd, rd = _p(job); sp, sec = _section(job, bid)
    lf = sd / "fallback" / "ladder.json"; lad = json.loads(lf.read_text(encoding="utf-8")) if lf.exists() else {}
    keys = [k for k in lad if k.rsplit("_", 1)[0] == bid and lad[k].get("still")] or [f"{bid}_9"]
    keys = [k for k in keys if not lad.get(k, {}).get("clip")] or keys
    log(f"{bid}: animating ({', '.join(keys[:1])})")
    st = _run_slots(job, sec, keys[:1], cfg, wg, log, animate=True)
    with _lock(job):
        rv = load(job)
        for k in keys[:1]:
            if k in st: _slot_cands(rv, sec, k, st[k], sd, True, log)
        r = st.get(keys[0], {})
        rv["beats"][bid]["msg"] = "Animation added." if r.get("clip") else f"Animation failed: {r.get('clip_why') or r.get('still_why') or 'unknown'}"
        save(job, rv)
    thumbs(job, cfg, log)

def refine(job, bid, cfg, wg, log, payload):
    from .llm import LLM
    text = (payload.get("text") or "").strip()
    if not text: raise ValueError("type an instruction first")
    sd, rd = _p(job); sp, sec = _section(job, bid)
    bare = re.fullmatch(r"\s*(https?://\S+|[A-Za-z]:\\[^\n]+|/[^\n]+)\s*", text)
    backend = "none (looked like a file/URL)"
    if bare: j = {"intent": "supply", "supply": bare.group(1), "understood": "use your file"}
    else:
        def chk(x):
            if x.get("intent") not in ("descriptive", "correction", "supply"): raise ValueError("intent must be descriptive, correction or supply")
            if x["intent"] != "supply" and len(str(x.get("still_prompt", "")).split()) < 12: raise ValueError("still_prompt too short")
        with LLM(cfg, log, lambda: False) as llm:
            backend = llm.name
            j = llm.chat_json("You are a careful news video editor. Reply with JSON only.",
                              REFINE.format(vo=sec["vo"], subject=(sec.get("subject") or {}).get("name") or "none", still=sec.get("still_prompt", ""),
                                            motion=sec.get("motion", ""), queries=json.dumps(sec.get("queries") or []), text=text.replace('"', "'")),
                              max_tokens=1200, check=chk)
    note = {"t": time.strftime("%H:%M"), "you": text, "intent": j["intent"], "understood": str(j.get("understood", ""))[:200], "backend": backend}
    with _lock(job):
        rv = load(job); rv["beats"][bid].setdefault("notes", []).append(note); save(job, rv)
    if j["intent"] == "supply":
        supply(job, bid, str(j.get("supply") or text), payload.get("tag", ""), cfg, log); return
    # new prompts on the beat (kept in the script, so a later run uses them too)
    sec["still_prompt"] = str(j["still_prompt"])[:500]; sec["motion"] = str(j.get("motion") or sec.get("motion", ""))[:160]
    qs = [q for q in (j.get("queries") or []) if isinstance(q, str) and q.strip()][:3]
    if qs: sec["queries"] = qs
    (sd / "plan.json").write_text(json.dumps(sp, indent=1), encoding="utf-8")
    with _lock(job):
        rv = load(job); b = rv["beats"][bid]
        n = sum(1 for h in b["history"]) + 1
        b["history"].append({"label": f"before \"{text[:40]}\"", "cands": list(b["cands"])}); b["cands"] = []
        save(job, rv)
    key = f"{bid}_r{n}"
    log(f"{bid}: refine ({j['intent']}, by {backend}): {note['understood']}")
    st = _run_slots(job, sec, [key], cfg, wg, log, prompt=sec["still_prompt"], motion=sec["motion"])
    picked, rejected = [], []
    if not sec.get("subject") and qs:
        try: picked, rejected = _extra_stock(job, sec, qs, f"r{n}", cfg, log)
        except Exception as e: log(f"  stock search failed ({str(e)[:100]})")
    with _lock(job):
        rv = load(job)
        if key in st: _slot_cands(rv, sec, key, st[key], sd, True, log)
        _stock_cands(rv, sec, picked, rejected, _story_subjects(job))
        rv["beats"][bid]["msg"] = f"New options from your instruction ({j['intent']}). Earlier options are under History."
        save(job, rv)
    thumbs(job, cfg, log)

# ---------------------------------------------------------------- after the render: keep only what was used
MEDIA = {".mp4", ".jpg", ".png", ".jpeg", ".webm", ".mov"}

def prune(job, log, full=True):
    """Delete previews and (full=True) the full files of treatments that weren't used (thumbnails stay). Files the video uses are
    listed in short/used.json by build() and the editor. After a render only previews go: the editor may still need the rest."""
    sd, rd = _p(job); uf = sd / "used.json"
    for d in (rd / "previews", Path(job) / "edit" / "previews"):
        if d.exists():
            for f in d.iterdir():
                if f.is_file(): f.unlink(missing_ok=True)
    if not full or not uf.exists(): return
    keep = {str((sd / u).resolve()) for u in json.loads(uf.read_text(encoding="utf-8"))}
    n, size = 0, 0
    for d in (rd / "previews", sd / "fallback", sd / "stock" / "clips", rd / "supplied"):
        if not d.exists(): continue
        for f in d.iterdir():
            if f.is_file() and f.suffix.lower() in MEDIA and str(f.resolve()) not in keep:
                try: size += f.stat().st_size; f.unlink(); n += 1
                except Exception: pass
    if n: log(f"Pruned {n} unused treatment file(s) ({size / 1e6:.0f} MB); thumbnails kept")
