"""Designed 9:16 thumbnail for a Short (1080x1920): the key visual of the strongest beat, a bold hook headline, the channel
name if configured. A separate file (output/thumbnail_9_16.png), never baked into the video; uploaded by hand in YouTube Studio.
Options (short/thumb.json): beat, size S|M|L, color yellow|red|white|cyan, text (lines split by "/" or newlines), image (own file)."""
import json, re, textwrap
from pathlib import Path
from . import media

COLORS = {"yellow": (255, 200, 61), "red": (255, 70, 70), "white": (255, 255, 255), "cyan": (80, 220, 255)}
SIZES = {"S": 112, "M": 148, "L": 186}
PICTURE = ("image", "video", "layers")

def _beats(job):
    tf = Path(job) / "short" / "public" / "teaser.json"
    return json.loads(tf.read_text(encoding="utf-8"))["beats"] if tf.exists() else []

def options(job):
    f = Path(job) / "short" / "thumb.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}

def _rank(bg):
    if bg["type"] == "image": return 0                     # a real photo of the subject
    if bg["type"] == "video": return 1 if "GENERATED" not in str(bg.get("tag", "")) else 2
    return 3                                                  # AI still / parallax

def best_beat(job):
    """The hook beat if it has a picture, else the beat with the strongest picture (real photo > footage > AI)."""
    beats = _beats(job)
    pics = [(b["id"], min(_rank(g) for g in b["bgs"] if g["type"] in PICTURE)) for b in beats if any(g["type"] in PICTURE for g in b["bgs"])]
    if not pics: return None
    if beats and pics[0][0] == beats[0]["id"]: return pics[0][0]
    return min(pics, key=lambda x: x[1])[0]

def _frame(job, bid, out):
    """A full-size picture from what that beat shows in the Short."""
    pub = Path(job) / "short" / "public"
    b = next((b for b in _beats(job) if b["id"] == bid), None)
    if not b: return None
    for g in sorted([g for g in b["bgs"] if g["type"] in PICTURE], key=_rank):
        try:
            if g["type"] == "image": return pub / g["src"]
            if g["type"] == "layers": return pub / g["layers"][0]
            src = pub / g["src"]; media.ff("-ss", f"{media.dur(src) / 2:.2f}", "-i", src, "-frames:v", 1, out); return out
        except Exception: continue
    return None

def _lines(plan, o):
    if o.get("text"):
        ls = [x.strip() for x in re.split(r"[/\n]", o["text"]) if x.strip()]; return [x.upper() for x in ls], len(ls) - 1
    for v in (plan["sections"][0].get("visuals") or []):
        g = v.get("chart") or {}
        if g.get("kind") == "hook" and g.get("lines"): return [str(x).upper() for x in g["lines"]][:4], int(g.get("accent", len(g["lines"]) - 1))
    ls = textwrap.wrap(plan["title"].upper(), 14)[:4]; return ls, len(ls) - 1

def make(job, plan, cfg, log, opts=None):
    from PIL import Image, ImageDraw, ImageFilter
    from .photos import _font
    job = Path(job); sd = job / "short"; out = job / "output" / "thumbnail_9_16.png"; out.parent.mkdir(exist_ok=True)
    o = options(job); o.update({k: v for k, v in (opts or {}).items() if v is not None})
    W, H = 1080, 1920
    src = Path(o["image"]) if o.get("image") and Path(o["image"]).exists() else None
    if not src:
        o["beat"] = o.get("beat") or best_beat(job)
        src = _frame(job, o["beat"], sd / "_thumb_frame.jpg") if o.get("beat") else None
    if src:
        im = Image.open(src).convert("RGB"); r = max(W / im.width, H / im.height)
        im = im.resize((int(im.width * r + 0.5), int(im.height * r + 0.5)), Image.LANCZOS)
        x0, y0 = (im.width - W) // 2, (im.height - H) // 2; im = im.crop((x0, y0, x0 + W, y0 + H))
    else:
        im = Image.new("RGB", (W, H), (14, 20, 32))
    # darken top and bottom so the text reads on any picture
    grad = Image.new("L", (1, H))
    for y in range(H): grad.putpixel((0, y), int(255 * max(0.25 * max(0, 1 - y / (H * 0.18)), min(0.88, max(0, (y - H * 0.38) / (H * 0.42)) * 0.88))))
    im = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), im, grad.resize((W, H)))
    dr = ImageDraw.Draw(im)
    acc = COLORS.get(o.get("color", "yellow"), COLORS["yellow"])
    lines, ai = _lines(plan, o)
    size = SIZES.get(o.get("size", "M"), 148)
    f = _font(size, True)
    while size > 60 and max(dr.textlength(l, font=f) for l in lines) > W - 100: size -= 6; f = _font(size, True)
    lh = int(size * 1.08); y = int(H * 0.80) - lh * len(lines)
    for i, l in enumerate(lines):
        w = dr.textlength(l, font=f); x = (W - w) / 2
        col = acc if i == ai else (255, 255, 255)
        if i == ai and o.get("color", "yellow") != "white":   # the accent line on a solid bar, news-style
            dr.rectangle([x - 26, y + int(size * 0.06), x + w + 26, y + lh - int(size * 0.02)], fill=acc); col = (17, 17, 17)
        dr.text((x, y), l, font=f, fill=col, stroke_width=0 if col == (17, 17, 17) else max(4, size // 22), stroke_fill=(0, 0, 0))
        y += lh
    ch = (cfg.get("channel_name") or "").strip()
    if ch:
        fc = _font(46, True); w = dr.textlength(ch.upper(), font=fc)
        dr.rounded_rectangle([(W - w) / 2 - 28, 140, (W + w) / 2 + 28, 222], radius=16, fill=(0, 0, 0))
        dr.text(((W - w) / 2, 154), ch.upper(), font=fc, fill=(255, 255, 255))
    im.save(out)
    o.update(path=str(out), approved=False)
    (sd / "thumb.json").write_text(json.dumps(o, indent=1), encoding="utf-8")
    log(f"Thumbnail ready: {out}")
    return out
