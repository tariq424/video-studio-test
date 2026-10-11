"""Internet Archive (archive.org) as a free source: public-domain / CC0 films (B-roll, Prelinger Archives first) and photos.
Uses the public HTTP API (advancedsearch + metadata) with requests - no login, no extra package.

Licence rule: only items whose `licenseurl` is creativecommons.org/publicdomain/... (CC0 = publicdomain/zero, Public Domain
Mark = publicdomain/mark). Anything else - no licence, "no known copyright", NC/ND, CC BY - is skipped. Every search has a 60 s
budget; on any failure it returns nothing and the ladder falls through as before."""
import re, time
import requests

UA = {"User-Agent": "VideoStudio/1.0 (personal YouTube explainer tool; contact via GitHub tariq424)"}
BUDGET = 60
SEARCH = "https://archive.org/advancedsearch.php"


def licence(url):
    """'cc0' | 'pdm' | None from an item's licenseurl."""
    u = (url or "").lower()
    if "creativecommons.org/publicdomain/zero" in u: return "cc0"
    if "creativecommons.org/publicdomain/mark" in u or "creativecommons.org/publicdomain/" in u: return "pdm"
    return None


def _words(q):
    w = [x for x in re.findall(r"[A-Za-z0-9]+", q or "") if len(x) > 2][:6]
    return " AND ".join(w) if w else ""


def _search(q, mediatype, log, rows=12, collection=None, deadline=None):
    terms = _words(q)
    if not terms: return []
    query = f"({terms}) AND mediatype:({mediatype}) AND licenseurl:*publicdomain*"
    if collection: query = f"collection:{collection} AND " + query
    try:
        r = requests.get(SEARCH, headers=UA, timeout=max(5, min(30, (deadline or time.time() + 30) - time.time())), params={
            "q": query, "fl[]": ["identifier", "title", "licenseurl", "creator", "description", "subject"], "rows": rows, "output": "json"})
        if r.status_code != 200: log(f"  Internet Archive search: HTTP {r.status_code}"); return []
        return [d for d in r.json().get("response", {}).get("docs", []) if licence(d.get("licenseurl"))]
    except Exception as e:
        log(f"  Internet Archive search failed ({str(e)[:80]})"); return []


def _meta(ident, deadline):
    left = deadline - time.time()
    if left < 3: return None
    try:
        r = requests.get(f"https://archive.org/metadata/{ident}", headers=UA, timeout=min(20, left))
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def _txt(v):
    if isinstance(v, list): v = " ".join(map(str, v))
    return re.sub(r"<[^>]+>", " ", str(v or "")).strip()


def _secs(v):
    try:
        if ":" in str(v):
            s = 0
            for p in str(v).split(":"): s = s * 60 + float(p)
            return s
        return float(v)
    except Exception:
        return 0.0


def videos(q, orient, log, want_long_side=1920, limit=5):
    """Footage candidates in the footage.py format. Prelinger Archives first, then any public-domain film.
    Archive films are mostly SD; a portrait Short only takes files tall enough to crop to 9:16 without upscaling (>= 1920 px),
    a landscape (long) video files of >= 480 px height (soft but usable as archival B-roll; the vision check still applies)."""
    deadline = time.time() + BUDGET
    docs = _search(q, "movies", log, rows=8, collection="prelinger", deadline=deadline)
    if len(docs) < limit: docs += _search(q, "movies", log, rows=8, deadline=deadline)
    out, seen = [], set()
    for d in docs:
        if len(out) >= limit or time.time() > deadline: break
        ident = d["identifier"]
        if ident in seen: continue
        seen.add(ident); m = _meta(ident, deadline)
        if not m: continue
        lic = licence((m.get("metadata") or {}).get("licenseurl"))
        if not lic: continue   # re-checked on the item itself
        files = m.get("files") or []
        mp4 = []
        for f in files:
            n = f.get("name", "")
            if not n.lower().endswith(".mp4"): continue
            try: w, h = int(float(f.get("width") or 0)), int(float(f.get("height") or 0))
            except ValueError: w, h = 0, 0
            mp4.append((h, w, n, _secs(f.get("length"))))
        if not mp4: continue
        mp4.sort(reverse=True); h, w, name, dur = mp4[0]
        if orient == "portrait" and h < 1920: continue
        if orient != "portrait" and h and h < 480: continue
        thumbs = sorted(f["name"] for f in files if f.get("format") == "Thumbnail" and f.get("name", "").lower().endswith(".jpg"))
        if len(thumbs) >= 4: thumbs = [thumbs[round(i * (len(thumbs) - 1) / 3)] for i in range(4)]
        base = f"https://archive.org/download/{ident}/"
        md = m.get("metadata") or {}
        c = {"id": "ia" + re.sub(r"[^A-Za-z0-9]", "", ident)[:40], "src": "Internet Archive", "orient": orient, "query": q, "dur": dur,
             "w": w or 640, "h": h or 480, "file": base + requests.utils.quote(name), "page": f"https://archive.org/details/{ident}",
             "author": _txt(md.get("creator"))[:60] or "Internet Archive", "license": lic,
             "desc": (_txt(md.get("title")) + ". " + _txt(md.get("subject"))[:120] + ". " + _txt(md.get("description"))[:160]).strip()}
        if len(thumbs) >= 4: c["pics"] = [base + requests.utils.quote(t) for t in thumbs]
        elif dur: c["preview"] = c["file"]   # no thumbnails: frames come from the file itself (cut at 4 points, slower)
        else: continue
        out.append(c)
    if out: log(f"  Internet Archive '{q[:40]}': {len(out)} public-domain film(s)")
    return out


def images(q, log, limit=6):
    """Photo candidates in the photos.py format (licence cc0 / pdm)."""
    deadline = time.time() + BUDGET
    out = []
    for d in _search(q, "image", log, rows=10, deadline=deadline):
        if len(out) >= limit or time.time() > deadline: break
        m = _meta(d["identifier"], deadline)
        if not m: continue
        md = m.get("metadata") or {}
        lic = licence(md.get("licenseurl"))
        if not lic: continue
        best = None
        for f in m.get("files") or []:
            n = f.get("name", "")
            if not re.search(r"\.(jpe?g|png)$", n, re.I) or f.get("format") == "Thumbnail" or "_thumb" in n: continue
            try: w, h = int(float(f.get("width") or 0)), int(float(f.get("height") or 0))
            except ValueError: w, h = 0, 0
            sz = int(float(f.get("size") or 0))
            if best is None or (w, sz) > (best[0], best[2]): best = (w, h, sz, n)
        if not best: continue
        ident = d["identifier"]
        out.append({"src": "Internet Archive", "id": "ia_" + re.sub(r"[^A-Za-z0-9]", "", ident)[:30],
                    "url": f"https://archive.org/download/{ident}/" + requests.utils.quote(best[3]), "title": _txt(md.get("title"))[:120],
                    "creator": _txt(md.get("creator"))[:80], "license": lic, "license_version": "", "landing": f"https://archive.org/details/{ident}",
                    "w": best[0], "h": best[1], "tags": (_txt(md.get("subject")) + " " + _txt(md.get("description")))[:300]})
    if out: log(f"  Internet Archive photos '{q[:40]}': {len(out)} public-domain candidate(s)")
    return out
