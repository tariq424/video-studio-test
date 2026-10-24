"""Shot framing for the interview edit (owner, 2026-10-24): the guest is the subject, the camera holder is not.

  analyze      once per video, 1 frame a second: faces (OpenCV frontal + profile), and the camera's tilt (dominant straight lines).
               The camera holder filmed himself on the front camera, so HIS face is the big, close one ("self", >= ~6% of the
               frame); the guest's face is smaller and farther away.
  plan_shots   a soundbite's picture, second by second, merged into shots of >= 2 s:
                 guest visible            -> crop/zoom onto the guest, the holder cut out
                 only the holder's face   -> CUTAWAY: the soundbite's sound continues over other footage (the guest elsewhere in
                                             the video, the B-roll clips, a context photo)
                 nobody (scenery, road)   -> as filmed
  tilt         a shot whose straight lines lean 2-15 degrees is turned level (and zoomed a little so no corners show)
  orient       a B-roll clip filmed sideways (portrait phone held flat) is turned upright: faces found only after a 90-degree turn
All of it ffmpeg + OpenCV on the CPU."""
import json
import math
from pathlib import Path

from . import media

SELF_AREA = 0.06      # a face this big (share of the frame) is the camera holder, filming himself
GUEST_H = {"short": 0.20, "documentary": 0.26}   # the guest's face height as a share of the output frame


def _cv():
    try:
        import cv2
        import numpy as np
        return cv2, np
    except ImportError:
        return None, None


def _faces(cv2, g):
    W, H = g.shape[1], g.shape[0]
    out = []
    for name in ("haarcascade_frontalface_default.xml", "haarcascade_profileface.xml"):
        c = cv2.CascadeClassifier(cv2.data.haarcascades + name)
        for (x, y, w, h) in c.detectMultiScale(g, 1.12, 6, minSize=(28, 28)):
            box = [(x + w / 2) / W, (y + h / 2) / H, w / W, h / H]
            if not any(abs(box[0] - b[0]) < b[2] / 2 and abs(box[1] - b[1]) < b[3] / 2 for b in out): out.append(box)
    return out


def _tilt(cv2, np, g):
    """Median lean of long, nearly level / upright lines in degrees (positive = turn clockwise to level), or 0."""
    e = cv2.Canny(g, 60, 160)
    lines = cv2.HoughLinesP(e, 1, np.pi / 360, 80, minLineLength=g.shape[1] // 6, maxLineGap=8)
    if lines is None: return 0.0
    devs = []
    for x1, y1, x2, y2 in lines[:, 0]:
        a = math.degrees(math.atan2(y2 - y1, x2 - x1))
        a = (a + 180) % 180
        if a < 20 or a > 160: devs.append(a if a < 20 else a - 180)                    # near level
        elif 70 < a < 110: devs.append(a - 90)                                           # near upright
    if len(devs) < 4: return 0.0
    devs.sort(); return float(devs[len(devs) // 2])


def _plain(cv2, np, g):
    """Share of the picture with almost no detail (a car ceiling, a blank wall): 16-px blocks whose texture is flat."""
    lap = np.abs(cv2.Laplacian(g, cv2.CV_32F))
    h, w = lap.shape; bs = 16
    blocks = lap[:h - h % bs, :w - w % bs].reshape(h // bs, bs, w // bs, bs).mean(axis=(1, 3))
    return float((blocks < 4.0).mean())


def analyze(src, work, flip=True, log=print):
    """-> {"secs": [{"t", "faces": [[cx, cy, w, h]], "tilt"}]} cached in work/faces.json."""
    out = Path(work) / "faces.json"
    if out.exists():
        res = json.loads(out.read_text(encoding="utf-8"))
        if res.get("secs") and "plain" not in res["secs"][0]:   # older analysis: add the plain-picture measure
            cv2, np = _cv(); fd = Path(work) / "frames1s"
            if cv2 and fd.is_dir():
                for sec in res["secs"]:
                    im = cv2.imread(str(fd / f"{sec['t'] + 1:05d}.jpg"))
                    sec["plain"] = round(_plain(cv2, np, cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)), 2) if im is not None else 0
                out.write_text(json.dumps(res), encoding="utf-8")
        return res
    cv2, np = _cv()
    if not cv2: return {"secs": []}
    fd = Path(work) / "frames1s"; fd.mkdir(parents=True, exist_ok=True)
    if not any(fd.glob("*.jpg")):
        log("Interview: one frame a second for framing (faces, tilt)")
        media.ff("-i", src, "-vf", ("hflip," if flip else "") + "fps=1,scale=640:-2", "-q:v", 4, fd / "%05d.jpg", timeout=3600)
    secs = []
    for f in sorted(fd.glob("*.jpg")):
        im = cv2.imread(str(f))
        if im is None: continue
        g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
        secs.append({"t": int(f.stem) - 1, "faces": [[round(v, 3) for v in b] for b in _faces(cv2, g)], "tilt": round(_tilt(cv2, np, g), 1),
                     "plain": round(_plain(cv2, np, g), 2)})
    res = {"secs": secs}
    out.write_text(json.dumps(res), encoding="utf-8")
    log(f"  framing: {len(secs)} s analysed; holder close-ups in {sum(1 for s in secs if kind_of(s) == 'self')} s")
    return res


def kind_of(s):
    big = [f for f in s["faces"] if f[2] * f[3] >= SELF_AREA]
    small = [f for f in s["faces"] if f[2] * f[3] < SELF_AREA]
    if small: return "guest"
    if big: return "self"
    if s.get("plain", 0) > 0.6: return "empty"   # a car ceiling / blank wall: covered by a cutaway like the holder's face
    return "none"


def plan_shots(an, t0, t1, min_len=2.0):
    """[(a, b, kind, guest_box or None, tilt)] covering t0-t1 (seconds of the source)."""
    by = {s["t"]: s for s in an.get("secs", [])}
    raw = []
    t = math.floor(t0)
    while t < t1:
        s = by.get(t) or {"faces": [], "tilt": 0}
        k = kind_of(s)
        g = None
        if k == "guest":
            gs = [f for f in s["faces"] if f[2] * f[3] < SELF_AREA]
            g = max(gs, key=lambda f: f[2] * f[3])
        raw.append([max(t0, t), min(t1, t + 1), k, g, s.get("tilt", 0)])
        t += 1
    if not raw: return [(t0, t1, "none", None, 0.0)]
    shots = []
    for r in raw:   # merge equal neighbours
        if shots and shots[-1][2] == r[2]:
            p = shots[-1]; p[1] = r[1]; p[5].append(r)
        else: shots.append([r[0], r[1], r[2], None, 0.0, [r]])
    i = 0
    while i < len(shots):   # a shot under min_len joins its longer neighbour
        if shots[i][1] - shots[i][0] < min_len and len(shots) > 1:
            j = i - 1 if i > 0 and (i == len(shots) - 1 or shots[i - 1][1] - shots[i - 1][0] >= shots[i + 1][1] - shots[i + 1][0]) else i + 1
            a, b = sorted((i, j)); keep = shots[j]
            keep[0], keep[1] = shots[a][0], shots[b][1]; keep[5] = shots[a][5] + shots[b][5]
            shots.pop(i if j != i else j); i = max(0, i - 1); continue
        i += 1
    res = []
    for a, b, k, _g, _t, rs in shots:
        gs = [r[3] for r in rs if r[3]]
        g = [sum(x[n] for x in gs) / len(gs) for n in range(4)] if gs else None
        tl = sorted(r[4] for r in rs); tilt = tl[len(tl) // 2] if tl else 0.0
        res.append((a, b, "guest" if g and k != "self" else k, g, tilt))
    return res


def vf_frame(kind, guest=None, tilt=0.0, flip=True, src_w=1920, src_h=1080):
    """Filter: mirror removed, level, framed on the guest (or centred), scaled to the output."""
    W, H = (1080, 1920) if kind == "short" else (1920, 1080)
    f = ["hflip"] if flip else []
    if 2.0 <= abs(tilt) <= 15.0:   # level the horizon; zoom so the turned corners stay outside the frame
        r = math.radians(-tilt); z = abs(math.cos(r)) + abs(math.sin(r)) * max(src_w, src_h) / min(src_w, src_h)
        f.append(f"rotate={r:.4f}:fillcolor=black,scale=iw*{z:.3f}:ih*{z:.3f},crop={src_w}:{src_h}")
    ar = W / H
    if guest:
        cx, cy, gw, gh = guest
        zoom = min(max(GUEST_H[kind] / max(gh, 0.01), 1.0), 1.8)   # the guest's face at a comfortable size
    else:
        cx, cy, zoom = 0.5, 0.5, 1.0
    ch = f"ih/{zoom:.3f}"; cw = f"min(iw\\,{ch}*{ar:.4f})"
    x = f"max(0\\,min(iw-{cw}\\,iw*{cx:.3f}-{cw}/2))"
    y = f"max(0\\,min(ih-{ch}\\,ih*{max(cy - 0.08, 0):.3f}-{ch}/2+{ch}*0.05))"   # a little headroom above the face
    f.append(f"crop={cw}:{ch}:{x}:{y}")
    f.append(f"scale={W}:{H}:force_original_aspect_ratio=decrease:flags=lanczos,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2")
    f.append("fps=30,format=yuv420p,setsar=1")
    return ",".join(f)


def orient(clip, work, log=print):
    """Rotation that makes a B-roll clip upright: '' (fine), 'transpose=1' (turn clockwise), 'transpose=2' (counter-clockwise).
    Faces found only after a 90-degree turn mean it was filmed sideways. Cached per clip."""
    cache = Path(work) / "orient.json"
    try: known = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError): known = {}
    key = Path(clip).name
    if key in known: return known[key]
    cv2, np = _cv(); best = ""; score = {}
    if cv2:
        tmp = Path(work) / "_orient.jpg"; score = {"": 0, "transpose=1": 0, "transpose=2": 0}
        try:
            d = media.dur(clip)
            for k in range(3):
                media.ff("-ss", f"{d * (k + 1) / 4:.2f}", "-i", clip, "-frames:v", 1, "-vf", "scale=640:-2", tmp, timeout=120)
                im = cv2.imread(str(tmp)); g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
                score[""] += len(_faces(cv2, g))
                score["transpose=1"] += len(_faces(cv2, cv2.rotate(g, cv2.ROTATE_90_CLOCKWISE)))
                score["transpose=2"] += len(_faces(cv2, cv2.rotate(g, cv2.ROTATE_90_COUNTERCLOCKWISE)))
            best = max(score, key=score.get) if max(score.values()) > score[""] else ""
        except Exception:
            best = ""
    if cv2 and not best and score and max(score.values()) == 0:   # no faces to go by: ask the local vision model once
        best = _orient_vision(clip, work)
    known[key] = best
    cache.write_text(json.dumps(known, indent=1), encoding="utf-8")
    if best: log(f"    {key}: filmed sideways, turned upright ({best})")
    return best


def _orient_vision(clip, work):
    try:
        from . import config, footage
        cfg = dict(config.load())
        if cfg.get("vet_provider", "local") in ("off", "", None): cfg["vet_provider"] = "local"
        tmp = Path(work) / "_orient_v.jpg"
        media.ff("-ss", f"{media.dur(clip) / 2:.2f}", "-i", clip, "-frames:v", 1, "-vf", "scale=640:-2", tmp, timeout=120)
        a = str(footage._vision(cfg, tmp, "Is this photo upright? Look at the floor, ceiling, doors, people and text. Answer with one word: "
                                     "upright, clockwise (it must be turned clockwise to be upright) or counterclockwise.")).lower()
        return "transpose=1" if "counter" not in a and "clockwise" in a else "transpose=2" if "counter" in a else ""
    except Exception:
        return ""


def cutaway_pool(an, used, min_len=3.0):
    """Stretches of the source where the guest is on screen and the holder isn't (for cutaways), outside the used ranges."""
    runs, cur = [], None
    for s in an.get("secs", []):
        ok = kind_of(s) == "guest" and not any(a - 1 <= s["t"] <= b + 1 for a, b in used)
        if ok:
            if cur and s["t"] == cur[1]: cur[1] = s["t"] + 1
            else:
                if cur and cur[1] - cur[0] >= min_len: runs.append(cur)
                cur = [s["t"], s["t"] + 1]
        else:
            if cur and cur[1] - cur[0] >= min_len: runs.append(cur)
            cur = None
    if cur and cur[1] - cur[0] >= min_len: runs.append(cur)
    return runs
