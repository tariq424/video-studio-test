"""Real, openly licensed PHOTOS of a story's specific subject (a named airline's aircraft, a car model, a building) for shots
stock-video libraries can't fill. Stock sites are built for generic scenes; these APIs are built for specific subjects:
  1. Openverse (api.openverse.org, no key; aggregates Flickr, Wikimedia and others, returns licence data)
  2. Wikimedia Commons (no key) - also used straight away when Openverse is rate-limiting (HTTP 429) or down
(Flickr's own API is not used: free keys are non-commercial only, and Openverse already indexes Flickr.)
Errors never stop the job: every search/download/check failure just means fewer photos, and with none the shot falls back to
the 3D reconstruction. Photos narrower than MIN_W pixels are rejected (they would look soft in a 1080p render).
Only licences that allow commercial use AND changes (we crop and move the photo): CC0, Public Domain Mark, CC BY, CC BY-SA
(preferred in that order). Every photo used gets a credit line ("Photo: title by creator, CC BY-SA 2.0, link") in the YouTube
description. Each photo is checked by the vision model: it must show the subject (brand evidence) and no other brand."""
import io, json, re, time
from pathlib import Path
import requests
from . import media
from .llm import parse_json

UA = {"User-Agent": "VideoStudio/1.1 (https://github.com/tariq424/video-studio-test; personal explainer tool) python-requests",
      "Api-User-Agent": "VideoStudio/1.1 (https://github.com/tariq424/video-studio-test)"}   # Wikimedia's User-Agent policy: tool name + contact URL
OK_LIC = {"cc0": 0, "pdm": 0, "by": 1, "by-sa": 2}
LIC_NAME = {"cc0": "CC0", "pdm": "Public domain", "by": "CC BY", "by-sa": "CC BY-SA"}
MIN_W = 900   # px; below this a photo looks soft in a 1080p frame

def _slug(s): return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:60]

def _openverse(q, log, n=20):
    """-> (results, problem). problem is "" for a normal answer (possibly no results), "throttled" for HTTP 429,
    or "error" for anything else (down, timeout, bad reply)."""
    try:
        r = requests.get("https://api.openverse.org/v1/images/", headers=UA, timeout=30,
                         params={"q": q, "license": "cc0,pdm,by,by-sa", "page_size": n, "mature": "false"})
        if r.status_code == 429:
            log("  Openverse is rate-limiting us (HTTP 429, about 200 searches/day without a key); going straight to Wikimedia Commons")
            return [], "throttled"
        if r.status_code != 200: log(f"  Openverse unavailable (HTTP {r.status_code}); going to Wikimedia Commons"); return [], "error"
        out = []
        for x in r.json().get("results", []):
            lic = (x.get("license") or "").lower()
            if lic not in OK_LIC or not x.get("url"): continue
            out.append({"src": "Openverse/" + (x.get("source") or x.get("provider") or "?"), "id": "ov_" + x["id"][:12], "url": x["url"],
                        "title": x.get("title") or "", "creator": x.get("creator") or "", "license": lic,
                        "license_version": x.get("license_version") or "", "landing": x.get("foreign_landing_url") or "",
                        "w": x.get("width") or 0, "h": x.get("height") or 0,
                        "tags": " ".join(t.get("name", "") for t in (x.get("tags") or [])[:40])})
        return out, ""
    except Exception as e:
        log(f"  Openverse search failed ({str(e)[:80]}); going to Wikimedia Commons"); return [], "error"

def _commons(q, log, n=15):
    try:
        r = requests.get("https://commons.wikimedia.org/w/api.php", headers=UA, timeout=30, params={
            "action": "query", "format": "json", "generator": "search", "gsrsearch": f"{q} filetype:bitmap", "gsrnamespace": 6,
            "gsrlimit": n, "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 1920})
        if r.status_code != 200:
            log(f"  Wikimedia Commons unavailable (HTTP {r.status_code})" + (" - rate-limited" if r.status_code == 429 else "")); return []
        out = []
        for pg in sorted(((r.json().get("query") or {}).get("pages") or {}).values(), key=lambda p: p.get("index", 99)):
            ii = (pg.get("imageinfo") or [{}])[0]; em = ii.get("extmetadata") or {}
            if ii.get("mime") not in ("image/jpeg", "image/png"): continue
            short = (em.get("LicenseShortName", {}).get("value") or "").lower()
            lic = "cc0" if "cc0" in short else "pdm" if "public domain" in short else "by-sa" if "by-sa" in short else "by" if "cc by" in short or "cc-by" in short else ""
            if not lic or "-nc" in short or "-nd" in short: continue
            ver = (re.search(r"(\d\.\d)", short) or [None, ""])[1]
            creator = re.sub(r"<[^>]+>", "", em.get("Artist", {}).get("value") or "").strip()[:80]
            out.append({"src": "Wikimedia Commons", "id": "wc_" + str(pg.get("pageid")), "url": ii.get("thumburl") or ii.get("url"),
                        "title": pg.get("title", "").replace("File:", ""), "creator": creator, "license": lic, "license_version": ver,
                        "landing": ii.get("descriptionurl") or "", "w": ii.get("width") or 0, "h": ii.get("height") or 0,
                        "tags": re.sub(r"<[^>]+>", " ", em.get("ImageDescription", {}).get("value") or "")[:300]})
        return out
    except Exception as e:
        log(f"  Commons search failed ({str(e)[:80]})"); return []

PHOTO = """This is a photo found by searching for: {subject}.
1. "brands": every brand, airline name/logo or make/badge you can read or clearly recognise. Empty list if none.
2. "same_subject": does it clearly show {subject} itself (the same airline livery / the same make and model / the same building),
   as the main subject? "yes", "no" or "unclear". Judge only WHAT it is, not what it is doing: parked, taxiing, landing or
   flying are all fine.
3. "watermark": is there a large watermark, caption, frame or text overlaid on the photo - or is it a screen capture of other media
   (a YouTube / social page or player, a video thumbnail, a TV broadcast with a channel logo, a film/TV still)? true or false.
5. "phase": what the aircraft or vehicle is doing: "air" (flying), "landing" (on approach or touching down), "takeoff",
   "taxi" (moving on the ground), "ground" (parked or standing), or "other".
4. "looks_ok": a clear, sharp, real photo of the real thing (not a drawing, scale model, simulator, screenshot, factory part or
   collage)? true or false.
Reply with JSON only: {{"brands": [], "same_subject": "yes|no|unclear", "watermark": false, "looks_ok": true, "phase": "air|landing|takeoff|taxi|ground|other", "seen": "10-20 words"}}"""

NOT_REAL = re.compile(r"\b(simulator|simulation|model|replica|toy|diecast|die-cast|scale|lego|render(ing)?|mock-?up|cgi|production line|"
                      r"factory|assembly|cutaway|drawing|illustration|painting|game|museum)\b", re.I)
TITLE_PHASE = [("landing", r"\b(lands?|landing|final approach|on approach|touch(es|ing)? ?down|arriv\w*)\b"),
               ("takeoff", r"\b(take ?-?off|taking off|departing|departure|rotat\w*|lined up)\b"),
               ("taxi", r"\b(taxi\w*|pushback)\b"), ("ground", r"\b(parked|at the gate|on stand|apron|ramp|stairs)\b"),
               ("air", r"\b(in flight|inflight|flying|airborne|overhead|cruis\w*|climb\w*)\b")]

def _check(cfg, p, path, subject, log):
    from .footage import _vision, _brands, _norm_brand
    if NOT_REAL.search(p["title"]): return False, "not a photo of the real thing (title)"
    key = _norm_brand(subject.get("brand", ""))
    from PIL import Image
    small = Path(path).with_name(Path(path).stem + "_vet.jpg")   # big originals (3-4k px) make the local vision model fail
    if not small.exists():
        im = Image.open(path).convert("RGB"); im.thumbnail((1280, 1280)); im.save(small, "JPEG", quality=88)
    try: j = parse_json(_vision(cfg, small, PHOTO.format(subject=subject["name"])))
    except Exception as e: return False, f"vision check unavailable ({str(e)[:50]})"
    yes = lambda k, d: str(j.get(k, d)).strip().lower() in ("true", "yes", "1")
    if yes("watermark", False): return False, "watermark/text overlay"
    if not yes("looks_ok", True): return False, "not a clear real photo"
    brands = _brands(j)
    other = [b for b in brands if not (key and (key in _norm_brand(b) or _norm_brand(b) in key))]
    if other: return False, f"shows another brand ({', '.join(other)[:50]})"
    same = str(j.get("same_subject", "")).strip().lower()
    if same == "no": return False, "not the subject"
    meta = _norm_brand(p["title"] + " " + p["tags"])
    # brand in the title/tags or visible; or, for things with no visible brand (military aircraft...), the model designation
    # from the subject's name (e.g. "F-35") in the photo's title/tags
    models = [_norm_brand(t) for t in re.findall(r"[A-Za-z]*-?\d+[A-Za-z0-9-]*", subject["name"]) if re.search(r"\d", t)]
    visible = bool(key) and any(key in _norm_brand(b) or _norm_brand(b) in key for b in brands)
    military = bool(re.search(r"\b(f-?\d+|fighter|military|air force)\b", subject["name"], re.I))
    if key and not military and not visible:
        # the viewer must SEE it is the subject (livery/badge readable), not just the photo's title saying so -
        # a front view of a white 737 could be any airline
        return False, f"{subject.get('brand')} not visible in the photo"
    evidence = (not key) or visible or key in meta or any(m and m in meta for m in models)
    if not evidence: return False, f"no sign of {subject.get('brand')}"
    if not key and same != "yes": return False, "subject not confirmed"
    p["phase"] = str(j.get("phase") or "").strip().lower()
    for ph, rx in TITLE_PHASE:   # the photographer's title ("Lands at Dhaka", "Taxiing") beats the small vision model's guess
        if re.search(rx, p["title"], re.I): p["phase"] = ph; break
    return True, ""

_last_dl = [0.0]

def _download(url):
    """Polite image download: at least 1.5 s between requests (image hosts like Wikimedia's upload server throttle bursts),
    and on HTTP 429/503 wait (Retry-After, else 5 s then 15 s) and try again, twice. -> (bytes, "") or (None, reason)."""
    why = ""
    for wait in (0, 5, 15):
        if wait: time.sleep(wait)
        gap = time.time() - _last_dl[0]
        need = 3.0 if "wikimedia.org" in url else 1.5   # Wikimedia's upload servers throttle bursts hardest
        if gap < need: time.sleep(need - gap)
        _last_dl[0] = time.time()
        try: r = requests.get(url, headers=UA, timeout=60)
        except Exception as e: why = str(e)[:60]; continue
        if r.status_code == 200 and r.content: return r.content, ""
        why = f"HTTP {r.status_code}"
        if r.status_code not in (429, 503): return None, why
        try: ra = float(r.headers.get("Retry-After", "0"))
        except ValueError: ra = 0
        if 0 < ra <= 60: time.sleep(ra)
    return None, why + " after 3 tries"

def find(cfg, subject, out_dir, log, want=4, keys=None):
    """-> list of checked photos for the subject (cached per subject in out_dir/<slug>.json): dicts with "path" + licence data."""
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    cf = out_dir / f"{_slug(subject['name'])}.json"
    if cf.exists(): return json.loads(cf.read_text(encoding="utf-8"))
    from .footage import ensure_vet_model
    q = subject["name"]
    cands, problem = _openverse(q, log)
    if len(cands) < 6: cands += _commons(q, log)
    if len(cands) < 6:   # Internet Archive: public-domain / CC0 only
        from . import archive
        cands += archive.images(q, log)
    if len(cands) < 4 and subject.get("brand") and subject["brand"].lower() != q.lower():
        if not problem:
            more, problem = _openverse(subject["brand"] + " " + (subject.get("kind") or ""), log); cands += more
        cands += _commons(subject["brand"], log)
    seen, uniq = set(), []
    for c in cands:   # the same photo often appears twice (Flickr + its Commons copy, or two sizes): one per title / URL
        t = re.sub(r"[^a-z0-9]", "", re.sub(r"\.(jpe?g|png)$", "", c["title"].lower()))
        k1, k2 = c["url"].split("?")[0], t
        if k1 in seen or (k2 and k2 in seen): continue
        seen.update({k1, k2}); uniq.append(c)
    # metadata that names the brand first, then freest licence, then larger
    key = re.sub(r"[^a-z0-9]", "", (subject.get("brand") or "").lower())
    uniq.sort(key=lambda c: (0 if key and key in re.sub(r"[^a-z0-9]", "", (c["title"] + c["tags"]).lower()) else 1,
                             OK_LIC.get(c["license"], 9), -(c["w"] or 0)))
    log(f"  photos of '{q}': {len(uniq)} openly licensed candidate(s)" + (" (Commons only; Openverse " + problem + ")" if problem else ""))
    got = []
    if uniq:
        try: ensure_vet_model(cfg, log)
        except Exception as e:
            log(f"  can't check photos ({str(e)[:100]}); using none - the shot falls back to a reconstruction"); return []
    from PIL import Image
    rej = []   # every rejected photo, with its reason and a preview where one could be had (the debugger thumbnails them)
    def reject(c, why, path=None):
        rej.append({"id": c["id"], "title": c["title"][:80], "why": why, "path": str(path) if path and Path(path).exists() else "",
                    "creator": c.get("creator", ""), "src": c.get("src", "")})
    def small_preview(c, data=None):
        pv = out_dir / f"{c['id']}_small.jpg"
        if pv.exists(): return pv
        try:
            if data is None: data, _ = _download(c["url"])
            if data: Image.open(io.BytesIO(data)).convert("RGB").save(pv, "JPEG", quality=85); return pv
        except Exception: pass
        return None
    for c in uniq[:want * 2 + 4]:
        if len(got) >= want: break
        if c["w"] and c["w"] < MIN_W:
            log(f"  photo skipped: {c['title'][:50]} (only {c['w']} px wide)"); reject(c, f"only {c['w']} px wide", small_preview(c)); continue
        path = out_dir / f"{c['id']}.jpg"
        if not path.exists():   # downloaded files are kept, so a re-run never fetches them again
            data, why = _download(c["url"])
            if data is None: log(f"  photo download failed ({why}): {c['title'][:50]}"); reject(c, f"download failed ({why})"); continue
            try: im = Image.open(io.BytesIO(data)).convert("RGB")
            except Exception: log(f"  photo download failed (not an image): {c['title'][:50]}"); reject(c, "not an image"); continue
            if im.width < MIN_W:
                log(f"  photo skipped: {c['title'][:50]} (only {im.width} px wide)"); reject(c, f"only {im.width} px wide", small_preview(c, data)); continue
            im.save(path, "JPEG", quality=92)
        ok, why = _check(cfg, c, path, subject, log)
        if not ok: log(f"  photo skipped: {c['title'][:50]} ({why})"); reject(c, why, path); continue
        c["path"] = str(path); got.append(c)
        log(f"  photo OK: {c['title'][:60]} - {c['creator'][:40]}, {credit_license(c)} ({c['src']}; {c.get('phase') or '?'})")
    if uniq:
        from .footage import unload_vet_model
        unload_vet_model(cfg)   # free the GPU for WanGP
    if got or not problem: cf.write_text(json.dumps(got, indent=1), encoding="utf-8")   # a throttled empty result is retried next time
    if rej: (out_dir / f"{_slug(subject['name'])}.rejected.json").write_text(json.dumps(rej, indent=1), encoding="utf-8")
    return got

def rejected(subject, out_dir):
    """Photos of the subject that were rejected (reason + preview path), from the last search."""
    f = Path(out_dir) / f"{_slug(subject['name'])}.rejected.json"
    try: return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []
    except Exception: return []

def credit_license(c):
    n = LIC_NAME.get(c["license"], c["license"].upper())
    return n + (f" {c['license_version']}" if c.get("license_version") and c["license"] in ("by", "by-sa") else "")

def credit(c):
    """One YouTube-description credit line (title, author, licence, source link) as CC licences require."""
    t = c["title"] or "Photo"
    by = f" by {c['creator']}" if c.get("creator") else ""
    return f"Photo: \"{t[:80]}\"{by}, {credit_license(c)}" + (f" - {c['landing']}" if c.get("landing") else "")

def short_credit(c):
    """On-screen credit (Shorts and long videos): 'Photo: creator / CC BY-SA 2.0'."""
    return f"Photo: {(c.get('creator') or 'unknown')[:40]} / {credit_license(c)}"

def _font(size, bold=False):
    from PIL import ImageFont
    names = (("arialbd.ttf", "C:/Windows/Fonts/arialbd.ttf", "DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf") if bold else ()) + \
            ("arial.ttf", "C:/Windows/Fonts/arial.ttf", "segoeui.ttf", "DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    for f in names:
        try: return ImageFont.truetype(f, size)
        except Exception: continue
    return ImageFont.load_default()

def headline_clip(text, kicker, out, secs, size=(1920, 1080)):
    """Last-resort visual for a subject-locked long-video shot: a dark headline card with a slow drift (drawn here, never by an
    image model, so it can't show the wrong subject)."""
    if media.ok(out): return out
    from PIL import Image, ImageDraw
    W, H = size; out = Path(out); out.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", (W, H)); d = ImageDraw.Draw(im)
    for y in range(H):   # dark blue -> near black gradient
        t = y / H; d.line([(0, y), (W, y)], fill=(int(16 - 9 * t), int(26 - 16 * t), int(46 - 28 * t)))
    for x in range(-H, W, 70): d.line([(x, H), (x + H, 0)], fill=(30, 40, 62), width=2)
    words, lines, cur = text.split(), [], ""
    f = _font(int(H * 0.075), True)
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=f) > W * 0.8 and cur: lines.append(cur); cur = w
        else: cur = t
    if cur: lines.append(cur)
    lines = lines[:3]; lh = int(H * 0.095); y = H // 2 - len(lines) * lh // 2
    if kicker:
        kf = _font(int(H * 0.033), True); kw = d.textlength(kicker.upper(), font=kf)
        d.rounded_rectangle([(W - kw) / 2 - 24, y - lh - 10, (W + kw) / 2 + 24, y - lh + int(H * 0.05)], radius=30, fill=(255, 200, 61))
        d.text(((W - kw) / 2, y - lh - 2), kicker.upper(), font=kf, fill=(17, 17, 17))
    for ln in lines:
        d.text(((W - d.textlength(ln, font=f)) / 2, y), ln, font=f, fill=(255, 255, 255)); y += lh
    png = out.with_suffix(".png"); im.save(png)
    return kenburns(png, out, secs, size, 2)

def _credit_png(text, out, scale=1.0):
    """The on-screen credit as a small semi-transparent label (PNG), drawn with PIL so ffmpeg needs no font setup."""
    from PIL import Image, ImageDraw, ImageFont
    size = int(26 * scale); font = None
    for f in ("arial.ttf", "C:/Windows/Fonts/arial.ttf", "segoeui.ttf", "DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try: font = ImageFont.truetype(f, size); break
        except Exception: continue
    font = font or ImageFont.load_default()
    d0 = ImageDraw.Draw(Image.new("RGBA", (10, 10))); x0, y0, x1, y1 = d0.textbbox((0, 0), text, font=font)
    pad = int(12 * scale); im = Image.new("RGBA", (x1 - x0 + 2 * pad, y1 - y0 + 2 * pad), (10, 12, 18, 150))
    ImageDraw.Draw(im).text((pad - x0, pad - y0), text, font=font, fill=(255, 255, 255, 220))
    im.save(out); return out

def kenburns(img, out, secs, size, k=0, credit=""):
    """Real photo as a video clip: slow push-in or pan (the photo itself is not altered), with the photo credit shown on screen
    for the whole clip (top-right corner). Used for long-video shots."""
    if media.ok(out): return out
    W, H = size; fr = int(secs * 30)
    zs = ["min(zoom+0.0006,1.15)", "1.12", "min(zoom+0.0005,1.12)"][k % 3]
    xs = ["iw/2-(iw/zoom/2)", f"(iw-iw/zoom)*on/{fr}", "iw/2-(iw/zoom/2)"][k % 3]
    kb = (f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,crop={W * 2}:{H * 2},"
          f"zoompan=z='{zs}':x='{xs}':y='ih/2-(ih/zoom/2)':d={fr}:s={W}x{H}:fps=30")
    if credit:
        lab = _credit_png(("FILE  ·  " + credit)[:120], Path(out).with_suffix(".credit.png"), W / 1920)
        m = int(28 * W / 1920)
        media.ff("-loop", 1, "-i", img, "-loop", 1, "-i", lab, "-t", f"{secs:.2f}", "-filter_complex",
                 f"[0:v]{kb}[v];[v][1:v]overlay=W-w-{m}:{m}:shortest=1,format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
                 "-t", f"{secs:.2f}", out, timeout=600)
    else:
        media.ff("-loop", 1, "-i", img, "-t", f"{secs:.2f}", "-vf", kb + ",format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", out, timeout=600)
    return out
