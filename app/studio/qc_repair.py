"""QC repair-by-ladder (owner spec approved 2026-10-26, exchange doc MSG 007, plus Tariq's addition the same evening).

qc.py (Koda's code, never edited here) only emits the MARKERS: run in report mode, its would_fix spans are the confirmed,
persistent HARD faults (black / finger / smudge under v8; orientation is report-only and never repaired). This module, run by
the pipeline when cfg "qc_mode" == "fix", replaces each marked span as ONE unit with a real visual and splices it over the
span, keeping the original audio (the narration plays on):

  1  stock footage (Pexels / Pixabay), checked for subject and frame faults
  2  AI image from the configured image services (Gemini never: "we don't go to google") -> local Python image-to-video
  3  ChatGPT chain: public web search of the span's narration -> visual description -> image prompt -> ChatGPT (its Chrome
     profile) -> local Python image-to-video
  4  World Labs Marble scene (world model) - only when marble_on is set and its signed-in browser profile exists
  5  local Python image-to-video of the nearest clean frame of this same video (2.5D parallax, Ken Burns if no cut-out)
  6  any image already made for the span, held still
  7  headline card (the floor, only after everything else)

Physics is excluded from repairs entirely. Bounded: every rung is tried once per span; nothing loops. Fail-open: any error or
timeout is logged and the next rung runs; a span nothing could repair is reported, never fatal - a video always stages.
A replacement shorter than its span is held on its last frame for the remainder (the static image under the narration).
Each candidate is frame-checked (the same pixel / two-agree judge as qc.py) before it is used.
Log: <video>.repair.json beside the video. The untouched original is kept as <job>/qc/<video>_preqc.mp4."""
import json, re, shutil, subprocess, time
from pathlib import Path

from . import media


def _log(log, m):
    (log or print)(m)


# ------------------------------------------------------------------ markers
def spans(mp4):
    """-> [(a, b, [faults])] from qc_part's report (<video>.qc.json, report mode): the HARD spans it would fix. Each run of
    bad samples is already one span (it starts at the first bad sample and ends where the next clean sample begins)."""
    rep = Path(mp4).with_suffix(".qc.json")
    if not rep.exists(): return []
    j = json.loads(rep.read_text(encoding="utf-8"))
    out = []
    for a, b, probs in j.get("would_fix") or []:
        a, b = float(a), float(b)
        if b - a < 0.5: continue
        if out and a <= out[-1][1] + 0.5: out[-1] = (out[-1][0], max(out[-1][1], b), sorted(set(out[-1][2]) | set(probs)))
        else: out.append((a, b, list(probs)))
    return out


def _clean_times(mp4):
    rep = Path(mp4).with_suffix(".qc.json")
    try: return [s["t"] for s in json.loads(rep.read_text(encoding="utf-8")).get("samples", []) if s.get("state") == "ok"]
    except Exception: return []


def narration(job_dir, mp4, a, b, vert):
    """The words spoken during [a, b] (the video's own timeline), widened to whole beats when the span holds few words."""
    tl = Path(job_dir) / ("short" if vert else "build") / "public" / "teaser.json"
    try: beats = json.loads(tl.read_text(encoding="utf-8")).get("beats", [])
    except Exception: return ""
    words, beat_txt = [], []
    for bt in beats:
        st = float(bt.get("start", 0)); d = float(bt.get("dur", 0) or 0)
        ws = bt.get("words") or []
        inside = [w[0] for w in ws if a - 1.0 <= st + float(w[1]) <= b + 1.0]
        words += inside
        if st < b and st + d > a: beat_txt.append(" ".join(w[0] for w in ws))
    txt = " ".join(words)
    if len(txt.split()) < 8 and beat_txt: txt = " ".join(beat_txt)
    return txt.strip()


# ------------------------------------------------------------------ helpers
def _probe(mp4):
    o = subprocess.run([media._bin("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height,avg_frame_rate", "-of", "json", str(mp4)], capture_output=True, text=True, timeout=30).stdout
    s = json.loads(o)["streams"][0]
    n, d = (s.get("avg_frame_rate") or "30/1").split("/")
    fps = float(n) / float(d) if float(d) else 30.0
    return int(s["width"]), int(s["height"]), (fps if 10 <= fps <= 61 else 30.0)


def clip_ok(cfg, clip, work, label=""):
    """-> (ok, why). Frames every ~2 s (at most 5) through qc.py's own judge: a candidate passes when none is a HARD fault
    or unchecked. Orientation is not judged (report-only under v8)."""
    from . import qc
    try: d = media.dur(clip)
    except Exception as e: return False, f"unreadable ({str(e)[:60]})"
    if d < 0.8: return False, "too short"
    n = max(2, min(5, int(d // 2) + 1)); work = Path(work); work.mkdir(parents=True, exist_ok=True)
    for k in range(n):
        t = min(d - 0.2, 0.3 + k * (d - 0.5) / max(1, n - 1)); img = work / f"chk_{label}_{k}.jpg"
        media.ff("-ss", f"{t:.2f}", "-i", clip, "-frames:v", 1, "-vf", "scale=768:-2", img, timeout=120, check=False)
        if not img.exists(): return False, f"no frame at {t:.1f}s"
        v = qc._judge(cfg, img)
        if v["state"] == "unchecked": return False, f"frame {t:.1f}s unchecked (vision model)"
        if v["state"] == "bad" and v["prob"] in qc.HARD: return False, f"frame {t:.1f}s {v['prob']}"
    return True, ""


def image_to_video(img, out, secs, W, H, log=None):
    """The local Python image-to-video maker: the picture cut (rembg, else depth) into background + subject, then a slow 2.5D
    parallax rendered frame by frame in numpy/PIL and piped to ffmpeg (CPU only). No cut-out -> a Ken Burns push-in."""
    from PIL import Image
    import numpy as np
    out = Path(out); secs = max(1.0, float(secs)); fps = 30; n = int(secs * fps)
    try:
        from . import depth
        L = depth.cutout_layers(str(img), str(out.with_suffix("")), log or (lambda m: None), size=(W, H))
    except Exception as e:
        L = None; _log(log, f"    image-to-video: no cut-out ({str(e)[:80]}); Ken Burns")
    if not L or len(L) < 2:
        from . import photos
        return Path(photos.kenburns(str(img), str(out), secs, (W, H), 0))
    bg = Image.open(L[0]).convert("RGB").resize((int(W * 1.10), int(H * 1.10)), Image.LANCZOS)
    fg = Image.open(L[-1]).convert("RGBA").resize((int(W * 1.14), int(H * 1.14)), Image.LANCZOS)
    cmd = [media._bin("ffmpeg"), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", str(out)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for i in range(n):
            u = i / max(1, n - 1)
            bx, by = int((bg.width - W) * (0.35 + 0.30 * u)), (bg.height - H) // 2
            fx, fy = int((fg.width - W) * (0.65 - 0.30 * u)), (fg.height - H) // 2
            fr = bg.crop((bx, by, bx + W, by + H)); layer = fg.crop((fx, fy, fx + W, fy + H))
            fr.paste(layer, (0, 0), layer)
            p.stdin.write(np.asarray(fr, dtype=np.uint8).tobytes())
        p.stdin.close(); p.wait(timeout=600)
    except Exception:
        p.kill(); raise
    if p.returncode or not media.ok(out): raise RuntimeError("parallax render failed: " + (p.stderr.read() or b"").decode(errors="replace")[:200])
    return out


def still_clip(img, out, secs, W, H):
    media.ff("-loop", 1, "-i", img, "-t", f"{secs:.2f}", "-vf",
             f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,format=yuv420p",
             "-r", 30, "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", out, timeout=300)
    return Path(out)


def _cfg_no_google(cfg):
    prov = [x for x in (cfg.get("imagegen_providers") or ["hf", "chatgpt", "bing"]) if x != "gemini"] or ["chatgpt"]
    return dict(cfg, imagegen_providers=prov, imagegen_rotate=False, imagegen_per_beat=1)


# ------------------------------------------------------------------ research (public web search, no account)
def research(cfg, text, log):
    """Narration -> (visual description, image prompt). Public search results (websearch: DuckDuckGo / Bing / Copilot in turn,
    Google rarely and last), then the script model turns the snippets + narration into one concrete, photographable scene."""
    from . import websearch
    from .llm import LLM
    c = dict(cfg)
    if c.get("script_provider") == "claude" and not c.get("anthropic_api_key"): c["script_provider"] = "deepseek" if c.get("deepseek_api_key") else "local"
    try:   # a short, specific web query (the raw narration matches junk: "attackers" alone finds adult-video studios)
        with LLM(c, log, lambda: False) as llm:
            q = str(llm.chat_json("You write web search queries. Reply with JSON only.", "Narration:\n" + text[:700]
                                  + '\n\nOne web search query (4-8 words, the specific subject, no quotes) that finds what this is about.\n{"query": "..."}',
                                  max_tokens=100).get("query") or "").strip()
    except Exception:
        q = ""
    q = q or " ".join(text.split()[:12])
    _log(log, f"    search query: {q}")
    snippets, src = websearch.search(cfg, q, log)
    with LLM(c, log, lambda: False) as llm:
        j = llm.chat_json("You plan one photorealistic picture for a documentary shot. Reply with JSON only.",
                          "Narration of the shot:\n" + text[:900] + "\n\nWhat a web search says about it:\n" + "\n".join("- " + s[:300] for s in snippets)
                          + '\n\nDescribe ONE concrete, real-looking scene a camera could have filmed that shows what the narration is about '
                          '(place, objects, light, weather; no readable text, no logos, no identifiable faces). Then write the image prompt.\n'
                          '{"description": "...", "prompt": "..."}', max_tokens=600)
    return str(j.get("description") or "").strip(), str(j.get("prompt") or j.get("description") or text[:300]).strip()


# ------------------------------------------------------------------ rungs (each -> (clip, image_or_None) or raises / None)
def _rung_stock(ctx):
    from . import footage
    cfg, vo, log = ctx["cfg"], ctx["vo"], ctx["log"]
    if not vo: return None, None, "no narration for the span"
    try:
        from .llm import LLM
        c = dict(cfg)
        if c.get("script_provider") == "claude" and not c.get("anthropic_api_key"): c["script_provider"] = "deepseek" if c.get("deepseek_api_key") else "local"
        with LLM(c, log, lambda: False) as llm:
            qs = llm.chat_json("You pick stock-footage searches. Reply with JSON only.",
                               "Narration:\n" + vo[:700] + '\n\nGive 2 short stock-video searches (2-4 words each) for footage that shows what this is about.\n{"queries": ["...", "..."]}',
                               max_tokens=200).get("queries") or []
    except Exception:
        qs = []
    qs = [q for q in qs if isinstance(q, str) and q.strip()][:2] or [" ".join(sorted(footage.narration_words(vo))[:3])]
    orient = "portrait" if ctx["vert"] else "landscape"; want = max(ctx["W"], ctx["H"])
    cands = []
    for q in qs:
        cands += footage.pexels(q, orient, log, want) + footage.pixabay(q, orient, log, want)
    tried = 0
    for c in cands:
        if tried >= 3: break
        tried += 1
        out = ctx["work"] / f"stock_{c['id']}.mp4"
        try: footage.fetch(c, str(out), ctx["need"] + 1.0)
        except Exception as e: _log(log, f"    stock {c['id']}: {str(e)[:80]}"); continue
        mid = ctx["work"] / f"stock_{c['id']}_mid.jpg"
        media.ff("-ss", f"{min(2.0, media.dur(out) / 2):.2f}", "-i", out, "-frames:v", 1, "-vf", "scale=768:-2", mid, check=False, timeout=120)
        try:
            from .llm import parse_json
            m = parse_json(footage._vision(dict(cfg, vet_provider="local"), mid, 'This frame comes from a stock clip found by searching "' + str(c.get("query"))
                                           + '". The video\'s narration here: "' + vo[:300].replace('"', "'") + '"\nDoes the frame really show '
                                           + str(c.get("query")) + ' (the place or thing itself, not something unrelated), with nothing that contradicts the narration? '
                                           'Reply with JSON only: {"match": true|false}'))
            if not (m or {}).get("match"): _log(log, f"    stock {c['id']} ({c.get('query')}): off-subject"); continue
        except Exception as e:
            _log(log, f"    stock {c['id']}: subject check failed ({str(e)[:60]})"); continue
        good, why = clip_ok(cfg, out, ctx["work"], f"stock_{c['id']}")
        if good: return out, None, f"Pexels/Pixabay '{c.get('query')}' ({c['id']})"
        _log(log, f"    stock {c['id']}: frame check failed ({why})")
    return None, None, f"no usable stock ({len(cands)} found, {tried} checked)"


def _gen_image(ctx, text, key, cfg):
    from . import imagegen
    res = imagegen.generate_many(cfg, ctx["job"], {"vo": text}, key, ctx["log"], aspect="9:16" if ctx["vert"] else "16:9")
    return (Path(res[0][0]), imagegen.last_site()) if res else (None, None)


def _img_rung(ctx, img, tag):
    out = ctx["work"] / f"{img.stem}_i2v.mp4"
    clip = image_to_video(img, out, ctx["need"], ctx["W"], ctx["H"], ctx["log"])
    good, why = clip_ok(ctx["cfg"], clip, ctx["work"], img.stem)
    if good: return clip, img, tag
    ctx["images"].append(img)
    return None, img, f"{tag}: frame check failed ({why})"


def _rung_aiimage(ctx):
    if not ctx["vo"]: return None, None, "no narration for the span"
    img, site = _gen_image(ctx, ctx["vo"], f"qcfix_{ctx['key']}", _cfg_no_google(ctx["cfg"]))
    if not img: return None, None, "no image service produced an image"
    return _img_rung(ctx, img, f"AI image ({site}) -> image-to-video")


def _rung_chatgpt(ctx):
    if not ctx["vo"]: return None, None, "no narration for the span"
    desc, prompt = research(ctx["cfg"], ctx["vo"], ctx["log"])
    ctx["research"] = {"description": desc, "prompt": prompt}
    _log(ctx["log"], f"    prompt: {prompt[:160]}")
    cfg = dict(_cfg_no_google(ctx["cfg"]), imagegen_providers=["chatgpt"])
    img, _ = _gen_image(ctx, prompt, f"qcfix_{ctx['key']}_gpt", cfg)
    if not img: return None, None, "ChatGPT produced no image"
    return _img_rung(ctx, img, "search -> prompt -> ChatGPT -> image-to-video")


def _rung_marble(ctx):
    cfg = ctx["cfg"]
    if not cfg.get("marble_on", False): return None, None, "World Labs Marble not set up (marble_on is off)"
    try:
        from . import marble
    except ImportError:
        return None, None, "World Labs Marble driver not installed"
    clip = marble.scene(cfg, ctx["vo"], ctx["work"] / f"marble_{ctx['key']}.mp4", ctx["need"], (ctx["W"], ctx["H"]), ctx["log"])
    if not clip: return None, None, "Marble made no scene"
    good, why = clip_ok(cfg, clip, ctx["work"], f"marble_{ctx['key']}")
    return (Path(clip), None, "World Labs Marble scene") if good else (None, None, f"Marble scene failed the frame check ({why})")


def _rung_ownframe(ctx):
    ts = [t for t in _clean_times(ctx["mp4"]) if not (ctx["a"] - 0.5 <= t <= ctx["b"] + 0.5)]
    if not ts and Path(ctx["mp4"]).exists():   # no QC report for this source (a raw clip): evenly spaced frames, each frame-checked
        try: dd = media.dur(ctx["mp4"]); ts = [dd * (i + 1) / 6 for i in range(5)]
        except Exception: ts = []
    if not ts: return None, None, "no clean frame recorded in this video"
    ts.sort(key=lambda t: min(abs(t - ctx["a"]), abs(t - ctx["b"])))
    for t in ts[:3]:
        img = ctx["work"] / f"own_{ctx['key']}_{int(t * 10)}.jpg"
        media.ff("-ss", f"{t:.2f}", "-i", ctx["mp4"], "-frames:v", 1, img, check=False, timeout=120)
        if not img.exists(): continue
        clip, im, tag = _img_rung(ctx, img, f"local Python image-to-video of this video's clean frame at {t:.1f}s")
        if clip: return clip, im, tag
    return None, None, "the nearest clean frames failed the frame check after image-to-video"


def _rung_static(ctx):
    for img in ctx["images"]:
        out = still_clip(img, ctx["work"] / f"{img.stem}_still.mp4", ctx["need"], ctx["W"], ctx["H"])
        good, why = clip_ok(ctx["cfg"], out, ctx["work"], f"{img.stem}_still")
        if good: return out, img, f"static image held ({img.name})"
    return None, None, "no image made for this span passed the frame check"


def _rung_card(ctx):
    from . import photos
    text = " ".join((ctx["vo"] or "").split()[:14]) or "..."
    out = photos.headline_clip(text, "", str(ctx["work"] / f"card_{ctx['key']}.mp4"), ctx["need"], (ctx["W"], ctx["H"]))
    return Path(out), None, "headline card"


RUNGS = [("stock", _rung_stock), ("ai_image", _rung_aiimage), ("chatgpt_chain", _rung_chatgpt), ("marble", _rung_marble),
         ("local_i2v_own_frame", _rung_ownframe), ("static_image", _rung_static), ("card", _rung_card)]


# ------------------------------------------------------------------ splice
def fit(clip, L, W, H, fps, out):
    """The replacement cut or held to exactly L seconds at the video's size and rate: a clip shorter than its span holds its
    last frame for the remainder (the static image under the narration)."""
    media.ff("-i", clip, "-an", "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps={fps:.3f},"
             f"tpad=stop_mode=clone:stop_duration={L:.3f},format=yuv420p",   # (no trim / setpts before tpad: ffmpeg 7.0 then does not pad)
             "-t", f"{L:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", out, timeout=600)
    return Path(out)


def splice(mp4, reps, W, H, fps, out):
    """Overlay each replacement (already fitted to its span) over its span; the original audio is copied untouched."""
    ins, flt, chain = ["-i", str(mp4)], [], "[0:v]"
    for k, (a, b, clip) in enumerate(reps, 1):
        ins += ["-i", str(clip)]
        flt.append(f"[{k}:v]setpts=PTS-STARTPTS+{a:.3f}/TB[r{k}]")
        flt.append(f"{chain}[r{k}]overlay=enable='between(t,{a:.3f},{b:.3f})':eof_action=pass[o{k}]"); chain = f"[o{k}]"
    media.ff(*ins, "-filter_complex", ";".join(flt), "-map", chain, "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", out, timeout=3600)
    return Path(out)


def repair(mp4, cfg, job_dir, log=print, stop=lambda: False, vert=False, narration_text=None, rungs=None):
    """Replace every HARD span qc_part marked in <mp4>.qc.json. Never raises (cancel aside); returns the repair report."""
    mp4 = Path(mp4); job_dir = Path(job_dir)
    rep = {"video": mp4.name, "started": time.strftime("%Y-%m-%d %H:%M:%S"), "spans": [], "status": "nothing to repair"}
    rpath = mp4.with_suffix(".repair.json")
    try:
        sp = spans(mp4)
        if not sp:
            rpath.write_text(json.dumps(rep, indent=1), encoding="utf-8"); return rep
        W, H, fps = _probe(mp4); total = media.dur(mp4)
        work = job_dir / "qc" / "repair" / mp4.stem; work.mkdir(parents=True, exist_ok=True)
        _log(log, f"  QC repair: {len(sp)} span(s) in {mp4.name}")
        reps = []
        for i, (a, b, faults) in enumerate(sp):
            if stop(): raise RuntimeError("cancelled")
            a, b = max(0.0, a), min(total, b)
            ctx = {"cfg": cfg, "log": log, "mp4": mp4, "job": job_dir, "vert": vert, "W": W, "H": H, "a": a, "b": b, "need": b - a,
                   "key": f"{mp4.stem[:20]}_{i}", "work": work, "images": [], "vo": narration_text if narration_text is not None else narration(job_dir, mp4, a, b, vert)}
            row = {"span": [round(a, 2), round(b, 2)], "faults": faults, "narration": ctx["vo"][:300], "attempts": [], "fixed_by": None}
            _log(log, f"  QC repair span {a:.1f}-{b:.1f}s ({', '.join(faults)}): " + (f'"{ctx["vo"][:80]}"' if ctx["vo"] else "no narration found"))
            for name, fn in [r for r in RUNGS if not rungs or r[0] in rungs]:
                if stop(): raise RuntimeError("cancelled")
                t0 = time.time()
                try: clip, img, why = fn(ctx)
                except Exception as e:
                    if str(e) == "cancelled" or type(e).__name__ == "Paused": raise
                    clip, img, why = None, None, f"error: {type(e).__name__}: {str(e)[:160]}"
                row["attempts"].append({"rung": name, "ok": bool(clip), "note": why, "secs": round(time.time() - t0, 1)})
                _log(log, f"    {name}: {'OK - ' if clip else 'no - '}{why}")
                if clip:
                    cd = media.dur(clip)
                    row.update(fixed_by=name, how=why, clip=str(clip), clip_secs=round(cd, 2),
                               held_still_secs=round(max(0.0, (b - a) - cd), 2))
                    if cd < (b - a) - 0.05: _log(log, f"    clip is {cd:.1f}s for a {b - a:.1f}s span: last frame held for the rest")
                    reps.append((a, b, fit(clip, b - a, W, H, fps, work / f"fit_{i}.mp4"))); break
            if ctx.get("research"): row["research"] = ctx["research"]
            if not row["fixed_by"]: _log(log, f"  QC repair span {a:.1f}-{b:.1f}s: NOT repaired (every rung failed); left as is")
            rep["spans"].append(row)
        if reps:
            keep = job_dir / "qc" / f"{mp4.stem}_preqc.mp4"
            if not keep.exists(): shutil.copy2(mp4, keep)
            tmp = work / f"{mp4.stem}_repaired.mp4"
            splice(mp4, reps, W, H, fps, tmp)
            if not media.ok(tmp) or abs(media.dur(tmp) - total) > 1.0:
                raise RuntimeError(f"spliced video is wrong ({media.dur(tmp) if media.ok(tmp) else 0:.1f}s vs {total:.1f}s)")
            shutil.copy2(tmp, mp4)
            rep["original"] = str(keep)
        n = sum(1 for r in rep["spans"] if r["fixed_by"])
        rep["status"] = f"{n} of {len(sp)} span(s) repaired"
        _log(log, f"  QC repair: {rep['status']}")
    except Exception as e:
        if str(e) == "cancelled" or type(e).__name__ == "Paused": raise
        rep["status"] = f"repair skipped ({type(e).__name__}: {str(e)[:200]}); video left as it was"
        _log(log, f"  QC repair skipped ({type(e).__name__}: {str(e)[:200]}); the video stages as it is")
    rep["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    try: rpath.write_text(json.dumps(rep, indent=1), encoding="utf-8")
    except OSError: pass
    return rep


def ladder_clip(cfg, text, visual, secs, kind, work, job_dir, src=None, log=print,
                rungs=("stock", "ai_image", "chatgpt_chain", "marble", "local_i2v_own_frame", "static_image")):
    """The repair ladder for a picture that isn't replacing a fault (owner, 2026-10-27: an interview fact's outside media goes
    through the rungs as a QC proof of concept). -> (clip, rung) or (None, ""). Each rung once; every candidate frame-checked;
    attempts logged to <work>/ladder.json. The card rung is left out: the interview has its own fallback under a fact."""
    work = Path(work); work.mkdir(parents=True, exist_ok=True)
    W, H = (1080, 1920) if kind == "short" else (1920, 1080)
    vo = (visual + ". " if visual else "") + text
    ctx = {"cfg": cfg, "log": log, "mp4": Path(src) if src else work / "none.mp4", "job": Path(job_dir), "vert": kind == "short",
           "W": W, "H": H, "a": -1e9, "b": -1e9, "need": float(secs), "key": f"fact_{work.name}_{kind}", "work": work, "images": [], "vo": vo}
    rec = {"text": text, "visual": visual, "secs": round(secs, 2), "attempts": [], "fixed_by": None}
    try:
        for name, fn in [r for r in RUNGS if r[0] in rungs]:
            t0 = time.time()
            try: clip, img, why = fn(ctx)
            except Exception as e:
                if str(e) == "cancelled" or type(e).__name__ == "Paused": raise
                clip, img, why = None, None, f"error: {type(e).__name__}: {str(e)[:160]}"
            rec["attempts"].append({"rung": name, "ok": bool(clip), "note": why, "secs": round(time.time() - t0, 1)})
            _log(log, f"      ladder {name}: {'OK - ' if clip else 'no - '}{why}")
            if clip:
                rec["fixed_by"] = name
                out = fit(clip, secs, W, H, 30.0, work / "fit.mp4")
                return out, f"{name}: {why}"
        return None, ""
    finally:
        if ctx.get("research"): rec["research"] = ctx["research"]
        try: (work / "ladder.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
        except OSError: pass
