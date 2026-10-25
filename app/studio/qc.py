"""Frame quality check for every finished video (owner, 2026-10-24): smudges, fingers, sideways / upside-down picture, blur,
clothing or giant-face close-ups, black frames. Uses this PC's local vision model (Ollama); without it the check is skipped.
  qc_part   a frame every few seconds; a failing stretch is covered, under the same sound, by a still (turned upright when it
            was upside down, else the nearest clean frame, else blurred)
  qc_final  a frame every 10-30 s of the finished video -> <video>_qc.jpg (failures red) + <video>_qc.json"""
import json
import shutil
from pathlib import Path

from . import media

ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]


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


def _qc_frame(cfg, img):
    from . import footage
    from .llm import parse_json
    try: j = parse_json(footage._vision(dict(cfg, vet_provider="local"), img, QC))
    except Exception: return True, "unchecked"
    prob = str(j.get("problem") or "none").strip().lower()
    return (bool(j.get("ok", True)) and prob in ("none", "")), prob


def qc_part(path, cfg, log=print, every=4.0, label="", kind="documentary"):
    """Owner, 2026-10-24: check every piece before it is stitched in. A frame every `every` seconds goes to the local vision
    model; a failing stretch (+/- 2 s) is replaced, under the same sound, by a still: the frame turned right side up when it
    was upside down, else the nearest clean frame of the same piece, else that frame blurred. Cached: <piece>.qc.json."""
    path = Path(path); rep = path.with_suffix(".qc.json")
    if rep.exists():
        try:
            if json.loads(rep.read_text(encoding="utf-8")).get("size") == path.stat().st_size: return path
        except Exception: pass
    d = media.dur(path)
    if d < 1.5: return path
    tmp = path.with_suffix(""); tmp.mkdir(exist_ok=True)
    times = [min(d - 0.3, 1.0 + k * every) for k in range(int(max(0.0, d - 1.0) // every) + 1)]
    res = []
    for k, t in enumerate(times):
        img = tmp / f"qc{k:03}.jpg"
        media.ff("-ss", f"{t:.2f}", "-i", path, "-frames:v", 1, "-vf", "scale=768:-2", img, timeout=120)
        ok, prob = _qc_frame(cfg, img) if img.exists() else (True, "unchecked")
        res.append((t, ok, prob, img))
    bad = [(t, prob, img) for t, ok, prob, img in res if not ok]
    if bad:
        good = [(t, img) for t, ok, prob, img in res if ok]
        spans = []
        for t, prob, img in bad:
            a, b = max(0.0, t - every / 2 - 0.5), min(d, t + every / 2 + 0.5)
            if spans and a <= spans[-1][1]: spans[-1][1] = max(spans[-1][1], b); spans[-1][2].append((t, prob, img))
            else: spans.append([a, b, [(t, prob, img)]])
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
        fixed = path.with_name(path.stem + "_qc.mp4")
        media.ff(*ins, "-filter_complex", ";".join(flt), "-map", chain, "-map", "0:a?", "-t", f"{d:.2f}", *ENC, "-c:a", "copy", fixed, timeout=1800)
        fixed.replace(path)
    rep.write_text(json.dumps({"size": path.stat().st_size, "checked": len(res), "fixed": [(t, p) for t, p, _ in bad]}), encoding="utf-8")
    return path


def qc_final(out, cfg, work, log=print, every=30.0):
    """Pre-release check of the finished video: a frame every 30 s; a contact sheet with failures marked red and a report
    (qc_report.json) beside the video."""
    from PIL import Image, ImageDraw
    out = Path(out); d = media.dur(out); tmp = Path(work) / "qc_final"; tmp.mkdir(exist_ok=True)
    rows, ims = [], []
    for k in range(int(d // every) + 1):
        t = min(d - 1.0, 2.0 + k * every); img = tmp / f"f{k:03}.jpg"
        media.ff("-ss", f"{t:.2f}", "-i", out, "-frames:v", 1, "-vf", "scale=480:-2", img, timeout=120)
        if not img.exists(): continue
        ok, prob = _qc_frame(cfg, img); rows.append({"t": round(t, 1), "ok": ok, "problem": prob}); ims.append((t, ok, prob, Image.open(img)))
    if ims:
        w, h = ims[0][3].size; cols = 6; sheet = Image.new("RGB", (w * cols, h * ((len(ims) + cols - 1) // cols)))
        dr = ImageDraw.Draw(sheet)
        for i, (t, ok, prob, im) in enumerate(ims):
            x, y = (i % cols) * w, (i // cols) * h; sheet.paste(im, (x, y))
            dr.rectangle([x, y, x + 150, y + 18], fill="black" if ok else "red"); dr.text((x + 3, y + 3), f"{int(t // 60)}:{int(t % 60):02d} {'' if ok else prob}", fill="yellow")
        sheet.save(tmp / (out.stem + "_qc.jpg"), quality=85)   # in the work folder: the output folder stays clean for the Publisher
    (tmp / (out.stem + "_qc.json")).write_text(json.dumps(rows, indent=1), encoding="utf-8")
    nbad = sum(1 for r in rows if not r["ok"])
    _log(log, f"  final QC: {len(rows)} frames checked, {nbad} flagged" + (": " + ", ".join(f"{r['t']:.0f}s {r['problem']}" for r in rows if not r['ok']) if nbad else ""))


