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
EDGE_SELF_AREA = 0.035   # ...or a smaller one cut off at the left/right edge (the holder half in shot beside the guest)
GUEST_LOW = 0.78     # a guest face centred this low is his head poking up at the bottom edge (a shot of the room, not of him)
GUEST_MIN_AREA = 0.008
NEAR = 2              # seconds: a "nobody" second this close to the holder or a ceiling counts as that (missed detections)   # smaller than this is a mirror, a poster, a passer-by far away
CEILING_TOP = 0.65    # the top of the picture this flat = a car ceiling / blank wall, not a shot of anything
DETECTOR = "yunet1"   # bump to re-detect faces in a cached analysis
MODEL = Path(__file__).resolve().parents[2] / "models" / "face_detection_yunet_2023mar.onnx"
GUEST_H = {"short": 0.20, "documentary": 0.26}   # the guest's face height as a share of the output frame


def _cv():
    try:
        import cv2
        import numpy as np
        return cv2, np
    except ImportError:
        return None, None


def is_self(f):
    a = f[2] * f[3]
    return a >= SELF_AREA or (a >= EDGE_SELF_AREA and (f[0] - f[2] / 2 < 0.02 or f[0] + f[2] / 2 > 0.98))


def is_guest(f):
    return not is_self(f) and f[2] * f[3] >= GUEST_MIN_AREA


BACK_CAMERA = {"on": False}   # owner, 2026-10-27: a back-camera interview (Nea Dixon) - the holder is behind the lens, so every
                              # face on screen is the guest; a big close face is the guest's close-up, never the holder


def split(faces):
    """-> (guest faces, holder faces). A close two-shot selfie has two big faces: the biggest is the holder, the other the guest."""
    if BACK_CAMERA["on"]: return [f for f in faces if f[2] * f[3] >= GUEST_MIN_AREA], []
    selfs = [f for f in faces if is_self(f)]
    guests = [f for f in faces if is_guest(f)]
    if not guests and len(selfs) >= 2:
        big = max(selfs, key=lambda f: f[2] * f[3])
        guests = [f for f in selfs if f is not big and f[2] * f[3] < 0.7 * big[2] * big[3]
                  and not (f[0] - f[2] / 2 < 0.02 or f[0] + f[2] / 2 > 0.98)]
        selfs = [f for f in selfs if f not in guests]
    return guests, selfs


_YN = {}


def _faces(cv2, g, im=None):
    """Faces as [cx, cy, w, h] (shares of the frame). YuNet (OpenCV's neural face detector, finds profiles, caps and people
    half out of shot) when its model file is there; else the old Haar cascades, which missed most of the interview."""
    if MODEL.exists():
        try:
            if im is None: im = cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)
            H, W = im.shape[:2]; s = 640 / max(H, W)
            im2 = cv2.resize(im, (int(W * s), int(H * s))) if s < 1 else im
            h2, w2 = im2.shape[:2]
            det = _YN.get((w2, h2))
            if det is None: det = _YN[(w2, h2)] = cv2.FaceDetectorYN.create(str(MODEL), "", (w2, h2), 0.6, 0.3, 50)
            _, fs = det.detect(im2)
            out = []
            for r in ([] if fs is None else fs):
                x, y, w, h = [float(v) for v in r[:4]]
                x, y = max(0.0, x), max(0.0, y); w, h = min(w, w2 - x), min(h, h2 - y)
                out.append([(x + w / 2) / w2, (y + h / 2) / h2, w / w2, h / h2])
            return out
        except Exception:
            pass
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
        want = DETECTOR if MODEL.exists() else "haar"
        if res.get("secs") and (res.get("det") != want or "top" not in res["secs"][0]):   # older analysis: redo faces / flatness
            cv2, np = _cv(); fd = Path(work) / "frames1s"
            if cv2 and fd.is_dir():
                log(f"  framing: re-reading faces in {len(res['secs'])} frames ({want})")
                for sec in res["secs"]:
                    im = cv2.imread(str(fd / f"{sec['t'] + 1:05d}.jpg"))
                    if im is None: continue
                    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
                    sec["faces"] = [[round(v, 3) for v in b] for b in _faces(cv2, g, im)]
                    sec["plain"] = round(_plain(cv2, np, g), 2)
                    sec["top"] = round(_plain(cv2, np, g[:int(g.shape[0] * 0.45)]), 2)
                res["det"] = want
                out.write_text(json.dumps(res), encoding="utf-8")
                log(f"  framing: guest in {sum(1 for x in res['secs'] if kind_of(x) == 'guest')} s, holder only in "
                    f"{sum(1 for x in res['secs'] if kind_of(x) == 'self')} s, ceiling/blank in {sum(1 for x in res['secs'] if kind_of(x) == 'empty')} s")
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
        secs.append({"t": int(f.stem) - 1, "faces": [[round(v, 3) for v in b] for b in _faces(cv2, g, im)], "tilt": round(_tilt(cv2, np, g), 1),
                     "plain": round(_plain(cv2, np, g), 2), "top": round(_plain(cv2, np, g[:int(g.shape[0] * 0.45)]), 2)})
    res = {"secs": secs, "det": DETECTOR if MODEL.exists() else "haar"}
    out.write_text(json.dumps(res), encoding="utf-8")
    log(f"  framing: {len(secs)} s analysed; holder close-ups in {sum(1 for s in secs if kind_of(s) == 'self')} s")
    return res


SHOT_CHECK = """This is one frame from a phone video of a conversation filmed while walking and driving. Reply with JSON only:
{"shot": "scenery|street|building|interior|person|clothing_closeup|hand_or_finger|ceiling|floor|blurry|other",
"top": "top|bottom|left|right", "usable": true|false}.
"top": where the TOP of the real scene is in this picture (the sky, the ceiling, people's heads): "top" if the picture is upright,
"bottom" if it is upside down, "left" or "right" if the phone was held on its side.
"usable": false for a close-up of clothing or a shirt filling the frame, a hand or finger over the lens, a blurry smear, or only
floor / ceiling with nothing else. A room, a street or a person seen upside down or sideways is still usable (it will be turned)."""

VIS_VERSION = 4   # bump to re-run the check (4: turns from upright faces only, 2026-10-25)
TURN = {"bottom": 180, "left": 90, "right": 270}   # degrees clockwise that bring the top back up


def _turn_img(cv2, im, rot):
    return im if not rot else cv2.rotate(im, {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}[rot])


def vision_check(an, work, cfg, log=print, every=2):
    """Every 2nd second where no face was found: the local vision model says what the frame shows and which way is up.
    Owner, 2026-10-25: never swap his footage for something else - an upside-down or sideways stretch is turned upright
    ("rot", degrees clockwise), a finger / shirt close-up / smear is blurred ("bad"). Faces found only after turning the
    frame confirm the turn. Cached in faces.json ("vis")."""
    secs = an.get("secs") or []
    if secs and an.get("vis") in (2, 3):   # v2 guessed "which way is up" with the vision model - wrong on most frames (checked
        cv2, _np = _cv()               # 2026-10-25); keep its blur verdicts, redo the turns from faces only
        if cv2 is not None:
            n = face_turns(an, work, cv2)
            an["vis"] = VIS_VERSION; (Path(work) / "faces.json").write_text(json.dumps(an), encoding="utf-8")
            log(f"  framing: {n} second(s) to turn upright (faces found only after turning)")
        return an
    if not secs or an.get("vis") == VIS_VERSION or not cfg: return an
    fd = Path(work) / "frames1s"
    try:
        from . import footage
        from .llm import parse_json
    except Exception:
        return an
    cv2, np = _cv()
    todo = [x for x in secs if not x.get("faces")]
    log(f"  framing: the vision model checks {len(todo[::every])} faceless frames (which way is up; fingers, shirt close-ups)")
    by = {x["t"]: x for x in secs}
    n_bad = n_rot = 0
    for x in todo[::every]:
        img = fd / f"{x['t'] + 1:05d}.jpg"
        if not img.exists(): continue
        try: j = parse_json(footage._vision(dict(cfg, vet_provider="local"), img, SHOT_CHECK))
        except Exception: continue
        rot = 0   # (the model's "which way is up" was wrong on most frames: turns come from faces only, face_turns below)
        bad = (not bool(j.get("usable", True))) or str(j.get("shot", "")) in ("clothing_closeup", "hand_or_finger", "blurry")
        for t in range(x["t"], x["t"] + every):
            if t in by and not by[t].get("faces"):
                by[t]["bad"] = bool(bad); by[t]["rot"] = rot
        n_bad += bool(bad); n_rot += bool(rot)
    if cv2 is not None: n_rot = face_turns(an, work, cv2)
    an["vis"] = VIS_VERSION
    (Path(work) / "faces.json").write_text(json.dumps(an), encoding="utf-8")
    try:   # free the vision model's memory now (~20 GB with its long context): transcription and renders need it
        import requests
        requests.post(cfg.get("ollama_url", "http://127.0.0.1:11434").rstrip("/") + "/api/generate",
                      json={"model": cfg.get("vet_model", "qwen2.5vl:7b"), "keep_alive": 0}, timeout=30)
    except Exception: pass
    log(f"  framing: {n_bad} frame(s) to blur, {n_rot} to turn upright")
    return an


def _upright(cv2, im):
    """Score of faces that are the right way up in this picture: eyes above the mouth (YuNet's landmarks), weighted by size.
    (A face lying on its side or upside down can still be detected; its landmarks give it away.)"""
    if not MODEL.exists(): return 0.0
    H, W = im.shape[:2]; sc = 640 / max(H, W)
    im2 = cv2.resize(im, (int(W * sc), int(H * sc))) if sc < 1 else im
    h2, w2 = im2.shape[:2]
    det = _YN.get((w2, h2))
    if det is None: det = _YN[(w2, h2)] = cv2.FaceDetectorYN.create(str(MODEL), "", (w2, h2), 0.6, 0.3, 50)
    _, fs = det.detect(im2)
    tot = 0.0
    for r in ([] if fs is None else fs):
        w, h = float(r[2]), float(r[3])
        if w * h / (w2 * h2) < GUEST_MIN_AREA: continue
        eyes_y = (r[5] + r[7]) / 2; mouth_y = (r[11] + r[13]) / 2
        if mouth_y - eyes_y > 0.25 * h and abs(r[4] - r[6]) > 0.2 * w: tot += float(r[14]) * (w * h) ** 0.5
    return tot


def face_turns(an, work, cv2):
    """rot (degrees clockwise) for faceless seconds where a face shows up only after turning the frame (a phone held on
    its side or upside down while filming a person); everything else stays as filmed. -> number of seconds turned."""
    fd = Path(work) / "frames1s"; n = 0
    for x in an.get("secs") or []:
        x["rot"] = 0
        if x.get("faces"): continue
        im = cv2.imread(str(fd / f"{x['t'] + 1:05d}.jpg"))
        if im is None: continue
        hits = {r: _upright(cv2, _turn_img(cv2, im, r)) for r in (0, 90, 180, 270)}
        best = max(hits, key=hits.get)
        if best and hits[best] > 0 and hits[0] == 0: x["rot"] = best; n += 1
    return n


def kind_keep(s):
    """Keep-the-scene mode (owner, 2026-10-25): what to DO with a second of his footage - never what to swap it for.
    turnN = turn N degrees clockwise; blur = finger / shirt / smear or the holder's own big face; guest = frame on him."""
    small, big = split(s["faces"])
    if s.get("rot") and not s.get("faces"): return f"turn{s['rot']}"
    if s.get("bad") and not small: return "blur"
    if small: return "guest"
    if big: return "blur"   # the camera holder's own close-up (his neck, his chin): the scene stays, blurred
    return "none"


def plan_keep(an, t0, t1, min_len=2.0):
    """[(a, b, kind, guest_box, tilt)] like plan_shots, with the keep-the-scene kinds. A turn needs 2+ agreeing checks."""
    by = {s["t"]: s for s in an.get("secs", [])}
    raw = []
    t = math.floor(t0)
    while t < t1:
        s = by.get(t) or {"faces": [], "tilt": 0}
        k = kind_keep(s)
        g = None
        if k == "guest":
            gs, ss = split(s["faces"]); g = max(gs, key=lambda f: f[2] * f[3])
            if ss: g = g + [max(ss, key=lambda f: f[2] * f[3])]   # the holder beside him: framed out where a crop can
        raw.append([max(t0, t), min(t1, t + 1), k, g, s.get("tilt", 0)])
        t += 1
    for i, r in enumerate(raw):   # a lone turn/blur second among plain ones is noise; a "none" between two turns of one kind joins them
        if r[2].startswith("turn"):
            same = sum(1 for q in raw[max(0, i - 3):i + 4] if q[2] == r[2])
            if same < 3: r[2] = "none"
    for i in range(1, len(raw) - 1):
        if raw[i][2] == "none" and raw[i - 1][2] == raw[i + 1][2] and raw[i - 1][2] != "none": raw[i][2] = raw[i - 1][2]
    if not raw: return [(t0, t1, "none", None, 0.0)]
    shots = []
    for r in raw:
        if shots and shots[-1][2] == r[2]: shots[-1][1] = r[1]; shots[-1][5].append(r)
        else: shots.append([r[0], r[1], r[2], None, 0.0, [r]])
    i = 0
    while i < len(shots):
        if shots[i][1] - shots[i][0] < min_len and len(shots) > 1:
            j = i - 1 if i > 0 and (i == len(shots) - 1 or shots[i - 1][1] - shots[i - 1][0] >= shots[i + 1][1] - shots[i + 1][0]) else i + 1
            a, b = sorted((i, j)); keep = shots[j]
            keep[0], keep[1] = shots[a][0], shots[b][1]; keep[5] = shots[a][5] + shots[b][5]
            shots.pop(i if j != i else j); i = max(0, i - 1); continue
        i += 1
    res = []
    for a, b, k, _g, _t, rs in shots:
        gs = [r[3] for r in rs if r[3]]
        g = [sum(x[n] for x in gs) / len(gs) for n in range(4)] if gs and k == "guest" else None
        sb = [r[3][4] for r in rs if r[3] and len(r[3]) > 4]
        if g and sb and holder_out("documentary", g + [max(sb, key=lambda f: f[2] * f[3])]): g = g + [max(sb, key=lambda f: f[2] * f[3])]
        tl = sorted(r[4] for r in rs); tilt = tl[len(tl) // 2] if tl else 0.0
        res.append((a, b, k, g, tilt))
    return res


def kind_of(s):
    small, big = split(s["faces"])
    if s.get("bad") and not small: return "empty"   # the vision check: shirt close-up / finger / sideways / floor
    ceiling = s.get("top", 0) > CEILING_TOP
    if small and min(f[1] for f in small) > GUEST_LOW: return "empty"   # only the top of his head at the bottom: cut away to him elsewhere
    if small and not (ceiling and max(f[1] for f in small) > 0.7): return "guest"   # (the guest's head poking up under a ceiling: no)
    if big: return "self"
    if ceiling or s.get("plain", 0) > 0.6: return "empty"   # a car ceiling / blank wall: covered by a cutaway like the holder's face
    return "none"


def plan_shots(an, t0, t1, min_len=2.0):
    """[(a, b, kind, guest_box or None, tilt)] covering t0-t1 (seconds of the source)."""
    by = {s["t"]: s for s in an.get("secs", [])}
    raw = []
    t = math.floor(t0)
    while t < t1:
        s = by.get(t) or {"faces": [], "tilt": 0}
        k = kind_of(s)
        if k == "none":   # a second with no face found, right beside the holder / a ceiling: the detector missed, not a clean shot
            near = [kind_of(by[u]) for u in range(t - NEAR, t + NEAR + 1) if u != t and u in by]
            if "self" in near: k = "self"
            elif "empty" in near: k = "empty"
        g = None
        if k == "guest":
            gs, ss = split(s["faces"])
            g = max(gs, key=lambda f: f[2] * f[3])
            if ss: g = g + [max(ss, key=lambda f: f[2] * f[3])]   # the holder beside him: frame him out
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
        sb = [r[3][4] for r in rs if r[3] and len(r[3]) > 4]
        if g and sb: g = g + [max(sb, key=lambda f: f[2] * f[3])]
        tl = sorted(r[4] for r in rs); tilt = tl[len(tl) // 2] if tl else 0.0
        res.append((a, b, "guest" if g and k != "self" else k, g, tilt))
    return res


def holder_out(kind, guest, src_w=1920, src_h=1080):
    """Can the guest be framed with the camera holder fully out of the picture? (no holder in the shot = yes)"""
    if not guest or len(guest) < 5: return True
    W, H = (1080, 1920) if kind == "short" else (1920, 1080)
    cx, cy, gw, gh = guest[:4]; holder = guest[4]
    hl, hr = holder[0] - holder[2] / 2, holder[0] + holder[2] / 2
    gl, gr = max(0.0, cx - gw * 0.75), min(1.0, cx + gw * 0.75)
    room = hl if holder[0] > cx else 1.0 - hr
    return room >= gr - gl and room >= (W / H) * src_h / src_w / 2.6


def vf_frame(kind, guest=None, tilt=0.0, flip=True, src_w=1920, src_h=1080, rot=0, blur=False):
    """Filter: mirror removed, turned upright (rot = degrees clockwise), level, framed on the guest (or centred), scaled to
    the output; blur=True softens a stretch that is kept but not worth seeing sharp (owner: blur, never swap)."""
    W, H = (1080, 1920) if kind == "short" else (1920, 1080)
    f = ["hflip"] if flip else []
    if rot:
        f.append({90: "transpose=1", 180: "hflip,vflip", 270: "transpose=2"}[rot])
        if rot in (90, 270): src_w, src_h = src_h, src_w
        if rot in (90, 270) and (src_w < src_h) != (W < H):   # a tall picture in a wide frame: centred over a blurred copy of itself
            tail = ",boxblur=22:2,eq=brightness=-0.08" if blur else ""
            return (",".join(f) + f",split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=30:2,"
                    f"eq=brightness=-0.18[bg];[b]scale={W}:{H}:force_original_aspect_ratio=decrease:flags=lanczos{tail}[fg];"
                    f"[bg][fg]overlay=(W-w)/2:(H-h)/2,fps=30,format=yuv420p,setsar=1")
        guest, tilt = None, 0.0
    if 2.0 <= abs(tilt) <= 15.0:   # level the horizon; zoom so the turned corners stay outside the frame
        r = math.radians(-tilt); z = abs(math.cos(r)) + abs(math.sin(r)) * max(src_w, src_h) / min(src_w, src_h)
        f.append(f"rotate={r:.4f}:fillcolor=black,scale=iw*{z:.3f}:ih*{z:.3f},crop={src_w}:{src_h}")
    ar = W / H
    holder = None
    if guest:
        cx, cy, gw, gh = guest[:4]
        holder = guest[4] if len(guest) > 4 else None
        zoom = min(max(GUEST_H[kind] / max(gh, 0.01), 1.0), 1.8)   # the guest's face at a comfortable size
    else:
        cx, cy, gw, zoom = 0.5, 0.5, 0.0, 1.0
    ch = f"min(ih/{zoom:.3f}\\,iw/{ar:.4f})"; cw = f"min(iw\\,{ch}*{ar:.4f})"   # (a tall clip in a wide frame: fill, never pillarbox)
    x = f"max(0\\,min(iw-{cw}\\,iw*{cx:.3f}-{cw}/2))"
    if holder:   # keep the camera holder out of the frame: the crop stops short of his face, the guest's face still whole
        hl, hr = holder[0] - holder[2] / 2, holder[0] + holder[2] / 2
        gl, gr = max(0.0, cx - gw * 0.75), min(1.0, cx + gw * 0.75)   # the guest's face with a little room
        room = (hl - 0.0) if holder[0] > cx else (1.0 - hr)          # the widest crop that leaves the holder out
        room_needed = (gr - 0.0) if holder[0] > cx else (1.0 - gl)
        if room >= gr - gl:   # possible without cutting the guest: zoom in until the crop fits beside him (at most 2.6x)
            cwf = min(1.0, ar * src_h / src_w / zoom)
            if cwf > room: zoom = min(2.6, ar * src_h / src_w / room); cwf = min(1.0, ar * src_h / src_w / zoom)
            x0 = min(max(cx - cwf / 2, 0.0), 1.0 - cwf)
            if holder[0] > cx: x0 = max(min(x0, hl - cwf), gr - cwf, 0.0)
            else: x0 = min(max(x0, hr), gl, 1.0 - cwf)
            ch = f"ih/{zoom:.3f}"; cw = f"min(iw\\,{ch}*{ar:.4f})"
            x = f"iw*{max(0.0, x0):.4f}"
    y = f"max(0\\,min(ih-{ch}\\,ih*{max(cy - 0.08, 0):.3f}-{ch}/2+{ch}*0.05))"   # a little headroom above the face
    f.append(f"crop={cw}:{ch}:{x}:{y}")
    f.append(f"scale={W}:{H}:force_original_aspect_ratio=decrease:flags=lanczos,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2")
    if blur: f.append("boxblur=22:2,eq=brightness=-0.08")
    f.append("fps=30,format=yuv420p,setsar=1")
    return ",".join(f)


def orient(clip, work, log=print):
    """Rotation that makes a B-roll clip upright: '' (fine), 'transpose=1' (turn clockwise), 'transpose=2' (counter-clockwise).
    Faces found only after a 90-degree turn mean it was filmed sideways. Cached per clip."""
    cache = Path(work) / "orient.json"
    try: known = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError): known = {}
    key = Path(clip).name + "|v3"   # v2: the vision model decides when there are no faces
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
        tmp = Path(work) / "_orient_v.jpg"; votes = []
        for k in range(3):   # three frames must agree, or the clip is left as it is (a wrong turn is worse than none)
            media.ff("-ss", f"{media.dur(clip) * (k + 1) / 4:.2f}", "-i", clip, "-frames:v", 1, "-vf", "scale=640:-2", tmp, timeout=120)
            a = str(footage._vision(cfg, tmp, "Is this photo upright? Look at the floor, ceiling, doors, people and text. Answer with one word: "
                                         "upright, clockwise (it must be turned clockwise to be upright) or counterclockwise.")).lower()
            votes.append("transpose=2" if "counter" in a else "transpose=1" if "clockwise" in a else "")
        return votes[0] if len(set(votes)) == 1 else ""
    except Exception:
        return ""


def cutaway_pool(an, used, min_len=3.0):
    """Stretches of the source where the guest is on screen and the holder isn't (for cutaways), outside the used ranges."""
    runs, cur = [], None
    for s in an.get("secs", []):
        ok = kind_of(s) == "guest" and not split(s["faces"])[1] and not any(a - 1 <= s["t"] <= b + 1 for a, b in used)
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
