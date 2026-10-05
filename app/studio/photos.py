"""Real, openly licensed PHOTOS of a story's specific subject (a named airline's aircraft, a car model, a building) for shots
stock-video libraries can't fill. Stock sites are built for generic scenes; these APIs are built for specific subjects:
  1. Openverse (api.openverse.org, no key; aggregates Flickr, Wikimedia and others, returns licence data)
  2. Flickr (only if FLICKR_API_KEY is in the project .env), CC/public-domain licences only
  3. Wikimedia Commons (no key)
Only licences that allow commercial use AND changes (we crop and move the photo): CC0, Public Domain Mark, CC BY, CC BY-SA
(preferred in that order). Every photo used gets a credit line ("Photo: title by creator, CC BY-SA 2.0, link") in the YouTube
description. Each photo is checked by the vision model: it must show the subject (brand evidence) and no other brand."""
import io, json, re
from pathlib import Path
import requests
from . import media
from .llm import parse_json

UA = {"User-Agent": "VideoStudio/1.0 (personal YouTube explainer tool; contact via GitHub tariq424)"}
OK_LIC = {"cc0": 0, "pdm": 0, "by": 1, "by-sa": 2}
LIC_NAME = {"cc0": "CC0", "pdm": "Public domain", "by": "CC BY", "by-sa": "CC BY-SA"}
FLICKR_LIC = {"9": ("cc0", ""), "10": ("pdm", ""), "7": ("pdm", ""), "8": ("pdm", ""), "4": ("by", "2.0"), "5": ("by-sa", "2.0")}

def _slug(s): return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:60]

def _openverse(q, log, n=20):
    try:
        r = requests.get("https://api.openverse.org/v1/images/", headers=UA, timeout=30,
                         params={"q": q, "license": "cc0,pdm,by,by-sa", "page_size": n, "mature": "false"})
        if r.status_code != 200: log(f"  Openverse: HTTP {r.status_code}"); return []
        out = []
        for x in r.json().get("results", []):
            lic = (x.get("license") or "").lower()
            if lic not in OK_LIC or not x.get("url"): continue
            out.append({"src": "Openverse/" + (x.get("source") or x.get("provider") or "?"), "id": "ov_" + x["id"][:12], "url": x["url"],
                        "title": x.get("title") or "", "creator": x.get("creator") or "", "license": lic,
                        "license_version": x.get("license_version") or "", "landing": x.get("foreign_landing_url") or "",
                        "w": x.get("width") or 0, "h": x.get("height") or 0,
                        "tags": " ".join(t.get("name", "") for t in (x.get("tags") or [])[:40])})
        return out
    except Exception as e:
        log(f"  Openverse search failed ({str(e)[:80]})"); return []

def _flickr(q, key, log, n=20):
    if not key: return []
    try:
        r = requests.get("https://api.flickr.com/services/rest/", headers=UA, timeout=30, params={
            "method": "flickr.photos.search", "api_key": key, "text": q, "license": ",".join(FLICKR_LIC), "content_type": 1,
            "media": "photos", "sort": "relevance", "per_page": n, "extras": "license,owner_name,url_l,url_o,tags,o_dims",
            "format": "json", "nojsoncallback": 1})
        out = []
        for x in (r.json().get("photos") or {}).get("photo", []):
            url = x.get("url_l") or x.get("url_o")
            lic = FLICKR_LIC.get(str(x.get("license")))
            if not url or not lic: continue
            out.append({"src": "Flickr", "id": "fl_" + str(x["id"]), "url": url, "title": x.get("title") or "", "creator": x.get("ownername") or "",
                        "license": lic[0], "license_version": lic[1], "landing": f"https://www.flickr.com/photos/{x.get('owner')}/{x['id']}",
                        "w": int(x.get("width_l") or 0), "h": int(x.get("height_l") or 0), "tags": x.get("tags") or ""})
        return out
    except Exception as e:
        log(f"  Flickr search failed ({str(e)[:80]})"); return []

def _commons(q, log, n=15):
    try:
        r = requests.get("https://commons.wikimedia.org/w/api.php", headers=UA, timeout=30, params={
            "action": "query", "format": "json", "generator": "search", "gsrsearch": f"{q} filetype:bitmap", "gsrnamespace": 6,
            "gsrlimit": n, "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 1600})
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
   as the main subject? "yes", "no" or "unclear".
3. "watermark": is there a large watermark, caption, frame or text overlaid on the photo? true or false.
4. "looks_ok": a clear, sharp, real photo (not a drawing, model, screenshot or collage)? true or false.
Reply with JSON only: {{"brands": [], "same_subject": "yes|no|unclear", "watermark": false, "looks_ok": true, "seen": "10-20 words"}}"""

def _check(cfg, p, path, subject, log):
    from .footage import _vision, _brands, _norm_brand
    key = _norm_brand(subject.get("brand", ""))
    try: j = parse_json(_vision(cfg, path, PHOTO.format(subject=subject["name"])))
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
    evidence = (not key) or key in meta or any(key in _norm_brand(b) for b in brands)
    if not evidence: return False, f"no sign of {subject.get('brand')}"
    if not key and same != "yes": return False, "subject not confirmed"
    return True, ""

def find(cfg, subject, out_dir, log, want=4, keys=None):
    """-> list of checked photos for the subject (cached per subject in out_dir/<slug>.json): dicts with "path" + licence data."""
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    cf = out_dir / f"{_slug(subject['name'])}.json"
    if cf.exists(): return json.loads(cf.read_text(encoding="utf-8"))
    from .footage import _keys, ensure_vet_model
    keys = keys if keys is not None else _keys()
    q = subject["name"]
    cands = _openverse(q, log)
    if len(cands) < 6: cands += _flickr(q, keys.get("FLICKR_API_KEY", ""), log)
    if len(cands) < 6: cands += _commons(q, log)
    if len(cands) < 4 and subject.get("brand") and subject["brand"].lower() != q.lower():
        cands += _openverse(subject["brand"] + " " + (subject.get("kind") or ""), log) + _commons(subject["brand"], log)
    seen, uniq = set(), []
    for c in cands:
        k = (c["url"].split("?")[0], c["title"].lower())
        if k in seen: continue
        seen.add(k); uniq.append(c)
    # metadata that names the brand first, then freest licence, then larger
    key = re.sub(r"[^a-z0-9]", "", (subject.get("brand") or "").lower())
    uniq.sort(key=lambda c: (0 if key and key in re.sub(r"[^a-z0-9]", "", (c["title"] + c["tags"]).lower()) else 1,
                             OK_LIC.get(c["license"], 9), -(c["w"] or 0)))
    log(f"  photos of '{q}': {len(uniq)} openly licensed candidate(s) (Openverse/Flickr/Commons)")
    got = []
    if uniq: ensure_vet_model(cfg, log)
    from PIL import Image
    for c in uniq[:want * 2 + 4]:
        if len(got) >= want: break
        if c["w"] and c["w"] < 900: continue
        path = out_dir / f"{c['id']}.jpg"
        try:
            if not path.exists():
                r = requests.get(c["url"], headers=UA, timeout=60); r.raise_for_status()
                im = Image.open(io.BytesIO(r.content)).convert("RGB")
                if im.width < 900: continue
                im.save(path, "JPEG", quality=92)
        except Exception as e: log(f"  photo {c['id']} download failed ({str(e)[:60]})"); continue
        ok, why = _check(cfg, c, path, subject, log)
        if not ok: log(f"  photo skipped: {c['title'][:50]} ({why})"); continue
        c["path"] = str(path); got.append(c)
        log(f"  photo OK: {c['title'][:60]} - {c['creator'][:40]}, {credit_license(c)} ({c['src']})")
    if uniq:
        from .footage import unload_vet_model
        unload_vet_model(cfg)   # free the GPU for WanGP
    cf.write_text(json.dumps(got, indent=1), encoding="utf-8")
    return got

def credit_license(c):
    n = LIC_NAME.get(c["license"], c["license"].upper())
    return n + (f" {c['license_version']}" if c.get("license_version") and c["license"] in ("by", "by-sa") else "")

def credit(c):
    """One YouTube-description credit line (title, author, licence, source link) as CC licences require."""
    t = c["title"] or "Photo"
    by = f" by {c['creator']}" if c.get("creator") else ""
    return f"Photo: \"{t[:80]}\"{by}, {credit_license(c)}" + (f" - {c['landing']}" if c.get("landing") else "")

def short_credit(c):
    """Short on-screen credit: 'Photo: creator / CC BY-SA 2.0 (via Openverse/flickr)'."""
    return f"Photo: {(c.get('creator') or 'unknown')[:40]} / {credit_license(c)}"

def kenburns(img, out, secs, size, k=0):
    """Real photo as a video clip: slow push-in or pan (no changes to the photo itself). Used for long-video shots."""
    if media.ok(out): return out
    W, H = size; fr = int(secs * 30)
    zs = ["min(zoom+0.0006,1.15)", "1.12", "min(zoom+0.0005,1.12)"][k % 3]
    xs = ["iw/2-(iw/zoom/2)", f"(iw-iw/zoom)*on/{fr}", "iw/2-(iw/zoom/2)"][k % 3]
    vf = (f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,crop={W * 2}:{H * 2},"
          f"zoompan=z='{zs}':x='{xs}':y='ih/2-(ih/zoom/2)':d={fr}:s={W}x{H}:fps=30,format=yuv420p")
    media.ff("-loop", 1, "-i", img, "-t", f"{secs:.2f}", "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", out, timeout=600)
    return out
