"""Long explainer rendered with the Short's architecture (Remotion `Teaser` composition at 1920x1080): one timeline built from
the actual narration. Replaces the ffmpeg section-stitching (assemble.py), whose separate timelines drifted: captions with one
static highlight, the end card inside the last narration slot, audio trimmed to the stitched video, frames lost when an
illustration clip's colour range differed.

  - section timeline = LEAD + narration (actual wav length) + TAIL; the video length is the sum, never a fixed target
  - word times from faster-whisper on each section's narration (captions.word_times, as for the Short) -> the same karaoke
    Captions component as the Short (the spoken word lights up)
  - emoji icons above the caption (captions.pick_emojis), as before but drawn by Remotion
  - visuals laid out on word boundaries; stock / motion clips slowed to fill their slot, then held (never black)
  - end card = its own beat AFTER the narration (no captions, nothing else), "Thanks for watching" + attribution
  - guaranteed visual: a missing file, a failed chart or a near-black frame becomes a branded card (gradient + text), never black
Media are hard-linked into build/public (no copies), audio = the narration with the same padding, loudness-normalised."""
import json, os, re, shutil, subprocess, time
from pathlib import Path
from . import media, captions as C

LEAD, TAIL, END_SECS = 0.4, 0.8, 5.0
W, H = 1920, 1080


def _link(src, pub, sub):
    """Hard-link (or copy) a job file into build/public/<sub>/ -> path relative to public."""
    src = Path(src); d = pub / sub; d.mkdir(parents=True, exist_ok=True)
    dst = d / src.name
    if not dst.exists():
        try: os.link(src, dst)
        except Exception: shutil.copy2(src, dst)
    return f"{sub}/{src.name}"


def _luma_image(p):
    """Mean brightness, or 0 for an image with no content at all (flat colour, std-dev < 3: an empty chart)."""
    try:
        from PIL import Image, ImageStat
        st = ImageStat.Stat(Image.open(p).convert("L").resize((96, 54)))
        return 0.0 if st.stddev[0] < 3 else st.mean[0]
    except Exception: return 0.0


def _luma_video(p, t):
    try:
        r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(p), "-frames:v", "1", "-vf", "scale=32:18,format=gray",
                            "-f", "rawvideo", "-"], capture_output=True, timeout=60)
        return sum(r.stdout) / max(1, len(r.stdout))
    except Exception: return 0.0


def _card(text, kicker=""):
    """The guaranteed visual: branded gradient card (HeadlineBackdrop) with the text."""
    return {"type": "graphic", "g": {"kind": "headline", "kicker": kicker, "text": text[:90], "sub": ""}}


def section_words(cfg, job, s, log):
    """[(word, start, end)] for the section's narration (cached), and its caption groups with emoji (as the old explainer)."""
    d = job / "captions"; d.mkdir(exist_ok=True); f = d / f"words_{s['id']}.json"
    if f.exists(): wt = [tuple(x) for x in json.loads(f.read_text(encoding="utf-8"))]
    else:
        import unicodedata
        text = unicodedata.normalize("NFKD", s["vo"]).encode("ascii", "ignore").decode()
        wt = C.word_times(job / "voice" / f"{s['id']}.wav", text); f.write_text(json.dumps(wt), encoding="utf-8")
    cf = d / f"icons_{s['id']}.json"
    if cf.exists(): groups = json.loads(cf.read_text(encoding="utf-8"))
    else:
        groups = C.groups(wt)
        try: groups = C.pick_emojis(cfg, groups, log)
        except Exception as e: log(f"  emoji pick failed for {s['id']} ({str(e)[:80]})")
        cf.write_text(json.dumps(groups, ensure_ascii=False), encoding="utf-8")
    return wt, groups


def _bounds(wt, n, D):
    """n visual slots over the section, cut on word starts near equal time splits."""
    starts = [LEAD + a for _, a, _ in wt] or [0.0]
    b = [0.0]
    for i in range(1, n):
        target = D * i / n
        cand = min(starts, key=lambda x: abs(x - target)) if starts else target
        b.append(max(b[-1] + 0.8, cand))
    b.append(D)
    if b[-2] >= D - 0.5: b = [D * i / n for i in range(n + 1)]   # degenerate (few words): even split
    return b


def _visual_bg(job, pub, v, slot, s, log):
    """One visual -> a Teaser background, or the branded card."""
    title = s.get("title") or ""
    if v.get("g") and not v.get("edit_clip"):   # illustration / silhouette / card / simulation: drawn live
        return {"type": "graphic", "g": v["g"], **({"tag": v["tag"]} if v.get("tag") else {})}
    if v.get("layers") and not v.get("edit_clip") and all((job / x).is_file() for x in v["layers"]):   # rembg parallax of a generated image
        return {"type": "layers", "layers": [_link(job / x, pub, "img") for x in v["layers"]], **({"tag": v["tag"]} if v.get("tag") else {})}
    try:
        if v.get("edit_clip") and (job / v["edit_clip"]).exists(): src = job / v["edit_clip"]; kind = "video"
        elif v.get("stock"):
            src = job / v["stock"]; kind = "image" if src.suffix.lower() in (".jpg", ".jpeg", ".png") else "video"
        elif v["type"] == "motion": src = job / "motion" / f"{v['id']}.mp4"; kind = "video"
        elif v["type"] == "chart": src = job / "charts" / f"{v['id']}.png"; kind = "chart"
        else: src = job / "stills" / f"{v['id']}.jpg"; kind = "image"
        if not src.exists():
            log(f"  {v['id']}: {src.name} missing -> branded card"); return _card(title or s["vo"][:80])
        if kind == "chart":
            if _luma_image(src) < 8:
                ch = v.get("chart") or {}
                text = " ".join(str(x) for x in ch.get("lines") or []) or ch.get("title") or ch.get("text") or title
                log(f"  {v['id']}: chart is blank -> branded card"); return _card(text)
            return {"type": "image", "src": _link(src, pub, "charts"), "fit": "still"}
        if kind == "image":
            if _luma_image(src) < 6: log(f"  {v['id']}: image is black -> branded card"); return _card(title or s["vo"][:80])
            bg = {"type": "image", "src": _link(src, pub, "img")}
            if v.get("credit"): bg.update(fit="frame", credit=v.get("short_credit") or "")
            if v.get("tag") and (v.get("stock_src") == "source" or str(v["tag"]).startswith("GENERATED · ")): bg["tag"] = v["tag"]
            return bg
        d = media.dur(src) or 0.1
        if _luma_video(src, d / 2) < 6: log(f"  {v['id']}: clip is black -> branded card"); return _card(title or s["vo"][:80])
        rate = max(0.6, min(1.0, d / max(slot, 0.1)))
        bg = {"type": "video", "src": _link(src, pub, "vid"), "rate": round(rate, 3)}
        if d / rate < slot - 0.1: bg["freezeAt"] = round(max(0.1, d / rate - 0.12), 2)   # shorter even slowed: hold its last frame
        if v.get("tag") and (v.get("stock_src") == "source" or str(v.get("tag")).startswith("GENERATED · ")): bg["tag"] = v["tag"]
        log(f"  {v['id']}: video {src.name} ({d:.1f}s{', ' + v['tag'] if bg.get('tag') else ''}) in a {slot:.1f}s slot")
        return bg
    except Exception as e:
        log(f"  {v.get('id')}: {str(e)[:80]} -> branded card"); return _card(title or s["vo"][:80])


def build(job, plan, cfg, log, stop=lambda: False):
    """Write build/public/teaser.json + voice.wav for the whole explainer. -> total seconds."""
    b = job / "build"; pub = b / "public"; pub.mkdir(parents=True, exist_ok=True)
    beats, t, audio_parts = [], 0.0, []
    secs = plan["sections"]
    from .pipeline import progress
    for si, s in enumerate(secs):
        if stop(): raise RuntimeError("cancelled")
        progress(job, si + 1, len(secs))
        vo = job / "voice" / f"{s['id']}.wav"; vd = media.dur(vo)
        D = LEAD + vd + TAIL
        wt, groups = section_words(cfg, job, s, log)
        vis = list(s["visuals"])
        if si == 0: vis = [{"id": "_title", "type": "chart"}] + vis
        bnd = _bounds(wt, len(vis), D)
        # a source clip is ~2.5 s: it gets only its own length (plus 0.4 s), the neighbouring visual takes the rest of the
        # slot. Stretched over a whole slot it played slowed, then froze for up to 15 s and looked like a still.
        for vi, v in enumerate(vis):
            if v.get("stock_src") != "source" or len(vis) < 2 or not (job / v.get("stock", "")).is_file(): continue
            d = (media.dur(job / v["stock"]) or 2.5) + 0.4
            if bnd[vi + 1] - bnd[vi] <= d + 0.5: continue
            if vi + 1 < len(vis):   # the later visuals share the freed time evenly, starting right after the clip
                a, rest = bnd[vi] + d, len(vis) - vi - 1
                for k in range(1, rest + 1): bnd[vi + k] = a + (D - a) * (k - 1) / rest
            else:                   # last slot: the earlier visuals share the freed time
                b = bnd[vi + 1] - d
                for k in range(1, vi): bnd[k] = b * k / vi
                bnd[vi] = b
        bgs = []
        for vi, v in enumerate(vis):
            slot = bnd[vi + 1] - bnd[vi]
            if v.get("edit_bgs"):   # replaced in the post-render editor (edit.py): the same backgrounds, in the same slot
                k = slot / max(0.1, float(v.get("edit_slot") or slot))   # offsets scale if the slot's length changed
                for eb in v["edit_bgs"]:
                    bg = dict(eb); bg["from"] = round(bnd[vi] + min(slot - 0.05, eb.get("from", 0) * k), 3); bg["slot"] = vi; bgs.append(bg)
                continue
            bg = _visual_bg(job, pub, v, slot, s, log); bg["from"] = round(bnd[vi], 3)
            if v.get("illustration"): bg["tag"] = "ILLUSTRATION" if v["illustration"] == "illustration" else "SILHOUETTE"
            bgs.append(bg)
        words = [[w, round(LEAD + a, 3), round(LEAD + e, 3)] for w, a, e in wt]
        icons = [{"at": round(LEAD + g["start"], 3), "dur": round(max(0.8, g["end"] - g["start"]), 3), "e": g["emoji"]} for g in groups if g.get("emoji")]
        beats.append({"id": s["id"], "start": round(t, 3), "dur": round(D, 3), "words": words, "bgs": bgs, "graphics": [], "icons": icons})
        audio_parts.append((vo, D)); t += D
    # end card: its own beat after the narration - no captions, no icons
    endp = job / "charts" / "_end.png"
    end_bg = {"type": "image", "src": _link(endp, pub, "charts"), "fit": "still", "from": 0} if endp.exists() else dict(_card("Thanks for watching"), **{"from": 0})
    beats.append({"id": "end", "start": round(t, 3), "dur": END_SECS, "words": [], "bgs": [end_bg], "graphics": [], "icons": []})
    total = t + END_SECS
    # audio: every section's narration with the same LEAD / TAIL padding, then silence under the end card; loudness-normalised
    ins, fl = [], []
    for i, (vo, D) in enumerate(audio_parts):
        ins += ["-i", str(vo)]
        fl.append(f"[{i}:a]aresample=48000,adelay={int(LEAD * 1000)}:all=1,apad,atrim=duration={D:.3f}[a{i}]")
    fl.append("".join(f"[a{i}]" for i in range(len(audio_parts))) + f"concat=n={len(audio_parts)}:v=0:a=1,apad,atrim=duration={total:.3f},"
              "equalizer=f=120:t=q:w=1:g=2,loudnorm=I=-16:TP=-1.5:LRA=11[out]")
    media.ff(*ins, "-filter_complex", ";".join(fl), "-map", "[out]", "-ar", 48000, pub / "voice.wav")
    data = {"audio": "voice.wav", "total": round(total, 3), "tag": "", "beats": beats, "w": W, "h": H, "progress": False}
    from .render_media import sanitize_timeline
    sanitize_timeline(data, pub, log, stop)
    (pub / "teaser.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    log(f"Explainer timeline: {total:.1f}s ({len(secs)} sections from the narration + {END_SECS:.0f}s end card)")
    return total


def render(job, plan, cfg, meta, log, stop=lambda: False, out_name=None):
    from . import short
    total = build(job, plan, cfg, log, stop)
    rdir = short._ensure_remotion(log)
    o = job / "output"; o.mkdir(exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9]+", "_", plan["title"])[:60].strip("_") or "explainer"
    final = o / (out_name or f"{slug}_explainer_1080p.mp4"); tmp = o / "_explainer_rendering.mp4"
    cmd = [short._npx(), "remotion", "render", "src/Root.tsx", "Teaser", str(tmp), f"--public-dir={job / 'build' / 'public'}",
           f"--props={job / 'build' / 'public' / 'teaser.json'}", f"--concurrency={cfg.get('short_concurrency', '75%')}",
           "--jpeg-quality=100", "--crf=16", "--log=info", f"--gl={short._gl(cfg)}"]
    log(f"Rendering the explainer with Remotion ({total / 60:.1f} min of video)...")
    for attempt in range(3):
        p = subprocess.Popen(cmd, cwd=rdir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        last, t0, tail = "", time.time(), []
        for line in p.stdout:
            line = line.strip()
            if line: last = line; tail = (tail + [line])[-40:]
            if "VS-MEDIA-ERROR" in line: log("  Remotion media error: " + line[line.index("VS-MEDIA-ERROR") + 15:][:300])
            if time.time() - t0 > 60 and last: log("  " + last[:160]); t0 = time.time()
            if stop(): p.kill(); raise RuntimeError("cancelled")
        if p.wait() == 0: break
        if attempt < 2 and any(short.BROWSER_FLAKE in l for l in tail):
            log(f"  Remotion couldn't connect to its browser in time; retrying ({attempt + 2} of 3)"); time.sleep(10); continue
        for l in tail[-15:]: log("  | " + l[:200])
        raise RuntimeError("Remotion explainer render failed: " + " / ".join(x for x in tail[-4:] if x)[:400])
    if final.exists(): final.unlink()
    media.ff("-i", tmp, "-c", "copy", "-movflags", "+faststart", final); tmp.unlink(missing_ok=True)
    if not out_name: _srt_and_description(job, plan, meta, o, slug, log)
    log(f"FINAL: {final} ({media.dur(final) / 60:.1f} min)")
    return final


def _srt_and_description(job, plan, meta, o, slug, log):
    """SRT from the real word times (the same timeline as the video) + YouTube description with chapters."""
    tl = json.loads((job / "build" / "public" / "teaser.json").read_text(encoding="utf-8"))
    def ts(x): h = int(x // 3600); m = int(x % 3600 // 60); s = x % 60; return f"{h:02}:{m:02}:{s:06.3f}".replace(".", ",")
    srt = []
    for bt in tl["beats"]:
        ws = bt["words"]
        for i in range(0, len(ws), 12):
            g = ws[i:i + 12]; srt.append((bt["start"] + g[0][1], bt["start"] + g[-1][2], " ".join(w[0] for w in g)))
    (o / f"{slug}.srt").write_text("".join(f"{i + 1}\n{ts(a)} --> {ts(b)}\n{x}\n\n" for i, (a, b, x) in enumerate(srt)), encoding="utf-8")
    def mmss(x): return f"{int(x // 60)}:{int(x % 60):02}"
    chap = [(bt["start"], s["title"]) for bt, s in zip(tl["beats"], plan["sections"])]
    desc = (plan.get("youtube_description") or "") + "\n\n" + "\n".join(f"{mmss(a)} {n}" for a, n in chap)
    desc += f"\n\nSource: \"{meta.get('title', '')}\" — {meta.get('channel') or meta.get('uploader') or ''}\n{meta.get('webpage_url', '')}\n"
    creds = sorted({v["credit"] for s in plan["sections"] for v in s["visuals"] if v.get("credit")})
    if creds: desc += "\n" + "\n".join(creds) + "\n"
    (o / "youtube_description.txt").write_text(desc, encoding="utf-8")
