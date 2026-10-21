"""Rendering stages: narration, presenter, motion clips, stills (with automatic QA + rerolls)."""
import os, re, json, math, shutil
from .llm import qa_available
from pathlib import Path
from . import media, qa, charts
STYLE = ", cinematic photorealistic, natural dramatic lighting, 35mm film look, highly detailed, no text, no watermark"

def chunks(text, limit=85):
    sents = re.findall(r"[^.?!]+[.?!]+[\"')\]]*|[^.?!]+$", text); out, cur, n = [], [], 0
    for s in (x.strip() for x in sents if x.strip()):
        w = len(s.split())
        if n + w > limit and cur: out.append(" ".join(cur)); cur, n = [], 0
        cur.append(s); n += w
    if cur: out.append(" ".join(cur))
    return out

def do_charts(job, plan, cfg, log):
    d = job / "charts"; d.mkdir(exist_ok=True)
    meta = json.loads((job / "src" / "meta.json").read_text(encoding="utf-8")) if (job / "src" / "meta.json").exists() else {}
    credit = f"Based on \"{meta.get('title', '')}\" — {meta.get('channel') or meta.get('uploader') or ''}".strip(" —")
    charts.render({"kind": "title", "title": plan["title"], "subtitle": plan.get("subtitle", ""), "credit": credit}, d / "_title.png")
    charts.render({"kind": "end", "text": plan.get("end_text") or "Thanks for watching", "credit": credit + (f"  |  {meta.get('webpage_url')}" if meta.get("webpage_url") else "")}, d / "_end.png")
    n = 0
    for s in plan["sections"]:
        for v in s["visuals"]:
            if v["type"] == "chart":
                p = d / f"{v['id']}.png"
                if not p.exists():
                    try: charts.render(v["chart"], p)
                    except Exception as e:
                        log(f"  chart {v['id']} failed ({e}); using a text card"); charts.render({"kind": "cards", "title": s["title"], "items": []}, p)
                n += 1
    log(f"Charts: {n} rendered")

def do_voice(job, plan, cfg, wg, log, stop):
    """WanGP (when needed at all) is started on demand and stopped as soon as this batch is done (wangp.py)."""
    with wg.hold():
        return _do_voice_inner(job, plan, cfg, wg, log, stop)


def _do_voice_inner(job, plan, cfg, wg, log, stop):
    d = job / "voice"; d.mkdir(exist_ok=True)
    gap = d / "_gap.wav"; media.ff("-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", 0.25, gap)
    seed = 9000
    from .pipeline import progress
    from . import tts
    if tts.engine(cfg) == "kokoro":   # all chunks in one Kokoro run; the per-section concat below is unchanged
        import unicodedata
        items = [(text, d / f"{s['id']}_{ci}.wav") for s in plan["sections"] if not media.ok(d / f"{s['id']}.wav")
                 for ci, text in enumerate(chunks(unicodedata.normalize("NFKD", s["vo"]).encode("ascii", "ignore").decode()))]
        if not tts.try_kokoro(cfg, items, log, "Narration", stop) and not wg.alive():
            raise RuntimeError("Kokoro narration failed and WanGP (the fallback) is not running. Start Wan2GP in Pinokio, then press Resume.")
    for si, s in enumerate(plan["sections"]):
        progress(job, si + 1, len(plan["sections"]))
        out = d / f"{s['id']}.wav"
        if media.ok(out): continue
        parts = []
        import unicodedata
        vo_ascii = unicodedata.normalize("NFKD", s["vo"]).encode("ascii", "ignore").decode()  # WanGP mangles non-ASCII in output filenames
        for ci, text in enumerate(chunks(vo_ascii)):
            seed += 1; p = d / f"{s['id']}_{ci}.wav"
            if not media.ok(p):
                for attempt in range(3):
                    r = wg.gen({"model_type": cfg["tts_model"], "prompt": text, "audio_prompt_type": "A", "audio_guide": cfg["voice_ref_wav"],
                                "alt_prompt": cfg["voice_ref_text"], "model_mode": "english", "duration_seconds": 60,
                                "temperature": 0.7, "top_k": 50, "seed": seed + attempt * 77}, log, f"voice {s['id']}_{ci}", stop=stop)
                    if not r["ok"]: raise RuntimeError(f"narration failed: {r['err']}")
                    try: wps = len(text.split()) / max(media.dur(r["file"]), 0.1)
                    except Exception as e:
                        log(f"  voice {s['id']}_{ci}: unreadable output ({e}), re-rendering"); r["ok"] = False; continue
                    if 1.7 <= wps <= 3.8: break
                    log(f"  voice {s['id']}_{ci}: odd pace ({wps:.1f} words/s), re-rendering")
                if not r["ok"]: raise RuntimeError(f"narration {s['id']}_{ci} failed 3 times")
                media.ff("-i", r["file"], "-ar", 48000, "-ac", 2, p)
            parts.append(p)
        lst = d / f"{s['id']}.txt"; lst.write_text("".join(f"file '{p.as_posix()}'\nfile '{gap.as_posix()}'\n" for p in parts), encoding="utf-8")
        media.ff("-f", "concat", "-safe", 0, "-i", lst, "-c", "copy", out)
        log(f"Narration {s['id']}: {media.dur(out):.1f}s")

def presenter_segments(job, plan):
    segs = []
    for si, s in enumerate(plan["sections"]):
        vo = job / "voice" / f"{s['id']}.wav"; D = media.dur(vo); sil = media.silences(vo)
        c = [a for a, b in sil if 7 <= a <= 11.5]; end = c[0] if c else min(10.0, D - 0.3)
        segs.append({"sid": s["id"], "kind": "open", "start": 0.0, "end": round(end + 0.15, 2)})
        if si == len(plan["sections"]) - 1 and D > 25:
            c2 = [b for a, b in sil if D - 13 <= b <= D - 6]; st = c2[0] if c2 else D - 10
            segs.append({"sid": s["id"], "kind": "close", "start": round(st - 0.1, 2), "end": round(D - 0.25, 2)})
    for g in segs: g["dur"] = round(g["end"] - g["start"], 2); g["frames"] = int(math.ceil(g["dur"] * 24 / 8)) * 8 + 1
    return segs

def do_presenter(job, plan, cfg, wg, log, stop):
    """WanGP (when needed at all) is started on demand and stopped as soon as this batch is done (wangp.py)."""
    with wg.hold():
        return _do_presenter_inner(job, plan, cfg, wg, log, stop)


def _do_presenter_inner(job, plan, cfg, wg, log, stop):
    d = job / "presenter"; d.mkdir(exist_ok=True)
    segs = presenter_segments(job, plan); (d / "segments.json").write_text(json.dumps(segs, indent=1))
    seed = 7000
    for g in segs:
        key = f"{g['sid']}_{g['kind']}"; out = d / f"{key}.mp4"; seed += 10
        if media.ok(out): continue
        wav = d / f"{key}.wav"
        media.ff("-ss", g["start"], "-t", g["dur"], "-i", job / "voice" / f"{g['sid']}.wav", "-ac", 1, "-ar", 16000, wav)
        best, best_s = None, -1
        for t in range(3):
            r = wg.gen({"model_type": cfg["video_model"], "prompt": cfg["presenter_prompt"], "image_prompt_type": "S",
                        "image_start": cfg["presenter_image"], "audio_prompt_type": "A", "audio_scale": 1, "audio_guide": str(wav),
                        "resolution": "832x480", "video_length": g["frames"], "num_inference_steps": 8, "seed": seed + t}, log, f"presenter {key}", stop=stop)
            if not r["ok"]: continue
            sc = media.mouth_score(r["file"])
            if sc > best_s: best, best_s = r["file"], sc
            if sc >= 10: break
            log(f"  presenter {key}: mouth barely moves (score {sc:.1f}), re-rendering")
        if best: shutil.copy(best, out); log(f"Presenter {key}: {g['dur']}s, mouth score {best_s:.1f}")
        else: log(f"Presenter {key}: failed, section will run without presenter")

def _still(cfg, wg, log, prompt, out, seed, stop, tag):
    last_issue = ""
    for t in range(3):
        r = wg.gen({"model_type": cfg["still_model"], "prompt": prompt + STYLE, "resolution": "1920x1088",
                    "num_inference_steps": 4, "seed": seed + t * 31}, log, tag, stop=stop)
        if not r["ok"]: continue
        if not qa_available(cfg):
            shutil.copy(r["file"], out); return True
        good, issue = qa.check(cfg, r["file"], prompt)
        if issue.startswith("qa-"): log(f"  {tag}: image check unavailable ({issue[:120]})")
        if good: shutil.copy(r["file"], out); return True
        last_issue = issue; log(f"  {tag}: QA rejected ({issue}), re-rendering")
        if t == 1: prompt = prompt + ", simple uncluttered composition, fewer people"
    if r.get("ok"): shutil.copy(r["file"], out); log(f"  {tag}: kept last attempt despite QA ({last_issue})")
    return r.get("ok", False)

def _ents(job):
    f = job / "entities.json"
    try: return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []
    except Exception: return []

def badge(src, dst, text="GENERATED · CLOUD"):
    """Was: burn the label into the still. Rung labels are no longer drawn on the video (2026-10-21): a plain copy."""
    import shutil as _sh
    if str(src) != str(dst): _sh.copy(src, dst)
    return
    """(old body kept below for reference)"""
    from PIL import Image, ImageDraw, ImageFont
    im = Image.open(src).convert("RGB"); W, H = im.size; fs = max(14, int(W * 0.018))
    font = None
    for f in ("arialbd.ttf", "C:/Windows/Fonts/arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try: font = ImageFont.truetype(f, fs); break
        except Exception: pass
    if font is None: font = ImageFont.load_default()
    d = ImageDraw.Draw(im); x, y = int(W * 0.11), int(H * 0.11)
    l, t, r, b = d.textbbox((x, y), text, font=font); p = int(fs * 0.5)
    d.rounded_rectangle((l - p, t - p, r + p, b + p), radius=int(fs * 0.35), fill=(255, 200, 61))
    d.text((x, y), text, font=font, fill=(17, 17, 17))
    im.save(dst, quality=93)

def cloud_still(cfg, job, v, vo, log):
    """Long videos: a 16:9 cloud still (Gemini -> ChatGPT) for visual v -> stills/<id>.jpg with the GENERATED · CLOUD label.
    Skipped for narration naming a real person; a still the image check rejects isn't used. -> True if made."""
    from . import cloudgen
    if not cfg.get("cloud_on", True) or not v.get("prompt") or not cloudgen.providers_of(cfg): return False
    if cloudgen.has_person(vo, _ents(job)): log(f"  cloud {v['id']}: narration names a real person, cloud skipped"); return False
    d = job / "stills"; d.mkdir(exist_ok=True); png = d / f"cloud_{v['id']}.png"
    res = cloudgen.generate(cfg, v["prompt"], png, "16:9", log, f"cloud {v['id']}", job=job)
    if not res["ok"]: return False
    if qa_available(cfg):
        good, issue = qa.check(cfg, png, v["prompt"])
        if not good and not issue.startswith("qa-"): log(f"  cloud {v['id']}: image check rejected it ({issue[:100]}); WanGP next"); return False
    badge(png, d / f"{v['id']}.jpg"); v["cloud"] = res["provider"]
    return True

def illustration_still(cfg, job, v, vo, log):
    """Long videos, before WanGP: a 16:9 flat illustration / silhouette (illustrate.py, Remotion), rendered as a 6 s animated clip
    (layer parallax, the aircraft moving at its attitude) -> motion/<id>.mp4 and the visual becomes "motion" (assemble stretches it
    to its slot); the ILLUSTRATION / SILHOUETTE label is drawn by Remotion. Beats WanGP must not draw (aircraft,
    vehicles, specific buildings, real people) get the headline card when no illustration fits. -> rung name, or None (WanGP may
    draw it: atmospheric filler)."""
    from . import illustrate, review
    sec = {"id": v["id"], "vo": vo, "still_prompt": v.get("prompt", "")}
    ents = _ents(job); opts = illustrate.options(sec, ents); lock = illustrate.wangp_lock(sec, ents)
    if opts: item = opts[0]
    elif lock: item = {"type": "graphic", "g": {"kind": "headline", "kicker": "", "text": " ".join(vo.split()[:12]), "sub": ""}, "rung": "headline"}
    else: return None
    d = job / "stills"; d.mkdir(exist_ok=True); ws = d / "_illus"; ws.mkdir(exist_ok=True)
    (ws / "space.json").write_text(json.dumps({"orient": "landscape", "still_res": "1920x1088", "i2v_res": "1280x720", "w": 1920, "h": 1080}), encoding="utf-8")
    bg = {k: item[k] for k in ("type", "g")}
    if item.get("tag"): bg["tag"] = item["tag"]
    md = job / "motion"; md.mkdir(exist_ok=True); clip = md / f"{v['id']}.mp4"
    raw = ws / f"{v['id']}_raw.mp4"
    try:
        review._remotion(ws, bg, 6, raw, cfg, log, frames=(0, 179), scale=1, crf=16)
        # Remotion writes full-range (yuvj420p) video; mixed with limited-range clips in one concat it corrupted a whole section
        # (job 20261011_082753: 39 s frozen on one blended frame). Normalise to limited range like every other clip.
        media.ff("-i", raw, "-an", "-vf", "scale=in_range=pc:out_range=tv,format=yuv420p", "-color_range", "tv", "-c:v", "libx264",
                 "-preset", "veryfast", "-crf", 16, clip); raw.unlink(missing_ok=True)
    except Exception as e: log(f"  illustration {v['id']} failed ({str(e)[:100]})"); return None
    v["illustration"] = item["rung"]; v["type"] = "motion"; v["g"] = item["g"]   # the explainer renders the graphic itself
    log(f"  {v['id']}: {item['rung']}" + (f" (WanGP skipped: {lock})" if lock else " (before WanGP)"))
    return item["rung"]

def _ws(job):
    """The landscape workspace for explainer clips made with Remotion (illustrations, GRAPHICS)."""
    ws = job / "stills" / "_illus"; ws.mkdir(parents=True, exist_ok=True)
    (ws / "space.json").write_text(json.dumps({"orient": "landscape", "still_res": "1920x1088", "i2v_res": "1280x720", "w": 1920, "h": 1080}), encoding="utf-8")
    return ws

def vo_slice(plan, s, v, pad=6):
    """The narration this visual plays over: explainer visuals get equal time slots across the section (explainer._bounds; the
    first section's slot 0 is the title card), so visual i of n covers about the i-th n-th of the words, padded a few words
    each side for context. Gives each visual its own graphic / illustration instead of n copies of one for the whole section."""
    words = s.get("vo", "").split()
    vis = list(s.get("visuals") or []); first = bool(plan.get("sections")) and plan["sections"][0] is s
    try: i = vis.index(v)
    except ValueError: return s.get("vo", "")
    n = len(vis) + (1 if first else 0); i += 1 if first else 0
    if not words or n <= 1: return s.get("vo", "")
    a, b = int(len(words) * i / n), int(len(words) * (i + 1) / n)
    return " ".join(words[max(0, a - pad):min(len(words), b + pad)])

def v2_after_wangp(cfg, job, v, vo, log):
    """Visual ladder v2 for an explainer visual that the cloud and WanGP didn't cover (WanGP draws atmospheric beats only):
    5 Remotion graphics (motion/<id>.mp4, GRAPHICS burned in) -> 6 physics module (drawn live by the explainer, SIMULATION) ->
    headline card (the illustration rung was removed 2026-10-21). CapCut is Shorts-only for now.
    -> rung name (always succeeds: the headline card is the floor)."""
    from . import graphics, physics
    sec = {"id": v["id"], "vo": vo, "still_prompt": v.get("prompt", ""), "visuals": [x for x in [v.get("chart") and {"chart": v["chart"]}] if x]}
    md = job / "motion"; md.mkdir(exist_ok=True)
    sec["subject"] = v.get("subject")
    verb, amod = physics.action(sec) if cfg.get("physics_auto", True) else ("", None)
    if amod:   # action (2026-10-13): the module that animates it before graphics
        from . import liveries
        g6 = physics.run(amod, physics.fill(cfg, amod, {**sec, "_story": liveries.story_text(_ents(job))}, log), cfg)
        if g6:
            v["type"] = "motion"; v["g"] = g6; v["tag"] = "SIMULATION"; log(f"  {v['id']}: simulation ({amod}, action: {verb})"); return "simulation"
        log(f"  {v['id']}: simulation {amod} had no usable data")
    motion = physics.synthetic_motion(sec)
    if motion:
        v["type"] = "motion"; v["g"] = motion; v["tag"] = "SYNTHETIC"
        log(f"  {v['id']}: synthetic motion ({motion['module']})")
        return "simulation"
    try: g5 = graphics.make(cfg, _ws(job), sec, v["id"], log, tag="GRAPHICS")
    except Exception as e: g5 = {"ok": False, "why": f"crash ({str(e)[:100]})"}
    if g5.get("ok"):
        shutil.copy(g5["path"], md / f"{v['id']}.mp4"); v["type"] = "motion"; v["graphics"] = g5.get("how"); v.pop("g", None)
        log(f"  {v['id']}: graphics ({g5.get('how')})"); return "graphics"
    log(f"  {v['id']}: graphics failed ({str(g5.get('why'))[:100]})")
    if cfg.get("physics_auto", True) and not amod:   # (amod was already tried above; no other module fits this visual's narration)
        mod = None
        g6 = None
        if g6:
            v["type"] = "motion"; v["g"] = g6; v["tag"] = "SIMULATION"; log(f"  {v['id']}: simulation ({mod})"); return "simulation"
    v["type"] = "motion"; v["g"] = {"kind": "headline", "kicker": "", "text": " ".join(vo.split()[:12]), "sub": ""}
    log(f"  {v['id']}: headline card"); return "headline"

def refresh_fallbacks(job, plan, cfg, log, stop=lambda: False):
    """Explainer shots that ended on the headline text card (the floor of the ladder, e.g. while the script AI was out of credit)
    go down the v2 ladder again; shots replaced in the editor (edit_bgs) are left alone. Caption groups whose emoji pick failed
    (icons_<sec>.json without a single emoji) are picked again by the explainer render. -> {rung: count}"""
    out = {}; n = 0
    for s in plan["sections"]:
        for v in s["visuals"]:
            if not isinstance(v, dict) or v.get("edit_bgs") or (v.get("g") or {}).get("kind") != "headline": continue
            if stop(): raise RuntimeError("cancelled")
            n += 1; v.pop("g", None)
            (job / "motion" / f"{v['id']}.mp4").unlink(missing_ok=True)
            r = v2_after_wangp(cfg, job, v, vo_slice(plan, s, v), log); out[r] = out.get(r, 0) + 1
    icons = 0
    for f in (job / "captions").glob("icons_*.json"):
        try:
            if not any(g.get("emoji") for g in json.loads(f.read_text(encoding="utf-8"))): f.unlink(); icons += 1
        except Exception: pass
    log(f"Rebuilt {n} text-card shot(s): " + (", ".join(f"{k} {c}" for k, c in sorted(out.items())) or "none") + f"; emoji re-picked for {icons} section(s)")
    return out

def do_motion(job, plan, cfg, wg, log, stop):
    """WanGP (when needed at all) is started on demand and stopped as soon as this batch is done (wangp.py)."""
    with wg.hold():
        return _do_motion_inner(job, plan, cfg, wg, log, stop)


def _do_motion_inner(job, plan, cfg, wg, log, stop):
    d = job / "motion"; d.mkdir(exist_ok=True); seed = 3000
    for s in plan["sections"]:
        for v in s["visuals"]:
            if v["type"] != "motion" or v.get("stock") or v.get("g") or v.get("v2"): continue   # g / v2: drawn live or decided in B-roll
            seed += 1; out = d / f"{v['id']}.mp4"
            if media.ok(out): continue
            if (job / "stills" / f"{v['id']}.jpg").exists() or cloud_still(cfg, job, v, s.get("vo", ""), log):   # cloud still
                v["type"] = "still"; log(f"Motion {v['id']}: cloud still instead of WanGP motion"); continue
            if cfg.get("ladder_v2"):   # v2: WanGP motion only for atmospheric beats; everything else goes down the v2 ladder
                from . import illustrate
                vs = vo_slice(plan, s, v)
                from . import physics
                lock = illustrate.wangp_lock({"id": v["id"], "vo": s.get("vo", ""), "still_prompt": v.get("prompt", "")}, _ents(job)) \
                    or ("action" if physics.action({"vo": vs, "subject": v.get("subject")})[0] else "")
                if lock: v2_after_wangp(cfg, job, v, vs, log); continue
            elif illustration_still(cfg, job, v, s.get("vo", ""), log): continue   # animated illustration clip (motion/<id>.mp4)
            ok = False
            for t in range(2):
                r = wg.gen({"model_type": cfg["video_model"], "prompt": v["prompt"] + STYLE, "resolution": "1280x720",
                            "video_length": 121, "num_inference_steps": 8, "seed": seed + t * 97}, log, f"motion {v['id']}", stop=stop)
                if not r["ok"]: continue
                if qa_available(cfg):
                    strip = d / f"{v['id']}_qa.jpg"; media.frames_strip(r["file"], strip)
                    good, issue = qa.check(cfg, strip, v["prompt"] + " (three frames from one video clip)")
                    if issue.startswith("qa-"): log(f"  motion {v['id']}: image check unavailable ({issue[:120]})")
                    if not good: log(f"  motion {v['id']}: QA rejected ({issue})"); continue
                shutil.copy(r["file"], out); ok = True; break
            if not ok:
                log(f"  motion {v['id']}: falling back to a still"); v["type"] = "still"
            else: log(f"Motion {v['id']} done")

def do_stills(job, plan, cfg, wg, log, stop):
    d = job / "stills"; d.mkdir(exist_ok=True); seed = 1000; n = 0
    todo = [(v, vo_slice(plan, s, v) if cfg.get("ladder_v2") else s.get("vo", "")) for s in plan["sections"] for v in s["visuals"] if v["type"] == "still" and not v.get("stock")]
    sec_of = {v["id"]: s for s in plan["sections"] for v in s["visuals"]}
    snap_cache = {}
    def section_snapshot(sec):
        """A frame of this section's source clip, for the image generators to describe (rung 3)."""
        if sec["id"] in snap_cache: return snap_cache[sec["id"]]
        res = None
        sv = next((x for x in sec["visuals"] if x.get("stock_src") == "source" and x.get("stock")), None)
        if sv:
            from . import source_visuals
            clip = job / sv["stock"]
            item = {"type": "video" if clip.suffix == ".mp4" else "image", "path": str(clip), "secs": media.dur(clip) if clip.suffix == ".mp4" else 0}
            try: res = source_visuals.snapshot(cfg, job, _ws(job), {"id": sec["id"]}, log, source_item=item)
            except Exception as e: log(f"  {sec['id']}: source screenshot failed ({str(e)[:100]})")
        snap_cache[sec["id"]] = res
        return res
    from .pipeline import progress
    for i, (v, vo) in enumerate(todo):
        progress(job, i + 1, len(todo))
        seed += 1; out = d / f"{v['id']}.jpg"
        if out.exists(): continue
        if stop(): raise RuntimeError("cancelled")
        if cfg.get("ladder_v2") and cfg.get("imagegen_on", True):   # rung 3: free image generators, rung 4: rembg parallax
            from . import imagegen, depth
            snap = section_snapshot(sec_of[v["id"]]) if v["id"] in sec_of else None
            beat = {"id": v["id"], "vo": vo, "still_prompt": v.get("prompt", ""), "queries": v.get("queries") or []}
            try: img, site, _p = imagegen.generate(cfg, _ws(job), beat, "L_" + v["id"], log, aspect="16:9", image=(snap or {}).get("path"))
            except Exception as e:
                if str(e) == "cancelled": raise
                log(f"  {v['id']}: image generators failed ({str(e)[:100]}); next rung"); img = None
            if img:
                shutil.copy(img, out); v["tag"] = imagegen.tag(site); v.pop("g", None)
                try:
                    lay = depth.cutout_layers(out, d / f"{v['id']}_px", log, size=(1920, 1080))
                    v["layers"] = [str(Path(x).relative_to(job)).replace("\\", "/") for x in lay]
                except Exception as e: log(f"  {v['id']}: parallax failed ({str(e)[:100]}); the image is shown as a still")
                log(f"  {v['id']}: new image from {site}" + (" (described from the source)" if snap else "")); n += 1; continue
        if cfg.get("ladder_v2") and cfg.get("flow_on", True):   # rung 5: Google Flow (paid credits), last resort for AI video
            from . import flow
            try: clip = flow.generate(cfg, _ws(job), {"id": v["id"], "vo": vo, "still_prompt": v.get("prompt", ""), "queries": v.get("queries") or []},
                                      "L_" + v["id"], log, aspect="16:9")
            except Exception as e:
                if str(e) == "cancelled": raise
                log(f"  {v['id']}: flow failed ({str(e)[:100]}); next rung"); clip = None
            if clip:
                md = job / "motion"; md.mkdir(exist_ok=True)
                shutil.copy(clip, md / f"{v['id']}.mp4"); v["type"] = "motion"; v["tag"] = "GENERATED · FLOW"; v.pop("g", None)
                log(f"  {v['id']}: Google Flow clip"); n += 1; continue
        if cloud_still(cfg, job, v, vo, log): continue   # cloud first
        if cfg.get("ladder_v2"):   # v2: WanGP still for atmospheric beats, then graphics -> physics -> illustration -> headline
            from . import illustrate
            lock = illustrate.wangp_lock({"id": v["id"], "vo": vo, "still_prompt": v.get("prompt", "")}, _ents(job))
            from . import physics
            if not lock and physics.action({"vo": vo, "subject": v.get("subject")})[0]: lock = "action"   # animate an action, no still
            try: alive = (not lock) and wg.alive()
            except Exception: alive = False
            try: made = alive and _still(cfg, wg, log, v["prompt"], out, seed, stop, f"still {v['id']}")
            except Exception as e:
                if str(e) == "cancelled": raise
                log(f"  still {v['id']} failed ({str(e)[:120]}); next rung"); made = False
            if not made:
                try: v2_after_wangp(cfg, job, v, vo, log)
                except Exception as e:   # a rung must never stop the job: the headline card is the floor
                    if str(e) == "cancelled": raise
                    log(f"  {v['id']}: ladder failed ({type(e).__name__}: {str(e)[:120]}); headline card")
                    v["type"] = "motion"; v["g"] = {"kind": "headline", "kicker": "", "text": " ".join(vo.split()[:12]), "sub": ""}
            n += 1; continue
        if illustration_still(cfg, job, v, vo, log): continue   # then illustration / silhouette; WanGP only for atmospheric filler
        if not _still(cfg, wg, log, v["prompt"], out, seed, stop, f"still {v['id']}"):
            raise RuntimeError(f"still {v['id']} failed")
        n += 1
        if n % 10 == 0: log(f"Stills: {i+1}/{len(todo)}")
    log(f"Stills done: {len(todo)}")
