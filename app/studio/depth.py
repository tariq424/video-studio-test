"""2.5D motion for still images: estimate depth (Depth Anything V2 Small, ONNX, CPU), split the image into layers,
and let Remotion move the layers at different speeds (parallax). Cheap: ~1-3 s per image on CPU, no PyTorch needed.
Model: Apache-2.0, downloaded once into <project>/models/."""
from pathlib import Path
import numpy as np
from . import config

URLS = ["https://huggingface.co/onnx-community/depth-anything-v2-small/resolve/main/onnx/model.onnx",
        "https://huggingface.co/inference4j/depth-anything-v2-small/resolve/main/model.onnx"]
_sess = None

def _model(log):
    global _sess
    if _sess is not None: return _sess
    import onnxruntime as ort, requests
    d = config.ROOT / "models"; d.mkdir(exist_ok=True); p = d / "depth_anything_v2_small.onnx"
    if not (p.exists() and p.stat().st_size > 10_000_000):
        for u in URLS:
            try:
                log("  downloading the depth model (one time, ~100 MB)...")
                r = requests.get(u, timeout=600, stream=True); r.raise_for_status()
                tmp = p.with_suffix(".part")
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(1 << 20): f.write(chunk)
                if tmp.stat().st_size > 10_000_000: tmp.replace(p); break
            except Exception as e: log(f"  depth model download failed from {u.split('/')[3]} ({str(e)[:80]})")
    if not p.exists(): raise RuntimeError("depth model unavailable")
    _sess = ort.InferenceSession(str(p), providers=["CPUExecutionProvider"])
    return _sess

def depth_map(img, log):
    """img: PIL RGB. Returns float32 array (H, W) in [0, 1], 1 = nearest."""
    from PIL import Image
    s = _model(log)
    w, h = img.size; k = 518 / max(w, h)
    nw, nh = [int(np.ceil(x * k / 14) * 14) for x in (w, h)]
    x = np.asarray(img.resize((nw, nh), Image.BICUBIC), dtype=np.float32) / 255.0
    x = (x - [0.485, 0.456, 0.406]) / [0.229, 0.224, 0.225]
    x = x.transpose(2, 0, 1)[None].astype(np.float32)
    out = s.run(None, {s.get_inputs()[0].name: x})[0]
    d = out.reshape(out.shape[-2], out.shape[-1])
    d = (d - d.min()) / max(1e-6, d.max() - d.min())
    return np.asarray(Image.fromarray((d * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC), dtype=np.float32) / 255.0

def _components(m):
    """4-connected labels of a small bool mask (numpy only). Returns (labels, sizes) with sizes[0] unused."""
    H, W = m.shape; lab = np.zeros((H, W), np.int32); sizes = [0]; flat = m.ravel(); lf = lab.ravel()
    for start in np.flatnonzero(flat):
        if lf[start]: continue
        n = len(sizes); lf[start] = n; stack = [start]; c = 0
        while stack:
            i = stack.pop(); c += 1; y, x = divmod(i, W)
            for j, ok in ((i - 1, x > 0), (i + 1, x < W - 1), (i - W, y > 0), (i + W, y < H - 1)):
                if ok and flat[j] and not lf[j]: lf[j] = n; stack.append(j)
        sizes.append(c)
    return lab, sizes

def subject_mask(d):
    """The single dominant near object (an aircraft, a vehicle) as one solid mask, or None when the shot has no such subject
    (landscapes, skylines, crowds: their near region runs off the bottom of the frame or is spread out)."""
    from PIL import Image, ImageFilter
    h, w = d.shape; sw, sh = 135, int(135 * h / w)
    small = np.asarray(Image.fromarray((d * 255).astype(np.uint8)).resize((sw, sh), Image.BILINEAR), dtype=np.float32) / 255
    m = small > np.quantile(small, 0.55)
    mi = Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))  # close thin gaps
    m = np.asarray(mi) > 127
    lab, sizes = _components(m)
    edge = set(lab[-1, :].tolist())                                    # clouds/ground below usually touch the bottom edge
    cand = [(sizes[k], k) for k in range(1, len(sizes)) if k not in edge]
    if not cand: return None
    area, k = max(cand)
    if not (0.005 <= area / m.size <= 0.5) or area < 0.6 * sum(c for c, _ in cand): return None
    s = lab == k
    outside, _ = _components(~s)                                       # fill holes: background not reachable from the border
    border = set(outside[0].tolist()) | set(outside[-1].tolist()) | set(outside[:, 0].tolist()) | set(outside[:, -1].tolist())
    s = s | ~np.isin(outside, list(border - {0}))
    mi = Image.fromarray((s * 255).astype(np.uint8)).resize((w, h), Image.BILINEAR).filter(ImageFilter.MaxFilter(13))
    return np.asarray(mi) > 127

def layers(still, out_prefix, log, size=(1080, 1920)):
    """Crop/resize the still to the frame, then write the parallax layers.
    One dominant subject (aircraft, vehicle): 2 layers, background with the subject painted out + the subject as ONE rigid
    layer, so no part of it (a tail fin) drifts away from the rest. Otherwise 3 layers: full background, mid (nearer half),
    front (nearest ~20%), with feathered edges; the full background stays underneath, so moving layers never reveal holes."""
    from PIL import Image, ImageFilter
    im = Image.open(still).convert("RGB")
    W, H = size; r = max(W / im.width, H / im.height)
    im = im.resize((int(im.width * r + 0.5), int(im.height * r + 0.5)), Image.LANCZOS)
    x0, y0 = (im.width - W) // 2, (im.height - H) // 2; im = im.crop((x0, y0, x0 + W, y0 + H))
    d = depth_map(im, log)
    p0 = Path(f"{out_prefix}_L0.jpg")
    s = None
    try: s = subject_mask(d)
    except Exception as e: log(f"  subject mask failed ({str(e)[:80]}); using 3 depth layers")
    if s is not None:
        hole = Image.fromarray((s * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(21))
        keep = Image.eval(hole, lambda v: 255 - v)
        a = np.asarray(im, dtype=np.float32); k = np.asarray(keep, dtype=np.float32)[..., None] / 255
        bl = lambda x: np.asarray(Image.fromarray(x.clip(0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(40)), dtype=np.float32)
        num = np.stack([bl(a[..., c] * k[..., 0]) for c in range(3)], -1); den = bl(k[..., 0] * 255)[..., None] / 255 + 1e-3
        bg = np.where(np.asarray(hole)[..., None] > 127, num / den, a)
        Image.fromarray(bg.clip(0, 255).astype(np.uint8)).save(p0, "JPEG", quality=92)
        fg = im.copy(); fg.putalpha(Image.fromarray((s * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(3)))
        p1 = Path(f"{out_prefix}_L1.png"); fg.save(p1)
        log("  parallax: 2 layers (one rigid subject)")
        return [p0, p1]
    paths = []
    im.save(p0, "JPEG", quality=92); paths.append(p0)
    for i, q in enumerate((0.55, 0.82), 1):
        thr = float(np.quantile(d, q))
        m = Image.fromarray(((d > thr) * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(6))
        lay = im.copy(); lay.putalpha(m)
        p = Path(f"{out_prefix}_L{i}.png"); lay.save(p); paths.append(p)
    return paths


_rembg = {"session": None}


def cutout_layers(still, out_prefix, log, size=(1080, 1920)):
    """Source Parallax (rung 4): the generated image cut with rembg into a background (subject painted out) and the
    subject as one rigid RGBA layer, for Remotion's 2.5D parallax. Falls back to depth layers when rembg is missing.
    The rembg model (u2net, ~170 MB) is downloaded once into <project>/models/u2net."""
    import os
    from PIL import Image, ImageFilter
    try:
        os.environ.setdefault("U2NET_HOME", str(config.ROOT / "models" / "u2net"))
        from rembg import remove, new_session
    except ImportError:
        log("  parallax: rembg is not installed; using depth layers")
        return layers(still, out_prefix, log, size)
    im = Image.open(still).convert("RGB")
    W, H = size; r = max(W / im.width, H / im.height)
    im = im.resize((int(im.width * r + 0.5), int(im.height * r + 0.5)), Image.LANCZOS)
    x0, y0 = (im.width - W) // 2, (im.height - H) // 2; im = im.crop((x0, y0, x0 + W, y0 + H))
    if _rembg["session"] is None:
        _rembg["session"] = new_session("u2net")
    fg = remove(im, session=_rembg["session"])   # RGBA, alpha = subject
    alpha = np.asarray(fg.split()[-1], dtype=np.float32) / 255
    share = float((alpha > 0.5).mean())
    if share < 0.02 or share > 0.9:   # nothing (or everything) is "subject": a cut-out would look wrong
        log(f"  parallax: rembg found no clear subject ({share:.0%} of the frame); using depth layers")
        return layers(still, out_prefix, log, size)
    hole = Image.fromarray(((alpha > 0.3) * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(21))
    keep = np.asarray(Image.eval(hole, lambda v: 255 - v), dtype=np.float32) / 255
    a = np.asarray(im, dtype=np.float32)
    bl = lambda x: np.asarray(Image.fromarray(x.clip(0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(40)), dtype=np.float32)
    num = np.stack([bl(a[..., c] * keep) for c in range(3)], -1); den = bl(keep * 255)[..., None] / 255 + 1e-3
    bg = np.where(np.asarray(hole)[..., None] > 127, num / den, a)
    p0, p1 = Path(f"{out_prefix}_L0.jpg"), Path(f"{out_prefix}_L1.png")
    Image.fromarray(bg.clip(0, 255).astype(np.uint8)).save(p0, "JPEG", quality=92)
    fg.save(p1)
    log(f"  parallax: rembg cut-out ({share:.0%} of the frame is the subject) over a filled background")
    return [p0, p1]
