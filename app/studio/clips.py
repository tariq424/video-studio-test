"""Your own footage, matched to beats ("Provide clips" on the job form; config own_clips, default off).

You give a text description (the script is written from it as for any pasted text) plus one or more video files, and optionally a
note on which clip goes where ("clip 1 is the church exterior, clip 2 is the interior through the bars"). After the script exists:

  1. describe   every clip is probed (length, size) and, unless your note already says what it shows, looked at once by the
                clip-checking vision model (4 frames -> one sentence). Cached in src/clips/clips.json.
  2. match      which beats your footage covers:
                  - structured note ("clip1=beat3, clip2=beat5,6")      -> taken literally
                  - free-text note or no note                          -> the script AI (DeepSeek; local model when no key) reads the
                                                                          beats, the clip descriptions and your note and assigns
                                                                          clips to the beats they actually show
                  - no AI available                                    -> word overlap between clip descriptions and narration
                A clip can cover several beats (successive parts of it). Beats with no matching clip stay with the visual
                ladder (stock, photos, illustrations, simulations, cards). Written to src/clips/match.json.
  3. place      Shorts: each covered beat gets its part of the clip, cut to 1080x1920 into short/stock/clips/own<N>_<beat>.mp4,
                listed in pick.json like vetted stock (so the timeline, review panel, editor and splice treat it as footage),
                marked own=True: no ILLUSTRATIVE label, review rung "Your footage". Stock search skips covered beats.
                Explainers: the covered section's AI still/motion slots get successive parts of the clip (1920x1080,
                broll/own/), before the stock B-roll search, so those slots are never searched or generated.
  4. offer      in the timeline editor every clip is a one-click candidate ("Your footage") on every beat, to move or override
                the automatic placement.

Nothing here runs unless the job was created with clips (and own_clips is on)."""
import json, math, re, shutil
from pathlib import Path
from . import media

VIDEO_EXT = (".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".mts", ".m2ts")
HINT_RX = re.compile(r"clip\s*#?\s*(\d+)\s*(?:=|->|:|→|goes (?:to|in|with)|for|on)\s*((?:beat|b|section|s)?\s*#?\s*\d+(?:\s*(?:,|and|&|-|to)\s*(?:beat|b|section|s)?\s*#?\s*\d+)*)", re.I)


def enabled(cfg): return bool(cfg.get("own_clips", False))


def _dir(job): return Path(job) / "src" / "clips"


def save(job, uploads, paths, hints, log=print):
    """Store the job's clips: uploads = [(filename, save_fn)], paths = files on this PC. -> [{n, file, name}] (also in state)."""
    d = _dir(job); d.mkdir(parents=True, exist_ok=True); out = []
    for name, saver in uploads:
        ext = Path(name).suffix.lower()
        if ext not in VIDEO_EXT: raise ValueError(f"{name}: not a video file ({', '.join(VIDEO_EXT)})")
        n = len(out) + 1; dst = d / f"clip{n}{ext}"; saver(str(dst)); out.append({"n": n, "file": f"src/clips/{dst.name}", "name": name[:120]})
    for p in paths:
        p = Path(str(p).strip().strip('"'))
        if not str(p): continue
        if not p.is_file(): raise ValueError(f"clip not found on this PC: {p}")
        if p.suffix.lower() not in VIDEO_EXT: raise ValueError(f"{p.name}: not a video file")
        n = len(out) + 1; dst = d / f"clip{n}{p.suffix.lower()}"; shutil.copy2(p, dst); out.append({"n": n, "file": f"src/clips/{dst.name}", "name": p.name[:120]})
    (d / "hints.txt").write_text(hints or "", encoding="utf-8")
    return out


def _probe(p):
    import subprocess
    o = subprocess.run([media._bin("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:stream_side_data=rotation:format=duration",
                        "-of", "json", str(p)], capture_output=True, text=True).stdout
    j = json.loads(o or "{}"); st = (j.get("streams") or [{}])[0]
    w, h = int(st.get("width") or 0), int(st.get("height") or 0)
    rot = next((abs(int(float(x.get("rotation", 0)))) for x in st.get("side_data_list") or [] if "rotation" in x), 0)
    if rot in (90, 270): w, h = h, w
    return {"dur": round(float((j.get("format") or {}).get("duration") or 0), 2), "w": w, "h": h}


def _sheet(p, out, dur):
    from PIL import Image
    ims = []
    for i, f in enumerate((0.15, 0.4, 0.65, 0.9)):
        fr = out.with_name(f"{out.stem}_{i}.jpg")
        media.ff("-ss", f"{dur * f:.2f}", "-i", p, "-frames:v", 1, "-vf", "scale=-2:480", fr)
        if fr.exists(): ims.append(Image.open(fr).convert("RGB"))
    if not ims: return None
    W = sum(i.width for i in ims) + 12 * (len(ims) - 1); s = Image.new("RGB", (W, max(i.height for i in ims))); x = 0
    for im in ims: s.paste(im, (x, 0)); x += im.width + 12
    s.save(out, "JPEG", quality=88)
    for i in range(4): out.with_name(f"{out.stem}_{i}.jpg").unlink(missing_ok=True)
    return out


DESCRIBE = ("These are 4 frames from one video clip, left to right in time. In ONE sentence say what it shows: the main subject, the "
            "setting, any action or camera move. Plain words, no guessing of names you can't read.")


def describe(job, cfg, log, clips):
    """-> [{n, file, name, dur, w, h, desc}] (cached)."""
    d = _dir(job); cf = d / "clips.json"
    cache = {c["file"]: c for c in (json.loads(cf.read_text(encoding="utf-8")) if cf.exists() else [])}
    out, vision_ok = [], True
    for c in clips:
        if c["file"] in cache and cache[c["file"]].get("dur"): out.append(cache[c["file"]]); continue
        p = Path(job) / c["file"]; info = _probe(p); c = dict(c, **info, desc="")
        if vision_ok and info["dur"] > 0:
            try:
                from .footage import _vision, ensure_vet_model
                if not out or not any(x.get("desc") for x in out): ensure_vet_model(cfg, log)
                sh = _sheet(p, d / f"sheet{c['n']}.jpg", info["dur"])
                if sh: c["desc"] = re.sub(r"\s+", " ", _vision(cfg, sh, DESCRIBE)).strip()[:240]
            except Exception as e:
                vision_ok = False; log(f"  your clips: couldn't look at the clips ({str(e)[:100]}); matching on your note and file names only")
        log(f"  clip {c['n']} ({c['name']}, {info['dur']:.0f}s, {info['w']}x{info['h']}): {c['desc'] or '(not described)'}")
        out.append(c)
    try:
        from .footage import unload_vet_model; unload_vet_model(cfg)
    except Exception: pass
    cf.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    return out


def parse_structured(hints, n_clips, beat_ids):
    """'clip1=beat3, clip2=beat5,6' / 'clip 2 -> 4-5' -> {clip_n: [beat ids]} (1-based beat numbers), or None when the note isn't
    in that form (then it is read as free text)."""
    if not hints or not hints.strip(): return None
    found = list(HINT_RX.finditer(hints))
    if not found: return None
    covered = sum(len(m.group(0)) for m in found); rest = re.sub(r"[\s,;.]+", "", HINT_RX.sub("", hints))
    if rest and covered < len(re.sub(r"\s+", "", hints)) * 0.6: return None   # mostly prose: let the AI read it
    out = {}
    for m in found:
        n = int(m.group(1))
        if not 1 <= n <= n_clips: continue
        nums = []
        for a, b in re.findall(r"(\d+)\s*(?:(?:-|to)\s*(\d+))?", m.group(2)):
            a = int(a); b = int(b) if b else a
            nums += list(range(min(a, b), max(a, b) + 1))
        for k in nums:
            if 1 <= k <= len(beat_ids): out.setdefault(n, []).append(beat_ids[k - 1])
    return out or None


MATCH = """You place an editor's own video clips on the beats of a narrated video. Each beat is one or two sentences of narration;
each clip is described below (what it shows), and the editor may have left a note on which clip goes where.

Beats:
{beats}

Clips:
{clips}

Editor's note: {hints}

Assign each clip to the beat(s) its content actually shows (a clip may cover several beats in a row if it is long enough; a beat
gets at most one clip). Follow the editor's note when it says where a clip goes. Leave a beat out when no clip fits it - it will
get generated visuals. Do not force every clip in: a clip that fits nothing is left unused.
Reply with ONLY JSON: {{"assign": [{{"clip": 1, "beats": ["b0", "b3"], "why": "short reason"}}], "unused": [clip numbers]}}"""


def _hint_for(hints, n):
    """The part of a free-text note about clip n ("clip 1 is the church exterior, clip 2 is ..." -> "is the church exterior,")."""
    m = re.search(rf"\bclip\s*#?\s*{n}\b(.*?)(?=\bclip\s*#?\s*\d|$)", hints or "", re.I | re.S)
    return m.group(1) if m else ""


def _words(t): return {w for w in re.findall(r"[a-z]{4,}", (t or "").lower())} - {"this", "that", "with", "from", "they", "have", "were", "their", "there", "which", "about", "into", "shows", "clip", "video"}


def match(job, sections, cfg, log, stop=lambda: False):
    """-> {"assign": {beat_id: clip_n}, "how": "note" | "ai" | "keywords", "why": {beat_id: reason}} (src/clips/match.json)."""
    from .pipeline import Job
    j = Job(job); clips = j.state.get("my_clips") or []
    d = _dir(job); mf = d / "match.json"
    if mf.exists(): return json.loads(mf.read_text(encoding="utf-8"))
    hints = (d / "hints.txt").read_text(encoding="utf-8") if (d / "hints.txt").exists() else ""
    beats = [s for s in sections if not s.get("cta")]; ids = [s["id"] for s in beats]
    info = describe(job, cfg, log, clips)
    st = parse_structured(hints, len(info), ids)
    assign, why, how = {}, {}, "note"
    if st:
        for n, bs in st.items():
            for b in bs:
                if b not in assign: assign[b] = n; why[b] = "your note"
    else:
        how = "ai"
        try:
            from .llm import LLM
            c = dict(cfg); c["script_provider"] = "deepseek" if cfg.get("deepseek_api_key") else "local"
            bt = "\n".join(f"{s['id']} (beat {i + 1}): {s['vo'][:300]}" for i, s in enumerate(beats))
            ct = "\n".join(f"clip {x['n']} ({x['name']}, {x['dur']:.0f}s): {x.get('desc') or '(no description; go by the file name and the note)'}" for x in info)
            with LLM(c, log, stop) as llm:
                r = llm.chat_json("You are a careful video editor. Reply with JSON only.", MATCH.format(beats=bt, clips=ct, hints=hints.strip() or "(none)"), max_tokens=1500)
            for a in r.get("assign") or []:
                n = int(a.get("clip") or 0)
                if not 1 <= n <= len(info): continue
                for b in a.get("beats") or []:
                    b = str(b)
                    if re.fullmatch(r"\d+", b) and 1 <= int(b) <= len(ids): b = ids[int(b) - 1]
                    if b in ids and b not in assign: assign[b] = n; why[b] = str(a.get("why") or "")[:120]
        except Exception as e:
            log(f"  your clips: the AI couldn't place them ({str(e)[:100]}); matching by words instead"); how = "keywords"
        if how == "keywords":   # only when the AI call failed; an AI answer of "nothing fits" stands
            for x in info:   # each clip: its description, file name and its own part of your note ("clip 2 is ...")
                cw = _words(x.get("desc", "") + " " + re.sub(r"[_\-.]+", " ", Path(x["name"]).stem) + " " + _hint_for(hints, x["n"]))
                free = [s for s in beats if s["id"] not in assign]
                best = max(free, key=lambda s: len(cw & _words(s["vo"])), default=None)
                if best and len(cw & _words(best["vo"])) >= 2: assign[best["id"]] = x["n"]; why[best["id"]] = "shared words"
    res = {"assign": {b: assign[b] for b in ids if b in assign}, "how": how, "why": why}
    mf.write_text(json.dumps(res, indent=1), encoding="utf-8")
    cov = ", ".join(f"beat {ids.index(b) + 1}=clip {n}" for b, n in res["assign"].items())
    log(f"Your clips: {len(res['assign'])} of {len(ids)} beat(s) covered by your footage ({how}): {cov or 'none'}; the rest use generated visuals")
    return res


def _segments(job, res, sections, wpm, rate=0.85):
    """Split each clip over the beats it covers, in beat order. -> {beat_id: (clip info, start, seconds of footage)}
    rate: footage plays at this speed in the Short (0.85), so a beat of D seconds needs D * rate seconds of it."""
    info = {c["n"]: c for c in json.loads((_dir(job) / "clips.json").read_text(encoding="utf-8"))}
    order = [s["id"] for s in sections]; est = {s["id"]: max(2.0, (len(s["vo"].split()) / wpm * 60 + 0.4) * rate) for s in sections}
    by = {}
    for b, n in res["assign"].items(): by.setdefault(n, []).append(b)
    out = {}
    for n, bs in by.items():
        c = info.get(n)
        if not c or not c.get("dur"): continue
        bs.sort(key=order.index); need = sum(est[b] for b in bs)
        scale = min(1.0, c["dur"] / need) if need else 1.0   # a short clip is shared in proportion; a long one gives each beat its part
        t = 0.0
        for b in bs:
            L = max(1.5, est[b] * scale); out[b] = (c, round(t, 2), round(min(L, c["dur"] - t), 2)); t += L
    return out


def _cut(src, start, length, out, W, H):
    media.ff("-ss", f"{start:.2f}", "-i", src, "-t", f"{length:.2f}", "-an",
             "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},fps=30,format=yuv420p",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-bf", "0", "-g", "30", out, timeout=900)
    if not media.ok(out, 0.3): raise RuntimeError(f"cutting {Path(src).name} produced no video")
    return out


def for_short(job, plan, cfg, log, stop=lambda: False):
    """Shorts: cut each covered beat's part of your clip into short/stock/clips/ -> {beat_id: [pick.json entry]}."""
    from .pipeline import Job
    from . import tts
    if not (Job(job).state.get("my_clips")): return {}
    res = match(job, plan["sections"], cfg, log, stop)
    segs = _segments(job, res, [s for s in plan["sections"] if not s.get("cta")], tts.wpm(cfg))
    cd = Path(job) / "short" / "stock" / "clips"; cd.mkdir(parents=True, exist_ok=True); out = {}
    for b, (c, st, L) in segs.items():
        if stop(): raise RuntimeError("cancelled")
        cid = f"own{c['n']}_{b}"
        if not media.ok(cd / f"{cid}.mp4", 0.3): _cut(Path(job) / c["file"], st, L, cd / f"{cid}.mp4", 1080, 1920)
        out[b] = [{"id": cid, "src": "yours", "orient": "portrait", "query": "", "dur": L, "w": 1080, "h": 1920, "file": c["file"], "page": "",
                   "author": "", "desc": c.get("desc") or c["name"], "seen": f"your clip {c['n']}: {c.get('desc') or c['name']}"[:120], "own": True,
                   "clip_n": c["n"], "start": st}]
    return out


def for_long(job, plan, cfg, log, stop=lambda: False):
    """Explainers: give each covered section's AI still / motion slots successive parts of your clip (v['stock'], stock_src 'yours')."""
    from .pipeline import Job
    from . import tts
    if not (Job(job).state.get("my_clips")): return 0
    res = match(job, plan["sections"], cfg, log, stop)
    info = {c["n"]: c for c in json.loads((_dir(job) / "clips.json").read_text(encoding="utf-8"))}
    od = Path(job) / "broll" / "own"; od.mkdir(parents=True, exist_ok=True); n = 0
    by = {}
    for b, k in res["assign"].items(): by.setdefault(k, []).append(b)
    for k, sids in by.items():
        c = info.get(k)
        if not c or not c.get("dur"): continue
        slots = [(s, v) for s in plan["sections"] if s["id"] in sids for v in s["visuals"] if v["type"] in ("still", "motion") and not v.get("stock")]
        if not slots: continue
        L = max(3.0, min(12.0, c["dur"] / len(slots)))   # successive parts; a short clip repeats rather than run dry
        for i, (s, v) in enumerate(slots):
            if stop(): raise RuntimeError("cancelled")
            st = (i * L) % max(0.1, c["dur"] - 1.0) if c["dur"] > L else 0.0
            out = od / f"{v['id']}.mp4"
            if not media.ok(out, 0.3): _cut(Path(job) / c["file"], st, min(L, c["dur"] - st), out, 1920, 1080)
            v["stock"] = str(out.relative_to(job)).replace("\\", "/"); v["stock_src"] = "yours"; v["own"] = True; n += 1
    log(f"Your clips: {n} explainer shot(s) use your footage")
    return n


def offer(job, sd, rv, bid, cfg, log):
    """Editor: every clip of the job as a candidate on this beat (rung 'own'), cut once per clip into <sd>/own/."""
    from .pipeline import Job
    from . import review
    clips = Job(job).state.get("my_clips") or []
    if not clips: return
    have = {rv["cands"][c]["item"].get("own_n") for c in rv["beats"][bid]["cands"]}
    sp = json.loads((Path(sd) / "space.json").read_text(encoding="utf-8")) if (Path(sd) / "space.json").exists() else {"w": 1080, "h": 1920}
    od = Path(sd) / "own"; od.mkdir(parents=True, exist_ok=True)
    info = {c["n"]: c for c in (json.loads((_dir(job) / "clips.json").read_text(encoding="utf-8")) if (_dir(job) / "clips.json").exists() else clips)}
    for c in clips:
        if c["n"] in have: continue
        out = od / f"own{c['n']}.mp4"
        if not media.ok(out, 0.3):
            src = Path(job) / c["file"]; d = info.get(c["n"], {}).get("dur") or media.dur(src)
            _cut(src, 0.0, min(180.0, d), out, sp["w"], sp["h"])
        desc = info.get(c["n"], {}).get("desc") or c["name"]
        review._add(rv, bid, {"type": "video", "src": f"own/{out.name}", "tag": "YOUR FOOTAGE", "own_n": c["n"], "rate": 1.0, "user": True}, "own", True, f"your clip {c['n']}: {desc}"[:120])


def coverage(job):
    """For the job page: {beat_id: clip number} of the automatic placement, or {}."""
    mf = _dir(job) / "match.json"
    return json.loads(mf.read_text(encoding="utf-8")).get("assign", {}) if mf.exists() else {}
