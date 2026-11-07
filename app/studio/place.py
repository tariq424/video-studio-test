"""Place colour for your OWN footage (owner, 2026-11-06): read where it was filmed from the video's GPS tag, research the place
and what is around it, and hand the script checked facts to colour the video before, during and after the guest's own story.
("An interview with Nea Dixon in Dockyard, Bermuda, in an artists' studio shop - but that is one attraction: add the rest.")

  where       gps_of (iPhone location tag) + the filming date
  reverse     OpenStreetMap Nominatim: the place's name (Royal Naval Dockyard, Sandys, Bermuda)
  nearby      OpenStreetMap Overpass: named attractions / museums / historic sites / viewpoints within ~1.5 km
  facts       Wikipedia summaries of the place and of the nearby sites: one or two sentences each, with the page as source
Pictures for these colour beats come from the ladder that fires anyway (interview: your own clips at that spot first, then
Commons photos, then AI images; uploads: the visual ladder). Cached in <work>/place.json. Never raises; never hangs (every
request has a time limit)."""
import json, math, re, time
from pathlib import Path

UA = {"User-Agent": "VideoStudio/1.0 (local video tool; place research for the creator's own footage)"}
COLOUR = ("PLACE COLOUR (from the footage's GPS: {where}{when}). Colour the video with the place, using ONLY the location notes "
          "below: open with one line on where we are before the first soundbite / beat; during the video, at most one or two short "
          "bridges about the surroundings at natural pauses (never about the guest's own life, never inside a soundbite); close with "
          "one line on what else to see nearby. Keep it brief: the guest's own story stays the backbone.")


def _get(url, params=None, timeout=20):
    import requests
    r = requests.get(url, params=params, headers=UA, timeout=timeout)
    r.raise_for_status()
    return r


def where(path):
    """-> {"lat", "lon", "date"} from the video's tags, or None (no location tag)."""
    from .interview import gps_of
    g = gps_of(path)
    if not g: return None
    date = ""
    try:
        import subprocess
        from . import media
        o = subprocess.run([media._bin("ffprobe"), "-v", "error", "-show_entries", "format_tags", "-of", "json", str(path)],
                           capture_output=True, text=True, timeout=60).stdout
        t = (json.loads(o or "{}").get("format") or {}).get("tags") or {}
        date = str(t.get("com.apple.quicktime.creationdate") or t.get("creation_time") or "")[:10]
    except Exception:
        pass
    return {"lat": g[0], "lon": g[1], "date": date}


def reverse(lat, lon):
    j = _get("https://nominatim.openstreetmap.org/reverse", {"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 16,
                                                             "addressdetails": 1, "accept-language": "en"}).json()
    a = j.get("address") or {}
    name = j.get("name") or a.get("tourism") or a.get("attraction") or a.get("neighbourhood") or a.get("suburb") or ""
    area = a.get("village") or a.get("town") or a.get("city") or a.get("county") or a.get("state") or ""
    country = a.get("country") or ""
    label = ", ".join(x for x in dict.fromkeys([name, area, country]) if x)
    return {"name": name, "area": area, "country": country, "label": label or j.get("display_name", "")[:120]}


def nearby(lat, lon, radius=1500, limit=12):
    """Named sights around the spot, nearest first: [{"name", "kind", "wikipedia", "m"}]. Wikipedia's geosearch first (articles
    with coordinates: every hit has a source), else OpenStreetMap Overpass (two servers; the main one is often busy)."""
    try:
        j = _get("https://en.wikipedia.org/w/api.php", {"action": "query", "list": "geosearch", "gscoord": f"{lat}|{lon}",
                                                       "gsradius": min(10000, max(500, radius)), "gslimit": 30, "format": "json"}).json()
        hits = [{"name": g["title"], "kind": "", "wikipedia": "en:" + g["title"], "m": round(g.get("dist") or 0)}
                for g in (j.get("query") or {}).get("geosearch") or []]
        if hits: return hits[:limit]
    except Exception:
        pass
    return osm_nearby(lat, lon, radius, limit)


def named_pages(area, country, limit=6):
    """Wikipedia articles ABOUT the place by name (many sights, e.g. a museum in a historic dockyard, carry no coordinates):
    [{"name", "kind", "wikipedia", "m"}]. Only titles that are not the place itself."""
    try:
        j = _get("https://en.wikipedia.org/w/api.php", {"action": "query", "list": "search", "srsearch": f'"{area}" {country}',
                                                       "srlimit": 12, "format": "json"}).json()
    except Exception:
        return []
    out = []
    for h in (j.get("query") or {}).get("search") or []:
        t = h["title"]
        if t.lower().startswith(area.lower()) or re.search(r"^(list of|\d{4})", t, re.I): continue
        out.append({"name": t, "kind": "", "wikipedia": "en:" + t, "m": None})
    return out[:limit]


def osm_nearby(lat, lon, radius=1500, limit=12):
    q = (f'[out:json][timeout:25];(nwr(around:{radius},{lat},{lon})["tourism"~"attraction|museum|viewpoint|gallery|artwork"]["name"];'
         f'nwr(around:{radius},{lat},{lon})["historic"]["name"];nwr(around:{radius},{lat},{lon})["leisure"~"park|marina|beach_resort"]["name"];);out center 80;')
    j = {}
    for server in ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"):
        try:
            j = _get(server, {"data": q}, timeout=40).json(); break
        except Exception:
            continue
    out, seen = [], set()
    for e in j.get("elements") or []:
        t = e.get("tags") or {}; nm = t.get("name:en") or t.get("name")
        la, lo = e.get("lat") or (e.get("center") or {}).get("lat"), e.get("lon") or (e.get("center") or {}).get("lon")
        if not nm or nm.lower() in seen or la is None: continue
        seen.add(nm.lower())
        d = math.hypot((la - lat) * 111320, (lo - lon) * 111320 * math.cos(math.radians(lat)))
        out.append({"name": nm, "kind": t.get("tourism") or t.get("historic") or t.get("leisure") or "",
                    "wikipedia": t.get("wikipedia", ""), "m": round(d)})
    out.sort(key=lambda x: (not x["wikipedia"], x["m"]))
    return out[:limit]


def wiki_fact(title, lang="en", sentences=2):
    """-> {"fact", "source"} from Wikipedia's page summary, or None."""
    if ":" in title and len(title.split(":")[0]) <= 3: lang, title = title.split(":", 1)
    try:
        j = _get(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title.replace(' ', '_')}").json()
    except Exception:
        return None
    ext = re.sub(r"\s+", " ", j.get("extract") or "").strip()
    if j.get("type") == "disambiguation" or len(ext.split()) < 12: return None
    parts = re.split(r"(?<=[.!?])\s+", ext)
    return {"fact": " ".join(parts[:sentences]), "source": (j.get("content_urls") or {}).get("desktop", {}).get("page", "")}


def colour(cfg, video, work, log=print):
    """-> {"context": str, "notes": [{"fact", "source"}], "where": {...}} or None (no GPS / turned off / research failed)."""
    if not cfg.get("place_colour_on", True): return None
    cache = Path(work) / "place.json"
    if cache.is_file():
        try: return json.loads(cache.read_text(encoding="utf-8"))
        except ValueError: pass
    try:
        w = where(video)
        if not w:
            log("  place colour: the footage has no location tag; skipped"); return None
        r = reverse(w["lat"], w["lon"]); time.sleep(1)   # Nominatim: at most one request a second
        sights = nearby(w["lat"], w["lon"], int(cfg.get("place_radius_m", 3000)))
        known = {x["name"].lower() for x in sights}
        sights += [x for x in named_pages(r["area"] or r["name"], r["country"]) if x["name"].lower() not in known]
        notes = []
        for title in [r["name"], r["area"]]:   # the place itself first
            f = wiki_fact(f"{title}, {r['country']}" if title and r["country"] and title != r["country"] else title) or wiki_fact(title) if title else None
            if f and f not in notes: notes.append(f)
        for s in sights:
            if len(notes) >= int(cfg.get("place_max_notes", 6)): break
            f = wiki_fact(s["wikipedia"]) if s["wikipedia"] else None
            if f:
                f["fact"] = (f"Nearby ({s['m']} m away): " if s.get("m") else f"Also at {r['area'] or r['name']}: ") + f["fact"]
                if f not in notes: notes.append(f)
        if not notes:
            log(f"  place colour: {r['label']} found, but no checked facts about it; skipped"); return None
        res = {"where": dict(w, **r), "notes": notes, "sights": sights,
               "context": COLOUR.format(where=r["label"], when=f", filmed {w['date']}" if w.get("date") else "")}
        cache.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
        log(f"  place colour: {r['label']} - {len(notes)} checked note(s), {len(sights)} sight(s) nearby")
        return res
    except Exception as e:
        log(f"  place colour: research failed ({str(e)[:120]}); the video is made without it"); return None


def markdown(res):
    """For uploads that go through the script writer: the same research as notes text (appended to the source notes)."""
    if not res: return ""
    lines = ["# Place colour", res["context"], "## Location notes (checked, with sources)"]
    lines += [f"- {n['fact']} (source: {n['source']})" for n in res["notes"]]
    return "\n".join(lines) + "\n"
