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
    d = job / "voice"; d.mkdir(exist_ok=True)
    gap = d / "_gap.wav"; media.ff("-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", 0.25, gap)
    seed = 9000
    for si, s in enumerate(plan["sections"]):
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

def do_motion(job, plan, cfg, wg, log, stop):
    d = job / "motion"; d.mkdir(exist_ok=True); seed = 3000
    for s in plan["sections"]:
        for v in s["visuals"]:
            if v["type"] != "motion" or v.get("stock"): continue
            seed += 1; out = d / f"{v['id']}.mp4"
            if media.ok(out): continue
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
    todo = [v for s in plan["sections"] for v in s["visuals"] if v["type"] == "still" and not v.get("stock")]
    for i, v in enumerate(todo):
        seed += 1; out = d / f"{v['id']}.jpg"
        if out.exists(): continue
        if not _still(cfg, wg, log, v["prompt"], out, seed, stop, f"still {v['id']}"):
            raise RuntimeError(f"still {v['id']} failed")
        n += 1
        if n % 10 == 0: log(f"Stills: {i+1}/{len(todo)}")
    log(f"Stills done: {len(todo)}")
