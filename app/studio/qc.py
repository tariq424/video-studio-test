"""Frame quality check for every finished video (owner, 2026-10-24): smudges, fingers, sideways / upside-down picture, blur,
clothing or giant-face close-ups, black frames. Uses this PC's local vision model (Ollama); without it the check is skipped.
  qc_part   a frame every few seconds; a failing stretch is covered, under the same sound, by a still (turned upright when it
            was upside down, else the nearest clean frame, else blurred)
  qc_final  a frame every 10-30 s of the finished video -> <video>_qc.jpg (failures red) + <video>_qc.json

Recalibration (v2, 2026-10-26, after the first run flagged most frames of the news Shorts and the videos had to be
restored from preqc):
  - two-agree: a flagged frame is re-checked with a strict confirmation prompt; the fault counts only if both agree.
  - persistence: a hard fault counts only when the SAME problem appears in at least 2 consecutive samples;
    a single-sample hit (transition, cut) is recorded as ignored and never fixed.
  - hard / soft split: HARD faults (sideways, upside_down, black, finger, smudge) may be covered by a still;
    SOFT faults (blurry, face_closeup, clothing_closeup) are reported only, never auto-fixed.
  - qc_mode: cfg "qc_mode" = "report" (default) only reports - it never modifies the video; "fix" covers hard spans.
  - unchecked frames (vision model error) are counted, never silently passed: if more than 10% of a video's
    samples are unchecked, its QC status in the report is "incomplete", not "passed".

v3 (2026-10-26, after smoke test 1: specimen A passed, B's sideways / upside-down / black were all missed):
  - black is detected from pixels, not by asking the model: a frame whose mean luminance is under 6 is black.
  - persistence is resolved adaptively: an isolated hard flag probes the frames halfway to its neighbouring
    samples (+/- half a step); the same problem there confirms it. A 10 s fault can no longer fall between
    samples at a 6 s interval and die on the two-in-a-row rule.
  - the vision prompts judge orientation FIRST, using any visible text / captions / faces as the anchor, and an
    upside-down face is upside_down, not face_closeup.
  - every sample's first and confirmation verdicts are recorded in the reports ("samples" / row fields),
    so a miss can be attributed: the first look, or the confirmation.

v4 (2026-10-26, after smoke round 2: A failed - the orientation-first prompt made qwen2.5vl:7b call 24 of 30
upright samples sideways; B's black was named by both checks but dropped, and the pixel test missed it):
  - the vision prompts revert to the round-1 wording (A was clean under it). The model's DIRECT sideways /
    upside_down verdicts are ignored entirely - two rounds proved they are noise in both directions.
  - orientation is decided by rotate-and-compare instead: a 4-panel strip (as-is, 180, 90, 90 the other way)
    and one question - which panel looks upright and readable? "Cannot tell" is a valid answer and flags nothing.
  - two-agree is judged on the problem field alone: if both checks name the same problem it is confirmed,
    whatever the ok fields say (round 2's confirm replied ok:true with problem "black" and was discarded).
  - the pixel black test is a FLAT-black test: mean luminance under 24 AND stddev under 4. Limited-range video
    black measures 16, not 0; a dark but real scene has texture, a black frame does not.
"""
import json
import shutil
from pathlib import Path

from . import media

ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-profile:v", "high"]

QCVER = 4
HARD = ("sideways", "upside_down", "black", "finger", "smudge")
SOFT = ("blurry", "face_closeup", "clothing_closeup")


def _log(log, m):
    (log or print)(m)


def available(cfg):
    if cfg.get("vet_provider", "local") not in ("local", "", None) and cfg.get("qc_provider", "local") != "local": return True
    try:
        import requests
        return requests.get(cfg.get("ollama_url", "http://127.0.0.1:11434").rstrip("/") + "/api/tags", timeout=4).status_code == 200
    except Exception:
        return False


QC = """Quality check of one frame from a finished travel documentary. Reply with JSON only:
{"ok": true|false, "problem": "none|finger|smudge|sideways|upside_down|blurry|clothing_closeup|face_closeup|black"}
Not ok: a finger or hand over the lens, a smudge or fog on the lens, a picture lying on its side or upside down, a blurry smear,
a close-up of clothing filling the frame, one person's face filling most of the frame, or a black / empty frame."""

CONFIRM = """A first quality check of this single frame claimed the problem: "{problem}".
Be strict: confirm ONLY if that exact fault is obvious in this frame. A normal shot - including a person's face
in a talking-head shot, a dark but visible scene, or a frame caught mid-transition - is NOT a fault.
Reply with JSON only: {{"ok": true|false, "problem": "none|finger|smudge|sideways|upside_down|blurry|clothing_closeup|face_closeup|black"}}"""

ORIENT = """Four versions of one picture side by side, numbered 1 to 4 from the left. Version 1 is the picture as-is;
versions 2, 3 and 4 are the same picture rotated: 180 degrees, 90 degrees one way, 90 degrees the other way.
Look at any text or captions, at faces, and at which way is up in the scene. Reply with JSON only:
{"upright": 1} - the number of the version that looks upright and readable.
If there is no readable text and no clear up or down in the scene, or you cannot tell, reply {"upright": "none"}."""


def _pixel_flat_black(img):
    """A black frame is a measurement, not an opinion: FLAT black - mean luminance under 24 (limited-range
    video black measures 16, not 0) AND stddev under 4 (a dark but real scene has texture; a black frame has none)."""
    try:
        from PIL import Image, ImageStat
        st = ImageStat.Stat(Image.open(img).convert("L"))
        return st.mean[0] < 24.0 and st.stddev[0] < 4.0
    except Exception: return False


def _judge(cfg, img):
    """-> {"state": "ok"|"bad"|"unchecked", "prob", "raw", "first", "confirm", "via"}.
    Black is decided from pixels. Anything else: a flag is the problem FIELD of the first check; it stands
    only when the confirmation check names the SAME problem (the ok fields are ignored - the model pairs
    ok:true with a named problem too often to trust them). Direct sideways / upside_down verdicts are
    recorded but never acted on: orientation is decided separately, by rotate-and-compare."""
    if _pixel_flat_black(img): return {"state": "bad", "prob": "black", "raw": "black", "first": "pixel", "confirm": "pixel", "via": "pixel"}
    from . import footage
    from .llm import parse_json
    try: j = parse_json(footage._vision(dict(cfg, vet_provider="local"), img, QC))
    except Exception: return {"state": "unchecked", "prob": "unchecked", "raw": "", "first": "error", "confirm": "", "via": "model"}
    prob = str(j.get("problem") or "none").strip().lower()
    if prob in ("none", ""): return {"state": "ok", "prob": "none", "raw": prob, "first": prob, "confirm": "", "via": "model"}
    try: j2 = parse_json(footage._vision(dict(cfg, vet_provider="local"), img, CONFIRM.format(problem=prob)))
    except Exception: return {"state": "unchecked", "prob": prob, "raw": prob, "first": prob, "confirm": "error", "via": "model"}
    prob2 = str(j2.get("problem") or "none").strip().lower()
    if prob2 != prob: return {"state": "ok", "prob": "none", "raw": prob, "first": prob, "confirm": prob2, "via": "model"}
    if prob in ("sideways", "upside_down"):   # both checks agree, and it still doesn't count: see _orientation
        return {"state": "ok", "prob": "none", "raw": prob, "first": prob, "confirm": prob2, "via": "model"}
    return {"state": "bad", "prob": prob, "raw": prob, "first": prob, "confirm": prob2, "via": "model"}


def _orientation(cfg, img):
    """Rotate-and-compare: one strip (as-is | 180 | 90 | 90 the other way), one question - which panel is
    upright? -> "upside_down" | "sideways" | None (panel 1, "none", or any failure: no evidence, no flag)."""
    try:
        from PIL import Image
        im = Image.open(img).convert("RGB")
        panels = [im, im.transpose(Image.ROTATE_180), im.transpose(Image.ROTATE_90), im.transpose(Image.ROTATE_270)]
        H = 512; rs = []
        for p in panels:
            rs.append(p.resize((max(1, int(p.width * H / p.height)), H)))
        strip = Image.new("RGB", (sum(p.width for p in rs), H))
        x = 0
        for p in rs: strip.paste(p, (x, 0)); x += p.width
        sp = Path(img).with_name(Path(img).stem + "_o4.jpg"); strip.save(sp, quality=80)
    except Exception: return None
    from . import footage
    from .llm import parse_json
    try: j = parse_json(footage._vision(dict(cfg, vet_provider="local"), sp, ORIENT))
    except Exception: return None
    try: u = int(j.get("upright"))
    except Exception: return None
    if u == 2: return "upside_down"
    if u in (3, 4): return "sideways"
    return None


def _judge_frame(cfg, img):
    """Full per-frame verdict: the model/pixel judge, plus rotate-and-compare orientation when the frame
    wasn't already judged bad or unchecked."""
    v = _judge(cfg, img)
    if v["state"] != "ok": return v
    o = _orientation(cfg, img)
    if o: return {"state": "bad", "prob": o, "raw": o, "first": "panel", "confirm": "panel", "via": "orient"}
    return v


def _flags(samples):
    return [(s["state"] == "bad" and s["prob"] in HARD) for s in samples]


def _resolve(samples, probe):
    """Persistence, resolved adaptively. A hard flag stands when the same problem appears in a neighbouring
    sample; an ISOLATED hard flag probes the frames halfway to its neighbours (probe(t, prob) -> verdict dict
    or None) and stands only if the same problem shows there. Sets s["rescued"] on probed samples."""
    flags = _flags(samples); keep = list(flags)
    for i, f in enumerate(flags):
        if not f: continue
        prev_ok = i > 0 and flags[i - 1] and samples[i - 1]["prob"] == samples[i]["prob"]
        next_ok = i < len(samples) - 1 and flags[i + 1] and samples[i + 1]["prob"] == samples[i]["prob"]
        if prev_ok or next_ok: continue
        s = samples[i]
        step = (samples[i + 1]["t"] - s["t"]) if i + 1 < len(samples) else ((s["t"] - samples[i - 1]["t"]) if i > 0 else 4.0)
        rescued = False
        if probe:
            for dt in (-step / 2, step / 2):
                v = probe(s["t"] + dt, s["prob"])
                if v and v.get("state") == "bad" and v.get("prob") == s["prob"]: rescued = True; break
        keep[i] = rescued; s["rescued"] = rescued
    return keep


def _mode(cfg):
    m = str(cfg.get("qc_mode", "report") or "report").strip().lower()
    return m if m in ("report", "fix") else "report"


def qc_part(path, cfg, log=print, every=4.0, label="", kind="documentary"):
    """Owner, 2026-10-24: check every piece before it is stitched in. A frame every `every` seconds goes to the local vision
    model (twice, if the first check flags it); a confirmed HARD fault that persists across samples (+/- 2 s) is replaced,
    under the same sound, by a still: the frame turned right side up when it was upside down, else the nearest clean frame
    of the same piece, else that frame blurred. In report mode (default) nothing is replaced - the spans are only
    logged and written to the report. Cached: <piece>.qc.json (keyed by size, QC version and mode)."""
    path = Path(path); rep = path.with_suffix(".qc.json"); mode = _mode(cfg)
    if rep.exists():
        try:
            old = json.loads(rep.read_text(encoding="utf-8"))
            if old.get("size") == path.stat().st_size and old.get("qcver") == QCVER and old.get("mode") == mode: return path
        except Exception: pass
    d = media.dur(path)
    if d < 1.5: return path
    tmp = path.with_suffix(""); tmp.mkdir(exist_ok=True)
    times = [min(d - 0.3, 1.0 + k * every) for k in range(int(max(0.0, d - 1.0) // every) + 1)]
    samples = []
    for k, t in enumerate(times):
        img = tmp / f"qc{k:03}.jpg"
        media.ff("-ss", f"{t:.2f}", "-i", path, "-frames:v", 1, "-vf", "scale=768:-2", img, timeout=120)
        v = _judge_frame(cfg, img) if img.exists() else {"state": "unchecked", "prob": "unchecked", "raw": ""}
        samples.append({"t": t, "img": img, **v})
    nun = sum(1 for s in samples if s["state"] == "unchecked")
    incomplete = bool(samples) and nun / len(samples) > 0.10
    def probe(t2, prob):
        if t2 < 0 or t2 > d - 0.3: return None
        img2 = tmp / f"qcR{int(t2 * 10)}.jpg"
        media.ff("-ss", f"{t2:.2f}", "-i", path, "-frames:v", 1, "-vf", "scale=768:-2", img2, timeout=120)
        return _judge_frame(cfg, img2) if img2.exists() else None
    keep = _resolve(samples, probe)
    bad = [(s["t"], s["prob"], s["img"]) for s, k in zip(samples, keep) if k]
    single = [(s["t"], s["prob"]) for s, k in zip(samples, keep)
              if s["state"] == "bad" and s["prob"] in HARD and not k]
    soft = [(s["t"], s["prob"]) for s in samples if s["state"] == "bad" and s["prob"] in SOFT]
    for t, prob in single: _log(log, f"    QC {label}: {t:.1f}s {prob} ignored (single sample, not persistent)")
    spans = []
    for t, prob, img in bad:
        a, b = max(0.0, t - every / 2 - 0.5), min(d, t + every / 2 + 0.5)
        if spans and a <= spans[-1][1]: spans[-1][1] = max(spans[-1][1], b); spans[-1][2].append((t, prob, img))
        else: spans.append([a, b, [(t, prob, img)]])
    would = [(round(a, 1), round(b, 1), sorted({p for _, p, _ in items})) for a, b, items in spans]
    fixed = []
    if spans and mode == "report":
        for a, b, probs in would: _log(log, f"    QC {label}: REPORT ONLY {a:.1f}-{b:.1f}s {', '.join(probs)} - would be covered by a still in fix mode")
    elif spans:
        good = [(s["t"], s["img"]) for s in samples if s["state"] == "ok"]
        ins, flt, n = ["-i", str(path)], [], 1
        chain = "[0:v]"
        for a, b, items in spans:
            t, prob, img = items[0]
            still = tmp / f"fix_{a:.0f}.jpg"
            near = min(good, key=lambda g: abs(g[0] - t))[1] if good else None
            if prob == "upside_down":
                media.ff("-i", img, "-vf", "transpose=1,transpose=1", still, timeout=60); how = "turned upright"
            elif near is not None:
                shutil.copy(near, still); how = "nearest clean frame"
            else:
                media.ff("-i", img, "-vf", "boxblur=24:2", still, timeout=60); how = "blurred"
            ins += ["-loop", "1", "-t", f"{d:.2f}", "-i", str(still)]
            W, H = (1080, 1920) if kind == "short" else (1920, 1080)
            flt.append(f"[{n}:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1[s{n}]")
            flt.append(f"{chain}[s{n}]overlay=enable='between(t,{a:.2f},{b:.2f})'[o{n}]")
            chain = f"[o{n}]"; n += 1
            _log(log, f"    QC {label}: {a:.1f}-{b:.1f}s {', '.join(sorted({p for _, p, _ in items}))} -> still ({how})")
        fixed_mp4 = path.with_name(path.stem + "_qc.mp4")
        media.ff(*ins, "-filter_complex", ";".join(flt), "-map", chain, "-map", "0:a?", "-t", f"{d:.2f}", *ENC, "-c:a", "copy", fixed_mp4, timeout=1800)
        fixed_mp4.replace(path)
        fixed = [(t, p) for t, p, _ in bad]
    if incomplete: _log(log, f"    QC {label}: INCOMPLETE - {nun}/{len(samples)} frames unchecked (vision model)")
    rep.write_text(json.dumps({"qcver": QCVER, "mode": mode, "size": path.stat().st_size, "checked": len(samples),
                               "unchecked": nun, "status": "incomplete" if incomplete else "complete",
                               "fixed": fixed, "would_fix": would if mode == "report" else [],
                               "soft": soft, "ignored_single": single,
                               "samples": [{"t": round(s["t"], 1), "state": s["state"], "prob": s["prob"],
                                            "first": s.get("first", ""), "confirm": s.get("confirm", ""), "via": s.get("via", ""),
                                            "rescued": bool(s.get("rescued", False))} for s in samples]}, indent=1), encoding="utf-8")
    return path


def qc_final(out, cfg, work, log=print, every=30.0):
    """Pre-release check of the finished video: a frame every 30 s; a contact sheet with confirmed persistent
    HARD failures marked red and a report (qc report json) beside the video. Report-only by design."""
    from PIL import Image, ImageDraw
    out = Path(out); d = media.dur(out); tmp = Path(work) / "qc_final"; tmp.mkdir(exist_ok=True, parents=True)
    samples, ims = [], []
    for k in range(int(d // every) + 1):
        t = min(d - 1.0, 2.0 + k * every); img = tmp / f"f{k:03}.jpg"
        media.ff("-ss", f"{t:.2f}", "-i", out, "-frames:v", 1, "-vf", "scale=480:-2", img, timeout=120)
        if not img.exists(): continue
        v = _judge_frame(cfg, img)
        samples.append({"t": round(t, 1), **v}); ims.append((t, img))
    def probe(t2, prob):
        if t2 < 0 or t2 > d - 0.5: return None
        img2 = tmp / f"fR{int(t2 * 10)}.jpg"
        media.ff("-ss", f"{t2:.2f}", "-i", out, "-frames:v", 1, "-vf", "scale=480:-2", img2, timeout=120)
        return _judge_frame(cfg, img2) if img2.exists() else None
    keep = _resolve(samples, probe)
    rows = []
    for s, k in zip(samples, keep):
        hard = k
        rows.append({"t": s["t"], "ok": not hard,
                     "problem": s["prob"] if hard else ("none" if s["state"] != "unchecked" else "unchecked"),
                     "raw": s["raw"], "first": s.get("first", ""), "confirm": s.get("confirm", ""), "via": s.get("via", ""),
                     "rescued": bool(s.get("rescued", False)), "unchecked": s["state"] == "unchecked",
                     "soft": s["prob"] if (s["state"] == "bad" and s["prob"] in SOFT) else ""})
    if ims:
        first = Image.open(ims[0][1]); w, h = first.size; cols = 6
        sheet = Image.new("RGB", (w * cols, h * ((len(ims) + cols - 1) // cols)))
        dr = ImageDraw.Draw(sheet)
        for i, ((t, img), r) in enumerate(zip(ims, rows)):
            x, y = (i % cols) * w, (i // cols) * h; sheet.paste(Image.open(img), (x, y))
            tag = "" if r["ok"] else r["problem"]
            if r["soft"] and r["ok"]: tag = r["soft"] + " (soft)"
            dr.rectangle([x, y, x + 170, y + 18], fill="black" if r["ok"] else "red"); dr.text((x + 3, y + 3), f"{int(t // 60)}:{int(t % 60):02d} {tag}", fill="yellow")
        sheet.save(tmp / (out.stem + "_qc.jpg"), quality=85)   # in the work folder: the output folder stays clean for the Publisher
    nun = sum(1 for r in rows if r["unchecked"])
    incomplete = bool(rows) and nun / len(rows) > 0.10
    (tmp / (out.stem + "_qc.json")).write_text(json.dumps(
        {"qcver": QCVER, "status": "incomplete" if incomplete else "complete", "unchecked": nun, "frames": rows}, indent=1), encoding="utf-8")
    nbad = sum(1 for r in rows if not r["ok"])
    _log(log, f"  final QC: {len(rows)} frames checked, {nbad} flagged"
         + (": " + ", ".join(f"{r['t']:.0f}s {r['problem']}" for r in rows if not r["ok"]) if nbad else "")
         + (f"; INCOMPLETE ({nun} unchecked)" if incomplete else ""))
