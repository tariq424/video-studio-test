"""Post-render editing: replace one beat's visual in a finished video and splice it into the MP4 in place.

Shorts (Remotion): the beat's frame range of the Teaser composition is rendered again (same captions, graphics, narration) and
spliced into the MP4 between keyframes that sit exactly on the beat boundaries (added once per video, after the render or on the
first edit), so only that range is encoded. Long videos / explainers (FFmpeg): the visual slot clip is rendered again, its
section is rebuilt (captions/presenter are drawn over it) and the sections are joined again without re-encoding.

The new visual is fitted to the beat's slot automatically (or with the fit you pick):
  direct  - lengths match (or pictures/cards, which stretch to any length)
  trim    - longer footage: the middle segment of it
  speed   - longer footage: played up to 1.25x faster (then trimmed)
  slow    - shorter footage: slow motion up to 1.3x, then the last frame holds
  freeze  - shorter footage: plays, then the last frame holds
  loop    - shorter footage: plays again from the start
  still   - shorter footage: plays, then the beat's AI still / card fills the rest
Auto: trim when longer; when shorter, 'still' for beats that carry information, 'slow' for atmospheric beats."""
import json, re, shutil, subprocess, threading, time
from pathlib import Path
from . import media

FPS_S = 30                     # Remotion (Shorts)
BASE_RATE = 0.85               # footage plays slightly slowed everywhere
ENC_S = ["-c:v", "libx264", "-preset", "fast", "-crf", 18, "-pix_fmt", "yuv420p", "-profile:v", "high", "-r", FPS_S]
FITS = ("auto", "direct", "trim", "speed", "slow", "freeze", "loop", "still")
FIT_NAME = {"direct": "direct splice", "trim": "trimmed to a segment", "speed": "sped up", "slow": "slow motion, then hold",
            "freeze": "last frame held", "loop": "looped", "still": "footage, then a still fills the rest"}

ATMOS = re.compile(r"\b(storm|rain|clouds?|sky|skies|night|dawn|dusk|sunset|sunrise|fog|mist|snow|wind|sea|ocean|waves?|desert|"
                   r"mountains?|forest|skyline|city lights|quiet|calm|silence|silent|darkness|landscape|horizon|weather|scenery)\b", re.I)
INFO = re.compile(r"\d|\b(hundred|thousand|million|billion|percent|said|says|told|according|announced|confirmed|reported|"
                  r"revealed|claims?|admitted|denied|because|minutes?|hours?|feet|miles|kilometres?|kilometers?)\b", re.I)

def atmospheric(vo):
    """True for mood/scenery beats (slow motion is fine there); False for beats that carry information."""
    names = len(re.findall(r"(?<![.!?]\s)(?<!^)\b[A-Z][a-z]{2,}", vo or ""))
    return bool(ATMOS.search(vo or "")) and not INFO.search(vo or "") and names < 2

# ---------------------------------------------------------------- fitting
def src_path(sd, item):
    t = item["type"]
    if t == "stock": return Path(sd) / "stock" / "clips" / f"{item['clip']['id']}.mp4"
    if t == "video": return Path(sd) / item["src"]
    return None

def layout(sd, items, d, mode="auto", vo="", filler=None):
    """-> (list of (item, props, start, length), mode used, why). props: rate / start / freezeAt / loop for videos."""
    lens = []
    for it in items:
        p = src_path(sd, it)
        try: lens.append(media.dur(p) if p else None)
        except Exception: lens.append(None)
    vids = [i for i, L in enumerate(lens) if L]
    out = []
    def place(alloc, props):
        t = 0.0
        for i, it in enumerate(items):
            out.append((it, props.get(i, {}), round(t, 3), alloc[i])); t += alloc[i]
    if not vids:   # pictures and cards: share the slot
        place([d / len(items)] * len(items), {}); return out, "direct", "pictures and cards stretch to any length"
    if len(vids) < len(items):   # footage at its own length, pictures/cards share the rest (at least 1.5 s each)
        nat = {i: lens[i] / items[i].get("rate", BASE_RATE) for i in vids}; rest = len(items) - len(vids)
        room = max(0.5, d - 1.5 * rest); k = min(1.0, room / sum(nat.values()))
        alloc = [nat[i] * k if i in nat else 0 for i in range(len(items))]
        left = max(0.0, d - sum(alloc))
        alloc = [a if i in nat else left / rest for i, a in enumerate(alloc)]
        props = {i: {"rate": items[i].get("rate", BASE_RATE), **({"start": round(lens[i] * (1 - k) / 2, 3)} if k < 1 else {})} for i in vids}
        place(alloc, props); return out, "direct", "footage at its own length, pictures fill the rest"
    rt = [it.get("rate", BASE_RATE) for it in items]   # each item's normal playback speed
    nat = [L / r for L, r in zip(lens, rt)]; total = sum(nat); delta = d - total
    why = ""
    if mode == "auto":
        if abs(delta) <= 0.3: mode, why = "direct", "the footage is as long as the beat"
        elif delta < 0: mode, why = "trim", f"the footage is {-delta:.1f}s longer than the beat"
        elif atmospheric(vo): mode, why = "slow", f"atmospheric beat, footage {delta:.1f}s short"
        else: mode, why = "still", f"the narration carries information; footage {delta:.1f}s short"
    if delta < -0.3 and mode in ("slow", "freeze", "loop", "still"): mode = "trim"
    if delta > 0.3 and mode in ("trim",): mode = "freeze"
    if delta > 0.3 and mode == "speed": mode = "slow"
    props = {i: {"rate": rt[i]} for i in range(len(items))}
    last = len(items) - 1
    if mode == "direct":
        alloc = [d * x / total for x in nat]
        if delta > 0: props[last]["freezeAt"] = round(nat[-1] - 0.05, 3)
    elif mode == "trim":
        alloc = [x * d / total for x in nat]
        for i in range(len(items)): props[i]["start"] = round((nat[i] - alloc[i]) * rt[i] / 2, 3)
    elif mode == "speed":
        f = min(1.25, total / d)
        alloc = [x / f for x in nat]; k = min(1.0, d / sum(alloc))
        for i in range(len(items)):
            props[i]["rate"] = round(rt[i] * f, 4)
            if k < 1: props[i]["start"] = round(lens[i] * (1 - k) / 2, 3)
        alloc = [a * k for a in alloc]
    elif mode == "slow":
        f = max(1 / 1.3, total / d)
        alloc = [x / f for x in nat]; extra = max(0.0, d - sum(alloc))
        for i in range(len(items)): props[i]["rate"] = round(rt[i] * f, 4)
        if extra > 0.05: props[last]["freezeAt"] = round(alloc[-1] - 0.05, 3); alloc[-1] += extra
    elif mode == "freeze":
        alloc = list(nat); props[last]["freezeAt"] = round(nat[-1] - 0.05, 3); alloc[-1] += max(0.0, delta)
    elif mode == "loop":
        alloc = list(nat); props[last]["loop"] = round(nat[-1], 3); alloc[-1] += max(0.0, delta)
    elif mode == "still":
        if filler is None or delta < 1.0:
            alloc = list(nat); props[last]["freezeAt"] = round(nat[-1] - 0.05, 3); alloc[-1] += max(0.0, delta)
            if filler is None and delta >= 1.0: why = (why + "; no still for this beat, so the last frame holds").lstrip("; ")
        else:
            items = list(items) + [filler]; alloc = list(nat) + [delta]
    place(alloc, props)
    return out, mode, why or FIT_NAME.get(mode, mode)

def filler_for(rv, bid):
    """The beat's best AI still / parallax / photo, else its headline card (for the 'still' fit)."""
    if not rv or bid not in rv.get("beats", {}): return None
    b = rv["beats"][bid]
    for rung in ("parallax", "still", "photo", "supplied"):
        for cid in b["cands"]:
            c = rv["cands"][cid]
            if c["rung"] == rung and c.get("ok") and c["item"]["type"] in ("layers", "image") and not c.get("missing"): return c["item"]
    return b.get("skip_item")

# ---------------------------------------------------------------- items -> Remotion backgrounds
def to_bg(sd, item, props, start, story_subjects=False, dest=None, used=None):
    """A Remotion background for an item. dest = public dir to copy media into (Short timeline); else paths stay relative to sd."""
    sd = Path(sd); t = item["type"]
    def media_path(rel, sub):
        if dest is None: return rel
        dst = Path(dest) / "media" / sub / Path(rel).name; dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists(): shutil.copy2(sd / rel, dst)
        if used is not None: used.append(rel)
        return f"media/{sub}/{Path(rel).name}"
    if t == "stock":
        c = item["clip"]; bg = {"type": "video", "src": media_path(f"stock/clips/{c['id']}.mp4", "stock")}
        tag = item.get("tag", "ILLUSTRATIVE" if story_subjects else "")
        if tag: bg["tag"] = tag
        if c.get("orient") == "landscape" and _tall(sd): bg["fit"] = "frame"
    elif t == "video": bg = {"type": "video", "src": media_path(item["src"], "fb")}; bg.update({"tag": item["tag"]} if item.get("tag") else {})
    elif t == "image":
        bg = {"type": "image", "src": media_path(item["src"], "fb"), "fit": item.get("fit", "frame"), "credit": item.get("short_credit", "")}
        if item.get("tag", "FILE"): bg["tag"] = item.get("tag", "FILE")
    elif t == "layers":
        bg = {"type": "layers", "layers": [media_path(x, "fb") for x in item["layers"]]}
        if item.get("tag"): bg["tag"] = item["tag"]
    else: bg = {"type": "graphic", "g": item["g"]}
    bg.update(props); bg["from"] = round(start, 3)
    return bg

def _tall(sd):
    from .ladder import space
    sp = space(sd); return sp["h"] > sp["w"]

# ---------------------------------------------------------------- job kinds and timelines
def kind(job):
    from .pipeline import Job
    s = Job(job).state
    if s.get("short_output") and (Path(job) / "short" / "public" / "teaser.json").exists(): return "short"
    if s.get("output"): return "long"
    return None

def _teaser(job):
    return json.loads((Path(job) / "short" / "public" / "teaser.json").read_text(encoding="utf-8"))

def short_frames(tz):
    """Frame range [a, b) of each beat, as the Teaser composition places them."""
    import math
    fr = lambda s: max(1, math.floor(s * FPS_S + 0.5))   # Math.round in the Teaser composition (halves round up)
    total = int(-(-tz["total"] * FPS_S // 1))
    out = []
    for i, b in enumerate(tz["beats"]):
        a = fr(b["start"]) if b["start"] > 0 else 0
        e = fr(tz["beats"][i + 1]["start"]) if i + 1 < len(tz["beats"]) else total
        out.append((b["id"], a, e))
    return out, total

def long_layout(job):
    """Sections and visual slots of a long video: [{id, sid, vi, start, dur, label, vo}] (start/dur in seconds of the output)."""
    from .pipeline import Job
    from . import assemble
    j = Job(job); plan = j.plan(); s = j.state
    out, t = [], 0.0
    secs = plan["sections"]
    for si, sec in enumerate(secs):
        p = Path(job) / "build" / f"sec_{sec['id']}.mp4"
        if not p.exists(): break
        vis, bounds, slots, D, caps = assemble.layout(Path(job), si, sec, secs, s.get("captions", True))
        for vi, v in enumerate(vis):
            vo = " ".join(" ".join(c["words"]) for c in caps if bounds[vi] <= assemble.LEAD + c["start"] < bounds[vi + 1]) or sec["vo"]
            out.append({"id": f"{sec['id']}_{vi}", "sid": sec["id"], "si": si, "vi": vi, "start": round(t + bounds[vi], 3), "dur": round(slots[vi], 3),
                        "label": sec["title"], "vo": vo[:600], "editable": not str(v.get("id", "")).startswith("_"), "visual": v})
        t += media.dur(p)
    return out

def beats(job):
    """The timeline for the job page: {kind, beats: [{id, start, dur, label, editable}]}."""
    k = kind(job)
    if k == "short":
        tz = _teaser(job)
        from .pipeline import Job
        plan = Job(job).short_plan() or {"sections": []}
        vo = {s["id"]: s["vo"] for s in plan["sections"]}; cta = {s["id"] for s in plan["sections"] if s.get("cta")}
        return {"kind": "short", "beats": [{"id": b["id"], "start": b["start"], "dur": b["dur"], "label": f"Beat {i + 1}", "vo": vo.get(b["id"], ""),
                                             "editable": b["id"] not in cta} for i, b in enumerate(tz["beats"])]}
    if k == "long":
        return {"kind": "long", "beats": [{k2: b[k2] for k2 in ("id", "start", "dur", "label", "vo", "editable")} for b in long_layout(job)]}
    return {"kind": None, "beats": []}

# ---------------------------------------------------------------- workspaces (where a beat's candidates live)
def workspace(job, k=None):
    """Shorts: the job itself (short/review). Long videos: job/longedit, a Short-like workspace in 16:9."""
    k = k or kind(job)
    return Path(job) if k == "short" else Path(job) / "longedit"

def open_beat(job, bid, cfg, log):
    """Make sure the beat has a review entry with its current visual among the candidates, and thumbnails. -> rv"""
    from . import review
    job = Path(job); k = kind(job); ws = workspace(job, k); sd, rd = review._p(ws); rd.mkdir(parents=True, exist_ok=True)
    with review._lock(ws):
        rv = review.load(ws) or {"mode": "edit", "status": "closed", "next": 1, "beats": {}, "cands": {}}
        if k == "short":
            tz = _teaser(job); tb = next(b for b in tz["beats"] if b["id"] == bid)
            from .pipeline import Job
            sec = next(s for s in Job(job).short_plan()["sections"] if s["id"] == bid)
            b = rv["beats"].setdefault(bid, {"vo": sec["vo"], "secs": tb["dur"], "auto": [], "cands": [], "decision": "auto", "chosen": [],
                                             "uncertain": False, "why": "", "history": [], "busy": "", "msg": "", "notes": []})
            b["skip_item"] = review._skip_item(sec); b["secs"] = tb["dur"]
            if not b.get("current"):   # what the video shows now (older jobs have no candidates at all)
                cur = []
                for bg in tb["bgs"]:
                    it = _bg_item(bg)
                    if it: cur.append(review._add(rv, bid, it, "current", True, "in the video now"))
                b["current"] = cur
                if not b["auto"]: b["auto"] = cur
        else:
            _long_workspace(job, cfg)
            lb = next(x for x in long_layout(job) if x["id"] == bid)
            sec = {"id": bid, "vo": lb["vo"], "backdrop": {"kind": "headline", "kicker": "", "text": lb["label"][:60], "sub": ""}}
            b = rv["beats"].setdefault(bid, {"vo": lb["vo"], "secs": lb["dur"], "auto": [], "cands": [], "decision": "auto", "chosen": [],
                                             "uncertain": False, "why": "", "history": [], "busy": "", "msg": "", "notes": []})
            b["skip_item"] = review._skip_item(sec); b["secs"] = lb["dur"]
            if not b.get("current"):
                src = job / "build" / f"v_{lb['sid']}_{lb['vi']}.mp4"; dst = sd / "current" / f"{bid}.mp4"; dst.parent.mkdir(parents=True, exist_ok=True)
                if src.exists() and not dst.exists(): shutil.copy2(src, dst)
                cur = [review._add(rv, bid, {"type": "video", "src": f"current/{bid}.mp4", "tag": "", "rate": 1.0}, "current", True, "in the video now")] if dst.exists() else []
                b["current"] = cur; b["auto"] = cur
                review._add(rv, bid, b["skip_item"], "headline", True, "text card summing up the beat")
        for cid in b["cands"]:   # files of unused treatments may have been cleaned up
            rv["cands"][cid]["missing"] = not _item_exists(sd, rv["cands"][cid]["item"])
        review.save(ws, rv)
    review.thumbs(ws, cfg, log, [c for c in rv["beats"][bid]["cands"] if not rv["cands"][c].get("missing")])
    return review.load(ws)

def _bg_item(bg):
    """A timeline background back to a candidate item (paths relative to the short folder)."""
    t = bg.get("type")
    if t == "video": return {"type": "video", "src": "public/" + bg["src"], "tag": bg.get("tag", ""), **({"rate": bg["rate"]} if bg.get("rate") else {})}
    if t == "image": return {"type": "image", "src": "public/" + bg["src"], "fit": bg.get("fit", "frame"), "tag": bg.get("tag", ""), "short_credit": bg.get("credit", "")}
    if t == "layers": return {"type": "layers", "layers": ["public/" + x for x in bg["layers"]], "tag": bg.get("tag", "")}
    if t == "graphic": return {"type": "graphic", "g": bg["g"]}
    return None

def _item_exists(sd, it):
    t = it["type"]
    if t == "stock": return (Path(sd) / "stock" / "clips" / f"{it['clip']['id']}.mp4").exists()
    if t == "stock_rejected": return True
    if t in ("video", "image"): return (Path(sd) / it["src"]).exists()
    if t == "layers": return all((Path(sd) / x).exists() for x in it["layers"])
    return True

def _long_workspace(job, cfg):
    """job/longedit/short: plan (one section per visual slot), 16:9 space, entities, so the review tools work unchanged."""
    ws = Path(job) / "longedit"; sd = ws / "short"; sd.mkdir(parents=True, exist_ok=True)
    (sd / "space.json").write_text(json.dumps({"orient": "landscape", "still_res": "1920x1088", "i2v_res": "1280x720", "w": 1920, "h": 1080}), encoding="utf-8")
    if (Path(job) / "entities.json").exists() and not (ws / "entities.json").exists(): shutil.copy2(Path(job) / "entities.json", ws / "entities.json")
    pf = sd / "plan.json"
    old = {s["id"]: s for s in json.loads(pf.read_text(encoding="utf-8"))["sections"]} if pf.exists() else {}
    secs = []
    for b in long_layout(job):
        if not b["editable"]: continue
        v = b["visual"]; o = old.get(b["id"], {})
        prompt = o.get("still_prompt") or v.get("prompt") or f"Cinematic documentary shot illustrating: {b['label']}"
        secs.append({"id": b["id"], "title": b["label"], "vo": b["vo"], "still_prompt": prompt, "motion": o.get("motion", ""),
                     "queries": o.get("queries") or v.get("queries") or [" ".join(prompt.split()[:5])], "subject": o.get("subject"),
                     "backdrop": {"kind": "headline", "kicker": "", "text": b["label"][:60], "sub": ""}, "visuals": []})
    pf.write_text(json.dumps({"title": "long edit", "sections": secs}, indent=1), encoding="utf-8")
    return ws

# ---------------------------------------------------------------- preview and apply
_busy, _lk = {}, threading.Lock()

def _plan_beat(job, bid, cids, fit, cfg):
    """Items for the chosen candidates, fitted to the beat. -> (k, ws, sd, rv, beat-info, fitted list, mode, why)"""
    from . import review
    job = Path(job); k = kind(job); ws = workspace(job, k); sd, _ = review._p(ws); rv = review.load(ws)
    if not cids: raise ValueError("pick at least one treatment")
    for cid in cids:
        if rv["cands"][cid]["item"]["type"] == "stock_rejected": review._ensure_clip(ws, cid, cfg, print); rv = review.load(ws)
    items = [rv["cands"][c]["item"] for c in cids]
    if k == "short":
        tz = _teaser(job); tb = next(b for b in tz["beats"] if b["id"] == bid); d = tb["dur"]; vo = rv["beats"][bid]["vo"]
    else:
        lb = next(x for x in long_layout(job) if x["id"] == bid); d = lb["dur"]; vo = lb["vo"]
    fit = fit if fit in FITS else "auto"
    lay, mode, why = layout(sd, items, d, fit, vo, filler_for(rv, bid))
    return k, ws, sd, rv, d, lay, mode, why

def _story(job):
    ef = Path(job) / "entities.json"
    return any(e.get("kind") != "person" for e in (json.loads(ef.read_text(encoding="utf-8")) if ef.exists() else []))

def preview(job, bid, cids, fit, cfg, log):
    """Half-resolution preview of the beat as it will look in the video (narration included). -> {video, fit, why}"""
    from . import review
    k, ws, sd, rv, d, lay, mode, why = _plan_beat(job, bid, cids, fit, cfg)
    pd = Path(job) / "edit" / "previews"; pd.mkdir(parents=True, exist_ok=True)
    out = pd / f"{bid}_{int(time.time())}.mp4"
    if k == "short":
        tz, (a, e) = _short_props(job, sd, bid, lay, dest=None)
        _render(job, "Teaser", tz, out, cfg, log, frames=(a, e - 1), scale=0.5, audio=True)
    else:
        lb = next(x for x in long_layout(job) if x["id"] == bid)
        bgs = [review._urlify(to_bg(sd, it, p, s0, _story(job)), sd) for it, p, s0, _ in lay]
        tmp = out.with_name(out.stem + "_v.mp4")
        _render(job, "BeatClip", {"bgs": bgs, "dur": d, "w": 960, "h": 540}, tmp, cfg, log, audio=False)
        from .pipeline import Job
        outp = Path(Job(job).state["output"])
        media.ff("-i", tmp, "-ss", f"{lb['start']:.3f}", "-t", f"{d:.3f}", "-i", outp, "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-shortest", out)
        tmp.unlink(missing_ok=True)
    rel = out.resolve().relative_to(Path(job).resolve()).as_posix()
    return {"video": rel, "fit": mode, "why": why}

def _short_props(job, sd, bid, lay, dest):
    """Teaser props with this beat's backgrounds replaced (media as http URLs for the preview renderer). -> (props, (a, e))"""
    from . import review
    tz = _teaser(job); pub = Path(job) / "short" / "public"
    story = _story(job)
    bgs = [to_bg(sd, it, p, s0, story, dest=dest) for it, p, s0, _ in lay]
    for b in tz["beats"]:
        if b["id"] == bid: b["bgs"] = bgs
    frames, total = short_frames(tz)
    a, e = next((x[1], x[2]) for x in frames if x[0] == bid)
    props = json.loads(json.dumps(tz))
    base = review.files_url(pub) + "/"; sdbase = review.files_url(sd) + "/"
    props["audio"] = base + props["audio"]
    for b in props["beats"]:
        for g in b["bgs"]:
            pre = base if (b["id"] != bid or dest is not None) else sdbase
            if g.get("src") and not g["src"].startswith("http"): g["src"] = pre + g["src"]
            if g.get("layers"): g["layers"] = [x if x.startswith("http") else pre + x for x in g["layers"]]
        for gr in b.get("graphics", []):
            th = gr.get("g", {}).get("thumb")
            if th and not str(th).startswith("http"): gr["g"]["thumb"] = base + th
    return (props, (a, e)) if dest is None else (props, (a, e), tz)

def _render(job, comp, props, out, cfg, log, frames=None, scale=1.0, audio=True):
    from . import review, short
    rdir, bundle = review._bundle(log); out = Path(out); out.parent.mkdir(parents=True, exist_ok=True)
    pf = out.with_name(out.stem + "_props.json"); pf.write_text(json.dumps(props), encoding="utf-8")
    cmd = [short._npx(), "remotion", "render", str(bundle), comp, str(out), f"--props={pf}", f"--gl={short._gl(cfg)}", f"--scale={scale}",
           "--log=error", f"--concurrency={cfg.get('short_concurrency', '75%')}", "--crf=12" if scale >= 1 else "--crf=24"]
    if frames: cmd.append(f"--frames={frames[0]}-{frames[1]}")
    if not audio: cmd.append("--muted")
    p = None
    for attempt in range(3):
        p = subprocess.run(cmd, cwd=rdir, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
        if p.returncode == 0 and out.exists(): break
        if short.BROWSER_FLAKE not in (p.stdout + p.stderr): break
        time.sleep(5)
    pf.unlink(missing_ok=True)
    if p.returncode != 0 or not out.exists():
        err = next((l for l in (p.stdout + p.stderr).splitlines() if re.search(r"Error|error:", l) and "│" not in l), "")
        raise RuntimeError("render failed: " + re.sub(r"\x1b\[[0-9;]*m", "", err or (p.stdout + p.stderr).strip()[-300:])[:300])
    return out

def _nframes(p):
    o = subprocess.run([media._bin("ffprobe"), "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries", "stream=nb_read_packets",
                        "-of", "csv=p=0", str(p)], capture_output=True, text=True).stdout.strip()
    return int(o or 0)

def ensure_keyframes(job, log):
    """Shorts: one re-encode that puts a keyframe exactly on every beat boundary, so a beat can be swapped without re-encoding the
    rest. Done after each render, and on the first edit of a Short rendered before this existed."""
    from .pipeline import Job
    job = Path(job); j = Job(job); outp = Path(j.state["short_output"]); kf = job / "edit" / "keyframes.json"
    frames, total = short_frames(_teaser(job))
    stamp = {"size": outp.stat().st_size, "mtime": int(outp.stat().st_mtime), "frames": [a for _, a, _ in frames]}
    if kf.exists() and json.loads(kf.read_text(encoding="utf-8")) == stamp: return
    log("Preparing the Short for editing (keyframes on beat boundaries, one time)...")
    t0 = time.time(); tmp = outp.with_name("_kf_" + outp.name)
    times = ",".join(f"{a / FPS_S:.6f}" for _, a, _ in frames if a > 0)
    media.ff("-i", outp, "-map", "0:v", "-map", "0:a?", *ENC_S, "-force_key_frames", times, "-forced-idr", 1, "-c:a", "copy", "-movflags", "+faststart", tmp, timeout=3600)
    tmp.replace(outp)
    kf.parent.mkdir(parents=True, exist_ok=True)
    kf.write_text(json.dumps({"size": outp.stat().st_size, "mtime": int(outp.stat().st_mtime), "frames": [a for _, a, _ in frames]}), encoding="utf-8")
    log(f"  done in {time.time() - t0:.0f}s")

def _clear_prev(job):
    for p in list(Path(job).glob("output/*.prev")) + list(Path(job).glob("short/public/*.prev")) + list(Path(job).glob("build/*.prev")):
        p.unlink(missing_ok=True)

def _backup(paths):
    for p in paths:
        p = Path(p)
        if p.exists(): shutil.copy2(p, p.with_name(p.name + ".prev"))

def status(job): return _busy.get(str(Path(job)), "")

def start_apply(job, bid, cids, fit, cfg, log):
    key = str(Path(job))
    with _lk:
        if _busy.get(key): return "Already applying an edit to this video."
        _busy[key] = f"Applying the new visual to {bid}..."
    def run():
        try: apply(job, bid, cids, fit, cfg, log)
        except Exception as e:
            import traceback
            log(f"Edit {bid} failed: {str(e)[:300]}"); log(traceback.format_exc()[-800:])
            _busy[key + ":err"] = str(e)[:300]
        finally: _busy[key] = ""
    _busy.pop(key + ":err", None)
    threading.Thread(target=run, daemon=True).start(); return ""

def apply(job, bid, cids, fit, cfg, log):
    """Render the beat with its new visual and splice it into the output MP4 in place (no re-render of other beats)."""
    from . import review
    from .pipeline import Job
    job = Path(job); t0 = time.time()
    k, ws, sd, rv, d, lay, mode, why = _plan_beat(job, bid, cids, fit, cfg)
    log(f"Edit {bid}: {', '.join(RUNG(rv, c) for c in cids)} -> {FIT_NAME.get(mode, mode)} ({why})")
    _clear_prev(job)
    if k == "short": _apply_short(job, bid, sd, lay, cfg, log)
    else: _apply_long(job, bid, sd, lay, d, cfg, log)
    with review._lock(ws):
        rv = review.load(ws); b = rv["beats"][bid]
        rv["undo"] = {"beat": bid, "state": {k2: b.get(k2) for k2 in ("edit", "decision", "chosen", "current")}}   # for Undo
        b["edit"] = {"cands": list(cids), "fit": mode, "why": why, "t": time.strftime("%H:%M")}
        b["decision"], b["chosen"] = "chosen", list(cids); b["current"] = list(cids)
        b["msg"] = f"Applied ({FIT_NAME.get(mode, mode)})."
        review.save(ws, rv)
    j = Job(job); edits = j.state.get("edits", []); edits.append({"beat": bid, "fit": mode, "t": time.time()}); j.save(edits=edits)
    log(f"Edit {bid}: spliced into the video in {time.time() - t0:.0f}s")

def RUNG(rv, cid):
    from .review import RUNG as R
    return R.get(rv["cands"][cid]["rung"], rv["cands"][cid]["rung"])

def _apply_short(job, bid, sd, lay, cfg, log):
    from .pipeline import Job
    j = Job(job); outp = Path(j.state["short_output"]); ed = job / "edit"; ed.mkdir(exist_ok=True)
    ensure_keyframes(job, log)
    pub = job / "short" / "public"; used = []
    props, (a, e), tz = _short_props(job, sd, bid, lay, dest=pub)
    n = e - a
    # 1. the beat's frames, full resolution (no audio: the narration track is kept as it is)
    raw = ed / "seg_raw.mp4"; seg = ed / "seg.mp4"
    _render(job, "Teaser", props, raw, cfg, log, frames=(a, e - 1), scale=1.0, audio=False)
    media.ff("-i", raw, "-an", *ENC_S, "-frames:v", n, "-force_key_frames", "0", "-forced-idr", 1, seg)
    if _nframes(seg) != n: raise RuntimeError(f"rendered {_nframes(seg)} frames for the beat, expected {n}")
    # 2. cut the video at the beat's keyframes (no re-encoding), swap the middle, join
    parts = ed / "parts"; shutil.rmtree(parts, ignore_errors=True); parts.mkdir()
    cuts = [x / FPS_S - 0.001 for x in (a, e) if 0 < x < short_frames(tz)[1]]
    vcopy = ed / "video_only.mp4"; media.ff("-i", outp, "-map", "0:v", "-c", "copy", vcopy)
    if cuts: media.ff("-i", vcopy, "-c", "copy", "-f", "segment", "-segment_times", ",".join(f"{c:.6f}" for c in cuts), "-reset_timestamps", 1, parts / "p%03d.mp4")
    else: shutil.copy2(vcopy, parts / "p000.mp4")
    ps = sorted(parts.glob("p*.mp4")); mid = 1 if a > 0 else 0
    total_before = _nframes(vcopy)
    ok = len(ps) == len(cuts) + 1 and _nframes(ps[mid]) == n
    newv = ed / "video_new.mp4"
    if ok:
        lst = ed / "join.txt"; lst.write_text("".join(f"file '{(seg if i == mid else p).resolve().as_posix()}'\n" for i, p in enumerate(ps)), encoding="utf-8")
        media.ff("-f", "concat", "-safe", 0, "-i", lst, "-c", "copy", newv)
        ok = _nframes(newv) == total_before
    if not ok:   # keyframes not where expected: re-encode the video track with the beat overlaid (slower, always correct)
        log("  keyframes didn't line up; re-encoding the video track once (slower)")
        times = ",".join(f"{x / FPS_S:.6f}" for _, x, _ in short_frames(tz)[0] if x > 0)
        media.ff("-i", vcopy, "-i", seg, "-filter_complex", f"[1:v]setpts=PTS-STARTPTS+{a / FPS_S:.6f}/TB[s];[0:v][s]overlay=eof_action=pass:enable='between(n,{a},{e - 1})'[v]",
                 "-map", "[v]", *ENC_S, "-force_key_frames", times, "-forced-idr", 1, newv, timeout=3600)
    # 3. put the original narration back, replace the output (previous version kept as .prev for Undo)
    tmp = outp.with_name("_edit_" + outp.name)
    media.ff("-i", newv, "-i", outp, "-map", "0:v", "-map", "1:a?", "-c", "copy", "-movflags", "+faststart", tmp)
    if abs(_nframes(tmp) - total_before) > 0: raise RuntimeError("the edited video has a different length; the original is unchanged")
    _backup([outp, pub / "teaser.json"])
    tmp.replace(outp)
    (pub / "teaser.json").write_text(json.dumps(tz, indent=1, ensure_ascii=False), encoding="utf-8")
    uf = job / "short" / "used.json"; u = set(json.loads(uf.read_text(encoding="utf-8"))) if uf.exists() else set()
    uf.write_text(json.dumps(sorted(u | set(used)), indent=1), encoding="utf-8")
    kf = ed / "keyframes.json"; st = json.loads(kf.read_text(encoding="utf-8")); st.update(size=outp.stat().st_size, mtime=int(outp.stat().st_mtime))
    kf.write_text(json.dumps(st), encoding="utf-8")
    for p in (raw, seg, vcopy, newv): Path(p).unlink(missing_ok=True)
    shutil.rmtree(parts, ignore_errors=True)

def _apply_long(job, bid, sd, lay, d, cfg, log):
    from . import review, assemble
    from .pipeline import Job
    j = Job(job); outp = Path(j.state["output"]); plan = j.plan()
    lb = next(x for x in long_layout(job) if x["id"] == bid)
    b = job / "build"; ed = job / "edit"; ed.mkdir(exist_ok=True)
    bgs = [review._urlify(to_bg(sd, it, p, s0, _story(job)), sd) for it, p, s0, _ in lay]
    raw = ed / "slot_raw.mp4"
    _render(job, "BeatClip", {"bgs": bgs, "dur": d, "w": assemble.W, "h": assemble.H}, raw, cfg, log, audio=False)
    nfr = int(round(lb["dur"] * assemble.FPS))
    vclip = b / f"v_{lb['sid']}_{lb['vi']}.mp4"; secf = b / f"sec_{lb['sid']}.mp4"
    _backup([outp, vclip, secf])
    keep = ed / "clips" / vclip.name; keep.parent.mkdir(exist_ok=True)
    media.ff("-i", raw, "-an", "-vf", f"fps={assemble.FPS},scale={assemble.W}:{assemble.H},setsar=1,tpad=stop_mode=clone:stop_duration=1,trim=duration={lb['dur']:.3f}",
             "-frames:v", nfr, *assemble.ENC, keep)
    shutil.copy2(keep, vclip)
    # remembered in the plan, so a full rebuild keeps the edit
    for v in plan["sections"][lb["si"]]["visuals"]:
        if v is not None and v.get("id") == lb["visual"].get("id"): v["edit_clip"] = keep.relative_to(job).as_posix()
    j.save_plan(plan)
    secf.unlink(missing_ok=True)
    s = j.state
    segs = json.loads((job / "presenter" / "segments.json").read_text()) if s.get("presenter") and (job / "presenter" / "segments.json").exists() else []
    assemble.section(job, lb["si"], plan["sections"][lb["si"]], plan["sections"], segs, s.get("captions", True), log)
    parts = [b / f"sec_{x['id']}.mp4" for x in plan["sections"]]
    lst = b / "final.txt"; lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    media.ff("-f", "concat", "-safe", 0, "-i", lst, "-an", "-c:v", "copy", b / "final_video.mp4")
    tmp = outp.with_name("_edit_" + outp.name)
    media.ff("-i", b / "final_video.mp4", "-i", b / "final_audio.wav", "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
             "-shortest", "-movflags", "+faststart", tmp)
    tmp.replace(outp); raw.unlink(missing_ok=True)

def undo(job, log):
    """Put back the version before the last edit."""
    job = Path(job); k = kind(job)
    from .pipeline import Job
    j = Job(job)
    if k == "short": files = [Path(j.state["short_output"]), job / "short" / "public" / "teaser.json"]
    else:
        files = [Path(j.state["output"])] + list((job / "build").glob("v_*.mp4")) + list((job / "build").glob("sec_*.mp4"))
    done = 0
    for p in files:
        pv = p.with_name(p.name + ".prev")
        if pv.exists(): shutil.copy2(pv, p); pv.unlink(); done += 1
    if not done: raise ValueError("nothing to undo")
    if k == "short":   # keyframes are still on the boundaries; refresh the stamp
        kf = job / "edit" / "keyframes.json"
        if kf.exists():
            st = json.loads(kf.read_text(encoding="utf-8")); outp = Path(j.state["short_output"])
            st.update(size=outp.stat().st_size, mtime=int(outp.stat().st_mtime)); kf.write_text(json.dumps(st), encoding="utf-8")
    edits = j.state.get("edits", [])
    if edits: edits.pop(); j.save(edits=edits)
    from . import review   # the beat's record goes back too, so a full re-render doesn't bring the undone edit back
    ws = workspace(job, k)
    with review._lock(ws):
        rv = review.load(ws)
        if rv and rv.get("undo"):
            u = rv.pop("undo"); b = rv["beats"].get(u["beat"])
            if b:
                for k2, v in u["state"].items():
                    if v is None: b.pop(k2, None)
                    else: b[k2] = v
                b["msg"] = "Last edit undone."
            review.save(ws, rv)
    log("Edit undone: the previous version of the video is back")
