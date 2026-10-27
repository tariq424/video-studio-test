"""Post-render editing: replace one beat's visual in a finished video and splice it into the MP4 in place.

Shorts (Remotion): the beat's frame range of the Teaser composition is rendered again (same captions, graphics, narration) and
spliced into the MP4 between keyframes that sit exactly on the beat boundaries (added once per video, after the render or on the
first edit), so only that range is encoded. Explainers rendered with Remotion (the default since Oct 2026) work the same way: each
visual slot of the explainer's Teaser timeline (build/public/teaser.json) is a beat, its frame range is rendered again and spliced
in between keyframes on the slot boundaries. Older long videos (FFmpeg stitcher, presenter on): the visual slot clip is rendered
again, its section is rebuilt (captions/presenter are drawn over it) and the sections are joined again without re-encoding.

A job with both a Short and an explainer edits one at a time (state "edit_target": short | long; set from the job page).
Undo is a stack (edit/history/NNN): every applied edit keeps what it replaced (the old frames of that range, the timeline JSON,
the beat's review state), so edits can be undone one by one, newest first.

The new visual is fitted to the beat's slot automatically (or with the fit you pick):
  direct  - lengths match (or pictures/cards, which stretch to any length)
  trim    - longer footage: the middle segment of it
  speed   - longer footage: played up to 1.25x faster (then trimmed)
  slow    - shorter footage: slow motion up to 1.3x, then the last frame holds
  freeze  - shorter footage: plays, then the last frame holds
  loop    - shorter footage: plays again from the start
  still   - shorter footage: plays, then the beat's AI still / card fills the rest
Auto: trim when longer; when shorter, 'still' for beats that carry information, 'slow' for atmospheric beats."""
import json, math, re, shutil, subprocess, threading, time
from pathlib import Path
from . import media

FPS_S = 30                     # Remotion (Shorts)
BASE_RATE = 0.85               # footage plays slightly slowed everywhere
ENC_S = ["-c:v", "libx264", "-preset", "fast", "-crf", 18, "-pix_fmt", "yuv420p", "-profile:v", "high", "-r", FPS_S]
FITS = ("auto", "direct", "trim", "speed", "slow", "freeze", "loop", "still", "segment")
FIT_NAME = {"direct": "direct splice", "trim": "trimmed to a segment", "speed": "sped up", "slow": "slow motion, then hold",
            "freeze": "last frame held", "loop": "looped", "still": "footage, then a still fills the rest",
            "segment": "chunks of it, hard cuts", "hold": "picture held for the beat"}
USER_MAX = 1.5                 # fit-and-render: your footage plays 1/1.5x .. 1.5x at most

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

def is_user(item):
    """Your own file (supplied to a beat, or one of your clips): fit-and-render, no interpretation."""
    return bool(item.get("user") or item.get("own_n") or (item.get("clip") or {}).get("own"))

def user_layout(sd, items, d, mode="auto"):
    """Fit-and-render for your own media: mechanical fitting only, never a substitute or an AI still.
    Footage plays at real speed (1.0x), sped up or slowed by up to 1.5x, trimmed, cut into 2-3 chunks (hard cuts), looped or held
    on its last frame; pictures are held for their share of the beat (no pan / zoom). Several files: hard cuts in your order."""
    lens = []
    for it in items:
        pth = src_path(sd, it)
        try: lens.append(max(0.2, media.dur(pth) - 0.1) if pth else None)   # a frame's margin: never ask for a time past the last frame
        except Exception: lens.append(None)
    vids = [i for i, L in enumerate(lens) if L]; out = []
    def emit(i, props, length): out.append((items[i], props, round(sum(x[3] for x in out), 3), length))
    if not vids:
        for i in range(len(items)): emit(i, {}, d / len(items))
        return out, "hold", "your picture(s) held for the beat, no motion added"
    if len(vids) < len(items):   # footage at real speed (trimmed if it doesn't fit), pictures share the rest (1.5 s each at least)
        rest = len(items) - len(vids); room = max(0.5, d - 1.5 * rest); nat = sum(lens[i] for i in vids); k = min(1.0, room / nat)
        left = max(0.0, d - nat * k)
        for i in range(len(items)):
            if i in vids: emit(i, {"rate": 1.0, **({"start": round(lens[i] * (1 - k) / 2, 3)} if k < 1 else {})}, lens[i] * k)
            else: emit(i, {}, left / rest)
        return out, "direct", "your footage at real speed, your pictures fill the rest"
    total = sum(lens); r = total / d; delta = d - total; why = ""
    if mode in ("auto", "direct") and abs(delta) <= 0.3: mode, why = "direct", "your footage is as long as the beat"
    elif mode == "auto":
        if delta < 0: mode = "speed" if r <= USER_MAX else ("trim" if r <= 2.5 else "segment")
        else: mode = "slow" if r >= 1 / USER_MAX else ("loop" if total >= 2.0 else "freeze")
        why = f"your footage is {abs(delta):.1f}s {'longer' if delta < 0 else 'shorter'} than the beat"
    if mode == "still": mode = "freeze"   # never fill with an AI still: the last frame of your footage holds
    if delta < -0.3 and mode in ("slow", "freeze", "loop", "direct"): mode = "trim"
    if delta > 0.3 and mode in ("trim", "speed", "segment", "direct"): mode = "freeze"
    last = len(items) - 1
    if mode == "direct":
        f = r   # within 0.3 s: a hair faster / slower so it ends with the beat
        for i in range(len(items)): emit(i, {"rate": round(f, 4)}, lens[i] / f)
    elif mode == "speed":
        f = min(USER_MAX, r); k = min(1.0, d / (total / f))
        for i in range(len(items)): emit(i, {"rate": round(f, 4), **({"start": round(lens[i] * (1 - k) / 2, 3)} if k < 1 else {})}, lens[i] / f * k)
    elif mode == "trim":
        for i in range(len(items)): a = lens[i] * d / total; emit(i, {"rate": 1.0, "start": round((lens[i] - a) / 2, 3)}, a)
    elif mode == "segment":   # 2-3 evenly spaced chunks of each file, hard cut together (more of the footage than one trimmed piece)
        n = 2 if r < 4 else 3
        for i in range(len(items)):
            a = lens[i] * d / total; c = a / n
            for j in range(n): emit(i, {"rate": 1.0, "start": round(max(0.0, lens[i] - c - 0.05) * j / (n - 1), 3)}, c)
    elif mode == "slow":
        f = max(1 / USER_MAX, r); alloc = [L / f for L in lens]; extra = max(0.0, d - sum(alloc))
        for i in range(len(items)):
            pr = {"rate": round(f, 4)}
            if i == last and extra > 0.05: pr["freezeAt"] = round(alloc[i] - 0.05, 3)
            emit(i, pr, alloc[i] + (extra if i == last else 0))
    elif mode == "loop":
        for i in range(len(items)):
            pr = {"rate": 1.0}
            if i == last: pr["loop"] = round(lens[i], 3)
            emit(i, pr, lens[i] + (max(0.0, delta) if i == last else 0))
    else:   # freeze
        mode = "freeze"
        for i in range(len(items)):
            pr = {"rate": 1.0}
            if i == last: pr["freezeAt"] = round(lens[i] - 0.05, 3)
            emit(i, pr, lens[i] + (max(0.0, delta) if i == last else 0))
    # each shot keeps playing 0.4 s under the next one (Teaser), so footage that is used to its end would run past its last
    # frame there (Remotion: "No frame found"): hold the last frame instead
    for it, pr, st, ln in out:
        if src_path(sd, it) and "loop" not in pr and "freezeAt" not in pr: pr["freezeAt"] = round(max(0.05, ln - 0.05), 3)
    return out, mode, why or FIT_NAME.get(mode, mode)

def layout(sd, items, d, mode="auto", vo="", filler=None):
    """-> (list of (item, props, start, length), mode used, why). props: rate / start / freezeAt / loop for videos.
    Your own files (fit-and-render) go to user_layout: mechanical fitting only."""
    if items and all(is_user(it) for it in items): return user_layout(sd, items, d, mode)
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
    if mode == "segment": mode = "trim"   # chunking is for your own footage (user_layout)
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
    for rung in ("parallax", "still", "photo", "current", "supplied"):
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
    else:
        bg = {"type": "graphic", "g": item["g"]}
        if item.get("tag"): bg["tag"] = item["tag"]   # ILLUSTRATION / SILHOUETTE
    if is_user(item):   # fit-and-render: no motion added (unless you asked for it), hard cuts, labelled as yours
        bg["user"] = True
        if item.get("move"): bg["still"] = False
        if t in ("video", "stock"): bg["tag"] = item.get("tag") or "YOUR FOOTAGE"; bg.setdefault("rate", 1.0)
        elif t == "image": bg["tag"] = item.get("tag") or "FILE"
    bg.update(props); bg["from"] = round(start, 3)
    return bg

def _tall(sd):
    from .ladder import space
    sp = space(sd); return sp["h"] > sp["w"]

# ---------------------------------------------------------------- job kinds and timelines
def outputs(job):
    """Finished outputs the editor can open: ["short", "long"] (either or both)."""
    if _iv(job): return _ie().outputs(job)
    from .pipeline import Job
    s = Job(job).state; out = []
    if s.get("short_output") and (Path(job) / "short" / "public" / "teaser.json").exists(): out.append("short")
    if s.get("output") and Path(s["output"]).exists() and _long_kind(job): out.append("long")
    return out

def v2():
    """config post_edit_v2: explainer slot editing, the Short/Explainer switch and the extra chat actions (off = editor as before)."""
    from . import config
    return bool(config.load().get("post_edit_v2", False))

def _long_kind(job):
    """'explainer' (Remotion timeline: build/public/teaser.json newer than any FFmpeg section) | 'long' (FFmpeg sections) | None."""
    b = Path(job) / "build"; tj = b / "public" / "teaser.json"; secs = list(b.glob("sec_*.mp4"))
    if not v2(): return "long" if secs else None   # as before: only FFmpeg-stitched long videos have editable slots
    if tj.exists() and (not secs or tj.stat().st_mtime >= max(p.stat().st_mtime for p in secs)): return "explainer"
    return "long" if secs else None

def kind(job):
    """short | explainer | long | None. A job with both outputs edits the one in state 'edit_target' (default: the Short)."""
    if _iv(job): return _ie().kind(job)
    from .pipeline import Job
    s = Job(job).state; outs = outputs(job)
    if "short" in outs and (s.get("edit_target") != "long" or "long" not in outs or not v2()): return "short"
    if "long" in outs: return _long_kind(job)
    return None

def set_target(job, target):
    if _iv(job): return _ie().set_target(job, target)
    from .pipeline import Job
    if not v2(): raise ValueError("switching between the Short and the explainer is off (setting post_edit_v2)")
    if target not in ("short", "long"): raise ValueError("target must be short or long")
    if target not in outputs(job): raise ValueError(f"this job has no finished {'Short' if target == 'short' else 'long video'}")
    Job(job).save(edit_target=target)

TL = {"short": ("short/public", "short_output"), "explainer": ("build/public", "output")}   # Remotion timelines: public dir, state key

def _tl_pub(job, k): return Path(job) / TL[k][0]
def _tl_out(job, k):
    from .pipeline import Job
    return Path(Job(job).state[TL[k][1]])
def _tl_json(job, k): return json.loads((_tl_pub(job, k) / "teaser.json").read_text(encoding="utf-8"))

def _fr(x): return max(1, math.floor(x * FPS_S + 0.5))   # Math.round in the Teaser composition (halves round up)

def _slots(beat):
    """[(slot, [bg indexes])] of a Teaser beat: bgs that replaced one visual slot carry its number ("slot"); untouched bgs are their own slot."""
    out = []
    for i, bg in enumerate(beat["bgs"]):
        sl = bg.get("slot", i)
        if out and out[-1][0] == sl: out[-1][1].append(i)
        else: out.append((sl, [i]))
    return out

def explainer_layout(job):
    """Visual slots of a Remotion explainer: [{id, sid, si, vi, start, dur, label, vo, editable, visual, beat}] (seconds of the output)."""
    from .pipeline import Job
    tz = _tl_json(job, "explainer"); plan = Job(job).plan(); secs = plan["sections"]; out = []
    beats = [b for b in tz["beats"] if b["id"] != "end"]
    for si, b in enumerate(beats):
        if si >= len(secs): break
        sec = secs[si]; vis = ([{"id": "_title", "type": "chart"}] if si == 0 else []) + list(sec["visuals"])
        gs = _slots(b)
        for gi, (slot, idx) in enumerate(gs):
            f0 = b["bgs"][idx[0]]["from"]; f1 = b["bgs"][gs[gi + 1][1][0]]["from"] if gi + 1 < len(gs) else b["dur"]
            v = vis[slot] if slot < len(vis) else {}
            vo = " ".join(w[0] for w in b["words"] if f0 <= w[1] < f1)
            out.append({"id": f"{sec['id']}_{slot}", "sid": sec["id"], "si": si, "vi": slot, "start": round(b["start"] + f0, 3), "dur": round(f1 - f0, 3),
                        "label": sec["title"], "vo": (vo or sec["vo"])[:600], "editable": not str(v.get("id", "")).startswith("_"), "visual": v,
                        "beat": b["id"], "f0": f0, "f1": f1})
    return out

def tl_frames(job, k):
    """Frame ranges [a, e) of every editable unit of a Remotion timeline (Short beats; explainer slots + end card), and the total."""
    tz = _tl_json(job, k)
    return short_frames(tz) if k == "short" else _frames_of(tz)

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
    if _long_kind(job) == "explainer": return explainer_layout(job)
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

def _is_own(bg):
    """A timeline background that is your own footage (clips.py): media/stock/own<N>_<beat>.mp4, own/own<N>.mp4, broll/own/..."""
    return bool(re.search(r"(^|/)own\d+(_|\.)|/own/", str(bg.get("src") or "")))

def _vis_source(v):
    """Editor-only note: where a long/explainer slot's picture came from (type, prompt, file, credit)."""
    if not v:
        return ""
    t = str(v.get("type") or v.get("kind") or "")
    lab = {"photo": "Photo", "image": "Image", "video": "Video", "chart": "Chart", "graphic": "Graphic",
           "generated": "AI image", "still": "AI image", "layers": "Layered image"}.get(t, t or "Picture")
    bits = [lab]
    if v.get("prompt"):
        bits.append("prompt: " + str(v["prompt"])[:120])
    src = v.get("src") or v.get("file") or v.get("img") or ""
    if src:
        bits.append(Path(str(src)).name)
    if v.get("credit"):
        bits.append(str(v["credit"]))
    return " · ".join(bits)


def _bg_source(bgs, sec):
    """Editor-only note for a Short beat: its timeline backgrounds (type, tag/credit, file), plus the
    plan section's AI-image prompt when the picture was generated."""
    notes = []
    for bg in bgs or []:
        it = _bg_item(bg)
        if not it:
            continue
        lab = {"video": "Video", "image": "Image", "layers": "Layered image", "graphic": "Graphic"}.get(it["type"], it["type"])
        det = it.get("tag") or it.get("short_credit") or ""
        src = it.get("src") or (it.get("layers") or [""])[0]
        n = lab + (f" · {det}" if det else "") + (f" · {Path(src).name}" if src else "")
        if n not in notes:
            notes.append(n)
    for v in (sec or {}).get("visuals") or []:
        if v.get("prompt"):
            n = "AI image · prompt: " + str(v["prompt"])[:120]
            if n not in notes:
                notes.append(n)
    return "; ".join(notes)


def beats(job):
    """The timeline for the job page: {kind, beats: [{id, start, dur, label, editable}]}."""
    if _iv(job): return _ie().beats(job)
    k = kind(job)
    if k == "short":
        tz = _teaser(job)
        from .pipeline import Job
        plan = Job(job).short_plan() or {"sections": []}
        vo = {s["id"]: s["vo"] for s in plan["sections"]}; cta = {s["id"] for s in plan["sections"] if s.get("cta")}
        secs = {s["id"]: s for s in plan["sections"]}
        return {"kind": "short", "beats": [{"id": b["id"], "start": b["start"], "dur": b["dur"], "label": f"Beat {i + 1}", "vo": vo.get(b["id"], ""),
                                             "editable": b["id"] not in cta, "own": any(_is_own(g) for g in b["bgs"]),
                                             "source": _bg_source(b["bgs"], secs.get(b["id"]))} for i, b in enumerate(tz["beats"])]}
    if k in ("long", "explainer"):
        tz = _tl_json(job, "explainer") if k == "explainer" else None
        def own(b):
            if b["visual"].get("own"): return True
            if not tz: return False
            tb = next((x for x in tz["beats"] if x["id"] == b.get("beat")), None)
            idx = next((ix for sl, ix in _slots(tb) if sl == b["vi"]), []) if tb else []
            return any(_is_own(tb["bgs"][i]) for i in idx)
        return {"kind": k, "beats": [dict({k2: b[k2] for k2 in ("id", "start", "dur", "label", "vo", "editable")}, own=own(b), source=_vis_source(b.get("visual"))) for b in long_layout(job)]}
    return {"kind": None, "beats": []}

# ---------------------------------------------------------------- workspaces (where a beat's candidates live)
def workspace(job, k=None):
    """Shorts: the job itself (short/review). Long videos: job/longedit, a Short-like workspace in 16:9."""
    k = k or kind(job)
    return Path(job) if k == "short" else Path(job) / "longedit"

def open_beat(job, bid, cfg, log):
    """Make sure the beat has a review entry with its current visual among the candidates, and thumbnails. -> rv"""
    if _iv(job): return _ie().open_beat(job, bid, cfg, log)
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
            if not b.get("current") and (b.get("chosen") if b.get("decision") == "chosen" else b.get("auto")):
                b["current"] = list(b["chosen"] if b.get("decision") == "chosen" else b["auto"])   # reviewed job: its pick is what the video shows
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
            if not b.get("current") and k == "explainer":   # what the video shows now: the slot's backgrounds from the timeline
                tz = _tl_json(job, "explainer"); tb = next(x for x in tz["beats"] if x["id"] == lb["beat"])
                idx = next(ix for sl, ix in _slots(tb) if sl == lb["vi"])
                cur = [review._add(rv, bid, it, "current", True, "in the video now")
                       for it in (_bg_item_from(tb["bgs"][i], _tl_pub(job, "explainer"), sd, f"{bid}_{n}") for n, i in enumerate(idx)) if it]
                b["current"] = cur; b["auto"] = cur
                review._add(rv, bid, b["skip_item"], "headline", True, "text card summing up the beat")
            if not b.get("current"):
                src = job / "build" / f"v_{lb['sid']}_{lb['vi']}.mp4"; dst = sd / "current" / f"{bid}.mp4"; dst.parent.mkdir(parents=True, exist_ok=True)
                if src.exists() and not dst.exists(): shutil.copy2(src, dst)
                cur = [review._add(rv, bid, {"type": "video", "src": f"current/{bid}.mp4", "tag": "", "rate": 1.0}, "current", True, "in the video now")] if dst.exists() else []
                b["current"] = cur; b["auto"] = cur
                review._add(rv, bid, b["skip_item"], "headline", True, "text card summing up the beat")
        try:   # your own clips (own_clips) as one-click candidates on every beat
            from . import clips as _clips
            _clips.offer(job, sd, rv, bid, cfg, log)
        except Exception as e: log(f"  your clips not offered for {bid} ({str(e)[:80]})")
        for cid in b["cands"]:   # files of unused treatments may have been cleaned up
            rv["cands"][cid]["missing"] = not _item_exists(sd, rv["cands"][cid]["item"])
        review.save(ws, rv)
    review.thumbs(ws, cfg, log, [c for c in rv["beats"][bid]["cands"] if not rv["cands"][c].get("missing")])
    return review.load(ws)

def _bg_item_from(bg, pub, sd, name):
    """An explainer timeline background -> a candidate item in the edit workspace (media copied to <sd>/current/)."""
    t = bg.get("type"); cur = Path(sd) / "current"; cur.mkdir(parents=True, exist_ok=True)
    def take(rel):
        src = Path(pub) / rel; dst = cur / f"{name}{src.suffix.lower()}"
        if src.exists() and not dst.exists(): shutil.copy2(src, dst)
        return f"current/{dst.name}" if dst.exists() else None
    if t == "video":
        p = take(bg["src"]); return p and {"type": "video", "src": p, "tag": bg.get("tag", ""), "rate": bg.get("rate", 1.0)}
    if t == "image":
        p = take(bg["src"]); return p and {"type": "image", "src": p, "fit": bg.get("fit", "frame"), "tag": bg.get("tag", ""), "short_credit": bg.get("credit", "")}
    if t == "graphic": return {"type": "graphic", "g": bg["g"], **({"tag": bg["tag"]} if bg.get("tag") else {})}
    if t == "layers":
        ls = []
        for i, x in enumerate(bg["layers"]):
            src = Path(pub) / x; dst = cur / f"{name}_L{i}{src.suffix.lower()}"
            if src.exists() and not dst.exists(): shutil.copy2(src, dst)
            if not dst.exists(): return None
            ls.append(f"current/{dst.name}")
        return {"type": "layers", "layers": ls, **({"tag": bg["tag"]} if bg.get("tag") else {})}
    return None

def _bg_item(bg):
    """A timeline background back to a candidate item (paths relative to the short folder)."""
    t = bg.get("type")
    if t == "video": return {"type": "video", "src": "public/" + bg["src"], "tag": bg.get("tag", ""), **({"rate": bg["rate"]} if bg.get("rate") else {})}
    if t == "image": return {"type": "image", "src": "public/" + bg["src"], "fit": bg.get("fit", "frame"), "tag": bg.get("tag", ""), "short_credit": bg.get("credit", "")}
    if t == "layers": return {"type": "layers", "layers": ["public/" + x for x in bg["layers"]], "tag": bg.get("tag", "")}
    if t == "graphic": return {"type": "graphic", "g": bg["g"], **({"tag": bg["tag"]} if bg.get("tag") else {})}
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


def _iv(job):
    """An interview job (interview_edit.py) - its own pieces, candidates and re-assembly."""
    try:
        from .interview_edit import is_interview
        return is_interview(job)
    except Exception: return False


def _ie():
    from . import interview_edit
    return interview_edit

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
    if _iv(job): return _ie().preview(job, bid, cids, fit, cfg, log)
    from . import review
    k, ws, sd, rv, d, lay, mode, why = _plan_beat(job, bid, cids, fit, cfg)
    pd = Path(job) / "edit" / "previews"; pd.mkdir(parents=True, exist_ok=True)
    out = pd / f"{bid}_{int(time.time())}.mp4"
    if k in TL:
        tz, (a, e) = _tl_props(job, k, sd, bid, lay, dest=None)
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
    return _tl_props(job, "short", sd, bid, lay, dest)

def _tl_props(job, k, sd, bid, lay, dest):
    """Teaser props with this beat's (Short) / visual slot's (explainer) backgrounds replaced (media as http URLs for the preview
    renderer). -> (props, (a, e)), or with dest (the real splice) (props, (a, e), timeline to save)"""
    from . import review
    tz = _tl_json(job, k); pub = _tl_pub(job, k)
    story = _story(job)
    bgs = [to_bg(sd, it, p, s0, story, dest=dest) for it, p, s0, _ in lay]
    if k == "short":
        for b in tz["beats"]:
            if b["id"] == bid: b["bgs"] = bgs
        changed = bid
    else:   # explainer: replace one slot inside its section beat; the new bgs keep the slot number so the layout stays stable
        lb = next(x for x in explainer_layout(job) if x["id"] == bid); b = next(x for x in tz["beats"] if x["id"] == lb["beat"])
        for i, bg in enumerate(b["bgs"]): bg.setdefault("slot", i)
        idx = next(ix for sl, ix in _slots(b) if sl == lb["vi"])
        for bg in bgs: bg["from"] = round(lb["f0"] + bg["from"], 3); bg["slot"] = lb["vi"]
        b["bgs"] = b["bgs"][:idx[0]] + bgs + b["bgs"][idx[-1] + 1:]
        changed = lb["beat"]
    frames = short_frames(tz)[0] if k == "short" else _frames_of(tz)[0]
    a, e = next((x[1], x[2]) for x in frames if x[0] == bid)
    bid = changed
    props = json.loads(json.dumps(tz))
    base = review.files_url(pub) + "/"; sdbase = review.files_url(sd) + "/"
    if k == "explainer": props["progress"] = False
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

def _frames_of(tz):
    """tl_frames for an explainer timeline already in memory."""
    total = int(-(-tz["total"] * FPS_S // 1)); out = []
    for i, b in enumerate(tz["beats"]):
        gs = _slots(b) if b["id"] != "end" else [(0, list(range(len(b["bgs"]))))]
        nxt = _fr(tz["beats"][i + 1]["start"]) if i + 1 < len(tz["beats"]) else total
        for gi, (slot, idx) in enumerate(gs):
            st = b["start"] + b["bgs"][idx[0]]["from"] if b["bgs"] else b["start"]
            a = _fr(st) if st > 0 else 0
            e = _fr(b["start"] + b["bgs"][gs[gi + 1][1][0]]["from"]) if gi + 1 < len(gs) else nxt
            out.append((b["id"] if b["id"] == "end" else f"{b['id']}_{slot}", a, e))
    return out, total

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
    m = re.search(r"\d+", o or "")   # some ffprobe builds print "412," here
    return int(m.group()) if m else 0

def ensure_keyframes(job, log, k="short"):
    """Remotion timelines (Short, explainer): one re-encode that puts a keyframe exactly on every beat / slot boundary, so a beat can
    be swapped without re-encoding the rest. Done on the first edit of a video (Shorts rendered before this existed, every explainer)."""
    job = Path(job); outp = _tl_out(job, k); kf = job / "edit" / ("keyframes.json" if k == "short" else f"keyframes_{k}.json")
    frames, total = tl_frames(job, k)
    stamp = {"size": outp.stat().st_size, "mtime": int(outp.stat().st_mtime), "frames": [a for _, a, _ in frames], "kfv": 2}
    if kf.exists() and json.loads(kf.read_text(encoding="utf-8")) == stamp: return
    log(f"Preparing the {'Short' if k == 'short' else 'explainer'} for editing (keyframes on beat boundaries, one time)...")
    t0 = time.time(); tmp = outp.with_name("_kf_" + outp.name)
    times = _kf_times(a for _, a, _ in frames)
    media.ff("-i", outp, "-map", "0:v", "-map", "0:a?", *ENC_S, "-force_key_frames", times, "-forced-idr", 1, "-c:a", "copy", "-movflags", "+faststart", tmp, timeout=7200)
    replace_file(tmp, outp, log)
    _stamp_keyframes(job, k)
    log(f"  done in {time.time() - t0:.0f}s")

def _kf_times(frames):
    """-force_key_frames times for these frame numbers: half a frame early, so a time like 29.566667 (frame 887 = 29.5666...)
    doesn't round past the frame and put the keyframe on the next one (then every splice fell back to a full re-encode)."""
    return ",".join(f"{(a - 0.5) / FPS_S:.6f}" for a in frames if a > 0)

def _stamp_keyframes(job, k):
    job = Path(job); outp = _tl_out(job, k); kf = job / "edit" / ("keyframes.json" if k == "short" else f"keyframes_{k}.json")
    kf.parent.mkdir(parents=True, exist_ok=True)
    kf.write_text(json.dumps({"size": outp.stat().st_size, "mtime": int(outp.stat().st_mtime), "frames": [a for _, a, _ in tl_frames(job, k)[0]],
                              "kfv": 2}), encoding="utf-8")   # kfv 2: keyframes placed half a frame early (exact on the boundary)

def _clear_prev(job):
    for p in list(Path(job).glob("output/*.prev")) + list(Path(job).glob("short/public/*.prev")) + list(Path(job).glob("build/*.prev")):
        p.unlink(missing_ok=True)

def _vstats(p):
    """Frame count, audio fingerprint/duration and decode errors of a video (for checking a splice)."""
    import hashlib
    a = subprocess.run([media._bin("ffmpeg"), "-v", "error", "-i", str(p), "-map", "0:a:0", "-c", "copy", "-f", "data", "-"], capture_output=True).stdout
    try: ad = float(subprocess.run([media._bin("ffprobe"), "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=duration", "-of", "csv=p=0", str(p)],
                                   capture_output=True, text=True).stdout.strip().strip(",") or 0)
    except ValueError: ad = 0.0
    errs = subprocess.run([media._bin("ffmpeg"), "-v", "error", "-i", str(p), "-f", "null", "-"], capture_output=True, text=True).stderr.strip()
    return {"frames": _nframes(p), "audio_md5": hashlib.md5(a).hexdigest(), "audio_dur": ad, "decode_errors": len([l for l in errs.splitlines() if l.strip()])}

def _ostamp(p): p = Path(p); return {"size": p.stat().st_size, "mtime": int(p.stat().st_mtime)}

# ---------------------------------------------------------------- replacing the output file safely (Windows file locks)
LOCKED_MSG = "Can't replace the video file — it's open in another app. Close the player and retry."

class FileLocked(RuntimeError):
    pass

def locked(p):
    """True when another program holds the file open (Windows: an exclusive open fails with a sharing violation). Elsewhere False."""
    import os
    p = Path(p)
    if os.name != "nt" or not p.exists(): return False
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateFileW.restype = wintypes.HANDLE
        k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        h = k32.CreateFileW(str(p), 0x80000000 | 0x40000000 | 0x00010000, 0, None, 3, 0x80, None)   # read|write|DELETE, no sharing, OPEN_EXISTING
        if h in (None, wintypes.HANDLE(-1).value, -1, 0xFFFFFFFFFFFFFFFF):
            return ctypes.get_last_error() in (32, 33, 5)   # sharing / lock violation, access denied
        k32.CloseHandle(h); return False
    except Exception:
        return False

def replace_file(tmp, dst, log=print, wait=12.0):
    """Put tmp in place of dst. Never leaves a stray _edit_ / _kf_ file and never reports success unless dst really changed.
    1. dst locked by another app (player, Explorer preview, the page's own video stream): wait up to `wait` s for it to close,
       without trying the rename. 2. rename (atomic), retried a few times. 3. copy over dst in place (works while a reader shares
       the file for writing), with a backup copied back if that fails half-way. Fails with FileLocked (LOCKED_MSG)."""
    import os
    tmp, dst = Path(tmp), Path(dst); t0 = time.time(); said = False
    while locked(dst) and time.time() - t0 < wait:
        if not said: log(f"  {dst.name} is open in another app; waiting for it to close..."); said = True
        time.sleep(0.5)
    last = None
    if not locked(dst):
        for i in range(6):
            try: os.replace(tmp, dst); return "renamed"
            except PermissionError as e: last = e; time.sleep(0.4 * (i + 1))
    try:   # copy-over-write (a reader that shares write access, e.g. the server streaming the preview, doesn't block this)
        bak = dst.with_name("_bak_" + dst.name); shutil.copyfile(dst, bak)
        try:
            shutil.copyfile(tmp, dst)
            if dst.stat().st_size != tmp.stat().st_size: raise OSError("size mismatch after copy")
        except Exception:
            try: shutil.copyfile(bak, dst)
            except Exception: pass
            raise
        finally: bak.unlink(missing_ok=True)
        tmp.unlink(missing_ok=True); return "copied"
    except Exception as e:
        last = last or e
    tmp.unlink(missing_ok=True)   # no stray file next to the original; the original is unchanged
    log(f"  replace failed ({type(last).__name__}: {str(last)[:120]})")
    raise FileLocked(LOCKED_MSG)

def clean_leftovers(job):
    """Stray _edit_ / _kf_ / _bak_ files from older failed replaces."""
    for pat in ("_edit_*.mp4", "_kf_*.mp4", "_bak_*.mp4"):
        for d in (Path(job) / "output", Path(job) / "build"):
            for q in d.glob(pat) if d.exists() else []:
                try: q.unlink()
                except Exception: pass

# ---------------------------------------------------------------- undo stack (edit/history/NNN)
def _hroot(job): return Path(job) / "edit" / "history"

def history(job):
    """Applied edits that can be undone, oldest first: [{n, beat, kind, t, label}]."""
    if _iv(job): return []
    r = _hroot(job); out = []
    for d in sorted(r.glob("[0-9][0-9][0-9]")) if r.exists() else []:
        try: m = json.loads((d / "meta.json").read_text(encoding="utf-8")); out.append({"n": int(d.name), **{x: m.get(x) for x in ("beat", "kind", "t", "label")}})
        except Exception: pass
    return out

def _hnew(job):
    r = _hroot(job); r.mkdir(parents=True, exist_ok=True)
    n = max([int(d.name) for d in r.glob("[0-9][0-9][0-9]")] or [0]) + 1
    d = r / f"{n:03d}"; d.mkdir(); return d

def can_undo(job): return _ie().can_undo(job) if _iv(job) else (bool(history(job)) or any(Path(job).glob("output/*.prev")))

def status(job): return _busy.get(str(Path(job)), "")

def start_apply(job, bid, cids, fit, cfg, log):
    if _iv(job): return _ie().start_apply(job, bid, cids, fit, cfg, log)
    key = str(Path(job))
    with _lk:
        if _busy.get(key): return "Already applying an edit to this video."
        _busy[key] = f"Applying the new visual to {bid}..."
    def run():
        from .pipeline import Job
        try: apply(job, bid, cids, fit, cfg, log)
        except Exception as e:
            import traceback
            msg = LOCKED_MSG if isinstance(e, FileLocked) or "WinError 5" in str(e) or "WinError 32" in str(e) else str(e)[:300]
            log(f"Edit {bid} NOT applied: {msg} The video is unchanged.")
            if not isinstance(e, FileLocked): log(traceback.format_exc()[-800:])
            _busy[key + ":err"] = msg
            try: Job(job).save(edit_last={"beat": bid, "ok": False, "msg": msg, "t": time.time()})
            except Exception: pass
            try:
                from . import review
                ws = workspace(job)
                with review._lock(ws):
                    rv = review.load(ws)
                    if rv and bid in rv.get("beats", {}): rv["beats"][bid]["msg"] = f"Not applied: {msg}"; review.save(ws, rv)
            except Exception: pass
        finally: _busy[key] = ""
    _busy.pop(key + ":err", None)
    threading.Thread(target=run, daemon=True).start(); return ""

def apply(job, bid, cids, fit, cfg, log):
    """Render the beat with its new visual and splice it into the output MP4 in place (no re-render of other beats).
    What it replaces goes on the undo stack."""
    from . import review
    from .pipeline import Job
    job = Path(job); t0 = time.time()
    k, ws, sd, rv, d, lay, mode, why = _plan_beat(job, bid, cids, fit, cfg)
    user = all(is_user(rv["cands"][c]["item"]) for c in cids)
    log(f"Edit {bid}: {', '.join(RUNG(rv, c) for c in cids)} -> {'fit-and-render (your file, no AI): ' if user else ''}{FIT_NAME.get(mode, mode)} ({why})")
    clean_leftovers(job)
    _clear_prev(job)   # older single-step undo files: the stack replaces them
    outp = _tl_out(job, k) if k in TL else Path(Job(job).state["output"])
    pre = _vstats(outp)
    if not v2():   # as before: only the last edit can be undone (post_edit_v2 keeps every step)
        for h in history(job): shutil.rmtree(_hroot(job) / f"{h['n']:03d}", ignore_errors=True)
    hd = _hnew(job)
    try:
        b0 = (rv.get("beats", {}).get(bid) or {})
        meta = {"beat": bid, "kind": k, "t": time.strftime("%Y-%m-%d %H:%M"), "label": f"{bid}: {', '.join(RUNG(rv, c) for c in cids)}",
                "rv_state": {k2: b0.get(k2) for k2 in ("edit", "decision", "chosen", "current", "msg")}}
        if k in TL: meta.update(_apply_timeline(job, k, bid, sd, lay, cfg, log, hd))
        else: meta.update(_apply_long(job, bid, sd, lay, d, cfg, log, hd))
        meta["after"] = _ostamp(outp); meta["out"] = str(outp)
        (hd / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    except Exception:
        shutil.rmtree(hd, ignore_errors=True); raise
    with review._lock(ws):
        rv = review.load(ws); b = rv["beats"][bid]
        b["edit"] = {"cands": list(cids), "fit": mode, "why": why, "t": time.strftime("%H:%M")}
        b["decision"], b["chosen"] = "chosen", list(cids); b["current"] = list(cids)
        b["msg"] = f"Applied ({FIT_NAME.get(mode, mode)})."
        review.save(ws, rv)
    post = _vstats(outp)
    ver = {"frames_same": pre["frames"] == post["frames"], "decode_ok": post["decode_errors"] == 0,
           "audio_same": (pre["audio_md5"] == post["audio_md5"]) if k in TL else abs(pre["audio_dur"] - post["audio_dur"]) < 0.05,
           "frames": post["frames"]}
    j = Job(job); edits = j.state.get("edits", []); edits.append({"beat": bid, "fit": mode, "t": time.time(), "verify": ver, "kind": k, "h": int(hd.name), "user": user})
    j.save(edits=edits, edit_last={"beat": bid, "ok": True, "msg": f"Applied ({FIT_NAME.get(mode, mode)}).", "t": time.time()})
    log(f"Edit {bid}: applied - spliced into the video in {time.time() - t0:.0f}s; check: frames {'same' if ver['frames_same'] else 'CHANGED'}, "
        f"audio {'unchanged' if ver['audio_same'] else 'CHANGED'}, decoding {'clean' if ver['decode_ok'] else 'ERRORS'} (undo step {int(hd.name)})")

def RUNG(rv, cid):
    from .review import RUNG as R
    return R.get(rv["cands"][cid]["rung"], rv["cands"][cid]["rung"])

def _splice(job, k, outp, a, e, seg, log, keep_old=None):
    """Swap frames [a, e) of the output's video track for seg (exactly e - a frames, keyframe first) without re-encoding the rest;
    the narration track is kept as it is. keep_old: where to save the frames that were there (for undo). Replaces outp."""
    ed = Path(job) / "edit"; ed.mkdir(exist_ok=True)
    n = e - a; total = tl_frames(job, k)[1]
    parts = ed / "parts"; shutil.rmtree(parts, ignore_errors=True); parts.mkdir()
    cuts = [x / FPS_S - 0.001 for x in (a, e) if 0 < x < total]
    vcopy = ed / "video_only.mp4"; media.ff("-i", outp, "-map", "0:v", "-c", "copy", vcopy)
    if cuts: media.ff("-i", vcopy, "-c", "copy", "-f", "segment", "-segment_times", ",".join(f"{c:.6f}" for c in cuts), "-reset_timestamps", 1, parts / "p%03d.mp4")
    else: shutil.copy2(vcopy, parts / "p000.mp4")
    ps = sorted(parts.glob("p*.mp4")); mid = 1 if a > 0 else 0
    total_before = _nframes(vcopy)
    ok = len(ps) == len(cuts) + 1 and _nframes(ps[mid]) == n
    if keep_old is not None:
        if ok: shutil.copy2(ps[mid], keep_old)   # bit-exact old frames
        else: media.ff("-ss", f"{a / FPS_S:.6f}", "-i", vcopy, "-an", *ENC_S, "-frames:v", n, "-force_key_frames", "0", "-forced-idr", 1, keep_old)
    newv = ed / "video_new.mp4"
    if ok:
        lst = ed / "join.txt"; lst.write_text("".join(f"file '{(Path(seg) if i == mid else p).resolve().as_posix()}'\n" for i, p in enumerate(ps)), encoding="utf-8")
        media.ff("-f", "concat", "-safe", 0, "-i", lst, "-c", "copy", newv)
        ok = _nframes(newv) == total_before
    if not ok:   # keyframes not where expected: re-encode the video track with the segment overlaid (slower, always correct)
        log("  keyframes didn't line up; re-encoding the video track once (slower)")
        times = _kf_times(x for _, x, _ in tl_frames(job, k)[0])
        media.ff("-i", vcopy, "-i", seg, "-filter_complex", f"[1:v]setpts=PTS-STARTPTS+{a / FPS_S:.6f}/TB[s];[0:v][s]overlay=eof_action=pass:enable='between(n,{a},{e - 1})'[v]",
                 "-map", "[v]", *ENC_S, "-force_key_frames", times, "-forced-idr", 1, newv, timeout=7200)
    tmp = outp.with_name("_edit_" + outp.name)
    media.ff("-i", newv, "-i", outp, "-map", "0:v", "-map", "1:a?", "-c", "copy", "-movflags", "+faststart", tmp)
    if abs(_nframes(tmp) - total_before) > 0: tmp.unlink(missing_ok=True); raise RuntimeError("the edited video has a different length; the original is unchanged")
    try: how = replace_file(tmp, outp, log)
    finally:
        for p in (vcopy, newv): Path(p).unlink(missing_ok=True)
        shutil.rmtree(parts, ignore_errors=True)
    if how == "copied": log("  (the video was open elsewhere: written over it in place)")

def _apply_short(job, bid, sd, lay, cfg, log, hd=None):
    return _apply_timeline(job, "short", bid, sd, lay, cfg, log, hd)

def _apply_timeline(job, k, bid, sd, lay, cfg, log, hd):
    """Short beat / explainer slot: render its frames with the new backgrounds, splice them in, save the timeline. -> undo meta"""
    from .pipeline import Job
    job = Path(job); outp = _tl_out(job, k); ed = job / "edit"; ed.mkdir(exist_ok=True)
    ensure_keyframes(job, log, k)
    pub = _tl_pub(job, k); used = []
    props, (a, e), tz = _tl_props(job, k, sd, bid, lay, dest=pub)
    n = e - a
    raw = ed / "seg_raw.mp4"; seg = ed / "seg.mp4"
    _render(job, "Teaser", props, raw, cfg, log, frames=(a, e - 1), scale=1.0, audio=False)
    media.ff("-i", raw, "-an", *ENC_S, "-frames:v", n, "-force_key_frames", "0", "-forced-idr", 1, seg)
    if _nframes(seg) != n: raise RuntimeError(f"rendered {_nframes(seg)} frames for the beat, expected {n}")
    shutil.copy2(pub / "teaser.json", hd / "teaser.json")
    _splice(job, k, outp, a, e, seg, log, keep_old=hd / "old.mp4")
    (pub / "teaser.json").write_text(json.dumps(tz, indent=1, ensure_ascii=False), encoding="utf-8")
    meta = {"a": a, "e": e}
    if k == "short":
        uf = job / "short" / "used.json"; u = set(json.loads(uf.read_text(encoding="utf-8"))) if uf.exists() else set()
        uf.write_text(json.dumps(sorted(u | set(used)), indent=1), encoding="utf-8")
    else:   # remembered in the plan, so a full re-render of the explainer keeps the edit (explainer.build reads edit_bgs)
        j = Job(job); plan = j.plan(); lb = next(x for x in explainer_layout(job) if x["id"] == bid)
        tb = next(x for x in tz["beats"] if x["id"] == lb["beat"])
        idx = next(ix for sl, ix in _slots(tb) if sl == lb["vi"])
        vi = lb["vi"] - (1 if lb["si"] == 0 else 0)
        if 0 <= vi < len(plan["sections"][lb["si"]]["visuals"]):
            v = plan["sections"][lb["si"]]["visuals"][vi]
            meta["plan_prev"] = {"si": lb["si"], "vi": vi, "edit_bgs": v.get("edit_bgs"), "edit_slot": v.get("edit_slot")}
            v["edit_bgs"] = [dict({x: y for x, y in tb["bgs"][i].items() if x != "slot"}, **{"from": round(tb["bgs"][i]["from"] - lb["f0"], 3)}) for i in idx]
            v["edit_slot"] = round(lb["f1"] - lb["f0"], 3)
            j.save_plan(plan)
    _stamp_keyframes(job, k)
    for p in (raw, seg): Path(p).unlink(missing_ok=True)
    return meta

def _apply_long(job, bid, sd, lay, d, cfg, log, hd=None):
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
    meta = {"vclip": vclip.name, "secf": secf.name, "si": lb["si"], "vid": lb["visual"].get("id")}
    if hd is not None:
        for p in (vclip, secf):
            if p.exists(): shutil.copy2(p, hd / p.name)
    keep = ed / "clips" / f"{vclip.stem}_{int(time.time())}.mp4"; keep.parent.mkdir(exist_ok=True)
    media.ff("-i", raw, "-an", "-vf", f"fps={assemble.FPS},scale={assemble.W}:{assemble.H},setsar=1,tpad=stop_mode=clone:stop_duration=1,trim=duration={lb['dur']:.3f}",
             "-frames:v", nfr, *assemble.ENC, keep)
    shutil.copy2(keep, vclip)
    # remembered in the plan, so a full rebuild keeps the edit
    for v in plan["sections"][lb["si"]]["visuals"]:
        if v is not None and v.get("id") == lb["visual"].get("id"): meta["edit_clip_prev"] = v.get("edit_clip"); v["edit_clip"] = keep.relative_to(job).as_posix()
    j.save_plan(plan)
    secf.unlink(missing_ok=True)
    s = j.state
    segs = json.loads((job / "presenter" / "segments.json").read_text()) if s.get("presenter") and (job / "presenter" / "segments.json").exists() else []
    assemble.section(job, lb["si"], plan["sections"][lb["si"]], plan["sections"], segs, s.get("captions", True), log)
    _rejoin_long(job, plan, outp)
    raw.unlink(missing_ok=True)
    return meta

def _rejoin_long(job, plan, outp):
    b = Path(job) / "build"
    parts = [b / f"sec_{x['id']}.mp4" for x in plan["sections"]]
    lst = b / "final.txt"; lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    media.ff("-f", "concat", "-safe", 0, "-i", lst, "-an", "-c:v", "copy", b / "final_video.mp4")
    tmp = outp.with_name("_edit_" + outp.name)
    media.ff("-i", b / "final_video.mp4", "-i", b / "final_audio.wav", "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
             "-shortest", "-movflags", "+faststart", tmp)
    replace_file(tmp, outp)

def undo(job, log):
    """Undo the newest edit still on the stack (repeat to go further back); older jobs fall back to their single .prev copy."""
    if _iv(job): return _ie().undo(job, log)
    job = Path(job)
    from .pipeline import Job
    from . import review
    j = Job(job); hs = history(job)
    if not hs: return _undo_prev(job, log)
    hd = _hroot(job) / f"{hs[-1]['n']:03d}"; m = json.loads((hd / "meta.json").read_text(encoding="utf-8")); k = m["kind"]
    outp = _tl_out(job, k) if k in TL else Path(j.state["output"])
    if _ostamp(outp) != m.get("after"):
        raise ValueError("the video changed since that edit (a full re-render, or a file was replaced), so it can't be undone step by step")
    if k in TL:
        ensure_keyframes(job, log, k)   # no-op: the boundaries are still keyframes
        _splice(job, k, outp, m["a"], m["e"], hd / "old.mp4", log)
        shutil.copy2(hd / "teaser.json", _tl_pub(job, k) / "teaser.json")
        pp = m.get("plan_prev")
        if pp:
            plan = j.plan(); v = plan["sections"][pp["si"]]["visuals"][pp["vi"]]
            for key in ("edit_bgs", "edit_slot"):
                if pp.get(key) is None: v.pop(key, None)
                else: v[key] = pp[key]
            j.save_plan(plan)
        _stamp_keyframes(job, k)
    else:
        b = job / "build"; plan = j.plan()
        for nm in (m["vclip"], m["secf"]):
            if (hd / nm).exists(): shutil.copy2(hd / nm, b / nm)
        for v in plan["sections"][m["si"]]["visuals"]:
            if v is not None and v.get("id") == m.get("vid"):
                if m.get("edit_clip_prev"): v["edit_clip"] = m["edit_clip_prev"]
                else: v.pop("edit_clip", None)
        j.save_plan(plan); _rejoin_long(job, plan, outp)
    ws = workspace(job, k if k in ("short",) else "long")
    with review._lock(ws):   # the beat's record goes back too, so a full re-render doesn't bring the undone edit back
        rv = review.load(ws); b = (rv or {}).get("beats", {}).get(m["beat"])
        if b:
            for k2, v in (m.get("rv_state") or {}).items():
                if v is None: b.pop(k2, None)
                else: b[k2] = v
            b["msg"] = "Edit undone."
            review.save(ws, rv)
    edits = j.state.get("edits", [])
    if edits: edits.pop(); j.save(edits=edits)
    shutil.rmtree(hd, ignore_errors=True)
    for h in reversed(history(job)):   # the next step down on the same video: its content is back, under a new file stamp
        mf = _hroot(job) / f"{h['n']:03d}" / "meta.json"; m2 = json.loads(mf.read_text(encoding="utf-8"))
        if m2.get("out", str(outp)) == str(outp):
            m2["after"] = _ostamp(outp); mf.write_text(json.dumps(m2, indent=1), encoding="utf-8"); break
    log(f"Edit undone ({m.get('label', m['beat'])}); {len(hs) - 1} earlier edit(s) can still be undone")

def _undo_prev(job, log):
    """Edits made before the undo stack existed: one step back from the .prev copies."""
    k = kind(job)
    from .pipeline import Job
    j = Job(job)
    if k == "short": files = [Path(j.state["short_output"]), job / "short" / "public" / "teaser.json"]
    else: files = [Path(j.state["output"])] + list((job / "build").glob("v_*.mp4")) + list((job / "build").glob("sec_*.mp4"))
    done = 0
    for p in files:
        pv = p.with_name(p.name + ".prev")
        if pv.exists(): shutil.copy2(pv, p); pv.unlink(); done += 1
    if not done: raise ValueError("nothing to undo")
    if k == "short" and (job / "edit" / "keyframes.json").exists(): _stamp_keyframes(job, "short")
    edits = j.state.get("edits", [])
    if edits: edits.pop(); j.save(edits=edits)
    from . import review
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
