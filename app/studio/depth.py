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

def layers(still, out_prefix, log, size=(1080, 1920)):
    """Crop/resize the still to the frame, then write 3 PNG layers: full background, mid (nearer half), front (nearest ~20%),
    with feathered edges. The full background stays underneath, so moving layers never reveal holes."""
    from PIL import Image, ImageFilter
    im = Image.open(still).convert("RGB")
    W, H = size; r = max(W / im.width, H / im.height)
    im = im.resize((int(im.width * r + 0.5), int(im.height * r + 0.5)), Image.LANCZOS)
    x0, y0 = (im.width - W) // 2, (im.height - H) // 2; im = im.crop((x0, y0, x0 + W, y0 + H))
    d = depth_map(im, log)
    paths = []
    p0 = Path(f"{out_prefix}_L0.jpg"); im.save(p0, "JPEG", quality=92); paths.append(p0)
    for i, q in enumerate((0.55, 0.82), 1):
        thr = float(np.quantile(d, q))
        m = Image.fromarray(((d > thr) * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(6))
        lay = im.copy(); lay.putalpha(m)
        p = Path(f"{out_prefix}_L{i}.png"); lay.save(p); paths.append(p)
    return paths
