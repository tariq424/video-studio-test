"""Assemble sections (Ken Burns stills, charts, motion, PIP presenter, narration) into the final 1080p video."""
import json, re
from pathlib import Path
from . import media
FPS, W, H = 24, 1920, 1080
LEAD, TAIL = 0.4, 0.8
PIP_W, PIP_M = 576, 48
ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", 17, "-pix_fmt", "yuv420p"]

def _visual(job, v, slot, out, k):
    nfr = int(round(slot * FPS))
    if v.get("stock"):   # real footage: slow it down up to 1.4x to fill the slot, then hold the last frame if still short
        src = job / v["stock"]; dd = media.dur(src); f = min(1.4, max(1.0, slot / max(dd, 0.1)))
        media.ff("-i", src, "-an", "-vf", f"setpts={f:.4f}*PTS,fps={FPS},scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},setsar=1,tpad=stop_mode=clone:stop_duration={slot:.3f},trim=duration={slot:.3f}", "-frames:v", nfr, *ENC, out)
        return
    if v["type"] == "motion":
        src = job / "motion" / f"{v['id']}.mp4"; f = slot / media.dur(src)
        media.ff("-i", src, "-an", "-vf", f"setpts={f:.4f}*PTS,fps={FPS},scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},setsar=1,trim=duration={slot:.3f}", "-frames:v", nfr, *ENC, out)
        return
    if v["type"] == "chart": src, z, d = job / "charts" / f"{v['id']}.png", 0.035, "center"
    else: src, z, d = job / "stills" / f"{v['id']}.jpg", 0.10, ["center", "left", "right", "up"][k % 4]
    px = {"center": "iw/2-(iw/zoom/2)", "left": f"(iw-iw/zoom)*(on/{nfr})", "right": f"(iw-iw/zoom)*(1-on/{nfr})", "up": "iw/2-(iw/zoom/2)"}[d]
    py = f"(ih-ih/zoom)*(1-on/{nfr})" if d == "up" else "ih/2-(ih/zoom/2)"
    media.ff("-loop", 1, "-i", src, "-vf", f"scale=3840:2160:force_original_aspect_ratio=increase,crop=3840:2160,zoompan=z='1+{z}*on/{nfr}':x='{px}':y='{py}':d={nfr}:s={W}x{H}:fps={FPS},setsar=1", "-frames:v", nfr, *ENC, out)

def build(job, plan, log, stop=lambda: False, use_presenter=True, use_captions=True):
    b = job / "build"; b.mkdir(exist_ok=True)
    segs = json.loads((job / "presenter" / "segments.json").read_text()) if use_presenter and (job / "presenter" / "segments.json").exists() else []
    secs = plan["sections"]; parts = []
    for si, s in enumerate(secs):
        if stop(): raise RuntimeError("cancelled")
        out = b / f"sec_{s['id']}.mp4"; vo = job / "voice" / f"{s['id']}.wav"
        if media.ok(out, 5): parts.append(out); continue
        D = LEAD + media.dur(vo) + TAIL
        vis = list(s["visuals"])
        if si == 0: vis = [{"id": "_title", "type": "chart"}] + vis
        if si == len(secs) - 1: vis = vis + [{"id": "_end", "type": "chart"}]
        cj = job / "captions" / f"v2_{s['id']}.json"
        caps = json.loads(cj.read_text(encoding="utf-8")) if (use_captions and cj.exists()) else []
        # scene cuts on sentence boundaries: each visual covers whole sentences
        bounds = [0.0]
        if len(caps) >= len(vis):
            for i in range(1, len(vis)):
                bounds.append(LEAD + caps[round(i * len(caps) / len(vis))]["start"])
        else:
            bounds += [D * i / len(vis) for i in range(1, len(vis))]
        bounds.append(D)
        slots = [max(0.8, bounds[i + 1] - bounds[i]) for i in range(len(vis))]
        clips = []
        for vi, v in enumerate(vis):
            o = b / f"v_{s['id']}_{vi}.mp4"
            if not media.ok(o, 0.3): _visual(job, v, slots[vi], o, si + vi)
            clips.append(o)
        lst = b / f"c_{s['id']}.txt"; lst.write_text("".join(f"file '{c.as_posix()}'\n" for c in clips), encoding="utf-8")
        sv = b / f"sv_{s['id']}.mp4"; media.ff("-f", "concat", "-safe", 0, "-i", lst, "-c", "copy", sv)
        Dv = media.dur(sv)
        ins = ["-i", sv, "-i", vo]; fc = [f"[0:v]fade=t=in:st=0:d=0.3,fade=t=out:st={Dv-0.35:.3f}:d=0.35[b0]"]; last = "b0"; n = 2
        for g in [g for g in segs if g["sid"] == s["id"]]:
            p = job / "presenter" / f"{g['sid']}_{g['kind']}.mp4"
            if not p.exists(): continue
            t0 = LEAD + g["start"]; d = g["dur"]; ins += ["-i", p]
            fc.append(f"[{n}:v]fps={FPS},scale={PIP_W}:-2,setsar=1,trim=duration={d:.3f},pad=iw+8:ih+8:4:4:color=white,format=yuva420p,fade=t=in:st=0:d=0.3:alpha=1,"
                      f"fade=t=out:st={max(d-0.3,0):.3f}:d=0.3:alpha=1,setpts=PTS-STARTPTS+{t0:.3f}/TB[p{n}]")
            fc.append(f"[{last}][p{n}]overlay=x={W-PIP_W-PIP_M}:y=H-h-{PIP_M}:eof_action=pass:enable='between(t,{t0:.3f},{t0+d:.3f})'[b{n}]"); last = f"b{n}"; n += 1
        if caps:
            from . import captions as C
            charts_t = [(bounds[vi], bounds[vi + 1]) for vi, v in enumerate(vis) if v["type"] == "chart"]
            for c in caps:
                if not c.get("emoji_png"): continue
                if not Path(c["emoji_png"]).exists() and not C.emoji_png(c["emoji"], c["emoji_png"]): continue
                t0 = LEAD + c["start"]; d = max(0.4, c["end"] - c["start"])
                if any(a - 0.2 <= t0 < b for a, b in charts_t): continue   # no icons over chart slides
                # input runs from t=0 for the whole section (late-starting inputs stall ffmpeg 7 on Windows)
                ins += ["-loop", "1", "-framerate", str(FPS), "-t", f"{Dv:.3f}", "-i", c["emoji_png"]]
                fc.append(f"[{n}:v]format=rgba,fade=t=in:st={t0:.3f}:d=0.12:alpha=1[e{n}]")
                nl = max(1, -(-len(" ".join(c["words"])) // 46))
                ey = 1010 - nl * 72 - 140
                fc.append(f"[{last}][e{n}]overlay=x=(W-w)/2:y={ey}:eof_action=pass:enable='between(t,{t0:.3f},{t0+d:.3f})'[b{n}]"); last = f"b{n}"; n += 1
            C.write_ass(caps, b / f"caps_{s['id']}.ass", offset=LEAD, low=charts_t)
            fc.append(f"[{last}]ass=caps_{s['id']}.ass[bc]"); last = "bc"
        fc.append(f"[1:a]adelay={int(LEAD*1000)}:all=1,apad,atrim=duration={Dv:.3f}[a]")
        media.ff(*[x if not isinstance(x, Path) else x.resolve() for x in ins], "-filter_complex", ";".join(fc), "-map", f"[{last}]", "-map", "[a]", "-t", f"{Dv:.3f}", *ENC, "-c:a", "aac", "-b:a", "192k", out.resolve(), cwd=str(b))
        parts.append(out); log(f"Assembled {s['id']} ({Dv:.1f}s, {len(vis)} visuals)")
    return parts

def finalize(job, plan, parts, meta, log):
    b = job / "build"; o = job / "output"; o.mkdir(exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9]+", "_", plan["title"])[:60].strip("_") or "explainer"
    lst = b / "final.txt"; lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    media.ff("-f", "concat", "-safe", 0, "-i", lst, "-vn", "-af", "equalizer=f=120:t=q:w=1:g=2,loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", 48000, b / "final_audio.wav")
    media.ff("-f", "concat", "-safe", 0, "-i", lst, "-an", "-c:v", "copy", b / "final_video.mp4")
    final = o / f"{slug}_explainer_1080p.mp4"
    media.ff("-i", b / "final_video.mp4", "-i", b / "final_audio.wav", "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", final)
    # captions + chapters
    def ts(x): h = int(x // 3600); m = int(x % 3600 // 60); s = x % 60; return f"{h:02}:{m:02}:{s:06.3f}".replace(".", ",")
    srt, chap, t = [], [], 0.0
    for s, p in zip(plan["sections"], parts):
        Dv = media.dur(p); chap.append((t, s["title"]))
        vo = job / "voice" / f"{s['id']}.wav"; sents = [x.strip() for x in re.findall(r"[^.?!]+[.?!]+", s["vo"])] or [s["vo"]]
        words = sum(len(x.split()) for x in sents); vt = media.dur(vo) - 0.25 * max(1, round(words / 80)); cur = t + LEAD
        for x in sents:
            wl = x.split(); L = vt * len(wl) / max(words, 1)
            for i in range(0, len(wl), 14):
                pc = " ".join(wl[i:i + 14]); pl = L * len(pc.split()) / len(wl); srt.append((cur, cur + pl, pc)); cur += pl
        t += Dv
    (o / f"{slug}.srt").write_text("".join(f"{i+1}\n{ts(a)} --> {ts(b_)}\n{x}\n\n" for i, (a, b_, x) in enumerate(srt)), encoding="utf-8")
    def mmss(x): return f"{int(x//60)}:{int(x%60):02}"
    desc = (plan.get("youtube_description") or "") + "\n\n" + "\n".join(f"{mmss(a)} {n}" for a, n in chap)
    desc += f"\n\nSource: \"{meta.get('title','')}\" — {meta.get('channel') or meta.get('uploader') or ''}\n{meta.get('webpage_url','')}\n"
    (o / "youtube_description.txt").write_text(desc, encoding="utf-8")
    log(f"FINAL: {final} ({media.dur(final)/60:.1f} min)")
    return final
