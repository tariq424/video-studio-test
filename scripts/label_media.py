"""Label a folder of your own trip media (owner, 2026-10-24: "label the Bermuda videos so we can find them").

Phase "index" (light, safe beside a render): reads each file's metadata (time taken, GPS, length, camera) with ffprobe for
videos and EXIF for photos (HEIC needs pillow-heif), groups files taken within ~150 m of each other into places, names each
place from OpenStreetMap (Nominatim, 1 request a second), and writes <out>/index.csv + <out>/places.json.
Originals are never changed. Copying into <out> with descriptive names, and the speech / picture pass (Whisper + the local
vision model) for files without GPS, are later phases.

Run: python scripts/label_media.py F:\\bermuda F:\\bermuda\\labeled index
"""
import csv
import json
import math
import re
import subprocess
import sys
import time
from pathlib import Path

import requests

VIDEO = {".mov", ".mp4", ".m4v"}
PHOTO = {".heic", ".jpg", ".jpeg", ".png"}
UA = {"User-Agent": "VideoStudio-label/1.0 (personal trip footage index)"}


def log(m): print(time.strftime("%H:%M:%S"), m, flush=True)


def video_meta(p):
    j = json.loads(subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(p)],
                                  capture_output=True, text=True, timeout=60).stdout or "{}")
    fm = j.get("format", {}); t = fm.get("tags", {})
    m = re.match(r"([+-]\d+\.\d+)([+-]\d+\.\d+)", t.get("com.apple.quicktime.location.ISO6709", ""))
    return {"dur": round(float(fm.get("duration") or 0), 1), "time": t.get("com.apple.quicktime.creationdate") or t.get("creation_time") or "",
            "lat": float(m[1]) if m else None, "lon": float(m[2]) if m else None, "camera": t.get("com.apple.quicktime.model", "")}


def photo_meta(p):
    from PIL import Image
    if p.suffix.lower() == ".heic":
        try:
            import pillow_heif; pillow_heif.register_heif_opener()
        except ImportError:
            return {"dur": 0, "time": "", "lat": None, "lon": None, "camera": "", "note": "HEIC: pillow-heif not installed"}
    im = Image.open(p); ex = im.getexif()
    gps = ex.get_ifd(0x8825) if ex else {}
    def deg(v, ref):
        try:
            d = float(v[0]) + float(v[1]) / 60 + float(v[2]) / 3600
            return -d if ref in ("S", "W") else d
        except Exception: return None
    lat = deg(gps.get(2), gps.get(1)) if gps else None
    lon = deg(gps.get(4), gps.get(3)) if gps else None
    sub = ex.get_ifd(0x8769) if ex else {}
    t = str(sub.get(0x9003) or ex.get(0x0132) or "")
    t = re.sub(r"^(\d{4}):(\d\d):(\d\d) ", r"\1-\2-\3T", t)
    return {"dur": 0, "time": t, "lat": lat, "lon": lon, "camera": str(ex.get(0x0110) or "")}


def dist(a, b):
    return 6371000 * math.hypot(math.radians(a[0] - b[0]), math.radians(a[1] - b[1]) * math.cos(math.radians(a[0])))


def place_name(lat, lon, cache):
    k = f"{lat:.4f},{lon:.4f}"
    if k in cache: return cache[k]
    time.sleep(1.1)   # Nominatim's usage policy: at most 1 request a second
    try:
        j = requests.get("https://nominatim.openstreetmap.org/reverse", headers=UA, timeout=30,
                         params={"lat": lat, "lon": lon, "format": "json", "zoom": 18, "namedetails": 1}).json()
        a = j.get("address", {})
        name = (j.get("name") or a.get("amenity") or a.get("tourism") or a.get("building") or a.get("road") or "").strip()
        area = (a.get("suburb") or a.get("village") or a.get("town") or a.get("city") or a.get("county") or "").strip()
        cache[k] = {"name": name, "area": area, "display": j.get("display_name", "")[:160]}
    except Exception as e:
        cache[k] = {"name": "", "area": "", "display": f"(lookup failed: {str(e)[:60]})"}
    return cache[k]


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40]


def index(src, out):
    out.mkdir(parents=True, exist_ok=True)
    mf = out / "meta.json"
    meta = json.loads(mf.read_text(encoding="utf-8")) if mf.exists() else {}
    files = [p for p in sorted(src.rglob("*")) if p.is_file() and p.suffix.lower() in VIDEO | PHOTO
             and not any(x in p.parts for x in ("_work", out.name))]
    log(f"{len(files)} media files; {len(meta)} already read")
    for n, p in enumerate(files):
        rel = str(p.relative_to(src))
        if rel in meta: continue
        try: meta[rel] = (video_meta if p.suffix.lower() in VIDEO else photo_meta)(p) | {"size": p.stat().st_size}
        except Exception as e: meta[rel] = {"err": str(e)[:100], "size": p.stat().st_size}
        if n % 50 == 0: mf.write_text(json.dumps(meta, indent=0), encoding="utf-8"); log(f"  read {n}/{len(files)}")
    mf.write_text(json.dumps(meta, indent=0), encoding="utf-8")
    # places: files within ~150 m of a place's first file
    places = []
    for rel, m in sorted(meta.items(), key=lambda x: x[1].get("time") or ""):
        if m.get("lat") is None: continue
        for pl in places:
            if dist(pl["at"], (m["lat"], m["lon"])) < 150: pl["files"].append(rel); break
        else: places.append({"at": (m["lat"], m["lon"]), "files": [rel]})
    pf = out / "places.json"
    cache = json.loads(pf.read_text(encoding="utf-8")).get("lookup", {}) if pf.exists() else {}
    log(f"{len(places)} places; naming them from OpenStreetMap")
    for pl in places:
        pl["name"] = place_name(pl["at"][0], pl["at"][1], cache)
    pf.write_text(json.dumps({"lookup": cache, "places": places}, indent=1, ensure_ascii=False), encoding="utf-8")
    where = {f: pl for pl in places for f in pl["files"]}
    with open(out / "index.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["file", "taken", "seconds", "place", "area", "lat", "lon", "camera", "suggested_name", "note"])
        for rel, m in sorted(meta.items(), key=lambda x: (x[1].get("time") or "9999", x[0])):
            pl = where.get(rel); nm = (pl or {}).get("name") or {}
            label = slug(nm.get("name") or nm.get("area") or "") or "unplaced"
            t = (m.get("time") or "")[:16].replace(":", "").replace("T", "_")
            w.writerow([rel, m.get("time", ""), m.get("dur", ""), nm.get("name", ""), nm.get("area", ""), m.get("lat"), m.get("lon"),
                        m.get("camera", ""), f"{t or 'undated'}_{label}_{Path(rel).name}", m.get("note") or m.get("err") or ""])
    log(f"index written: {out / 'index.csv'} ({sum(1 for m in meta.values() if m.get('lat') is not None)} of {len(meta)} files placed)")


if __name__ == "__main__":
    try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    phase = sys.argv[3] if len(sys.argv) > 3 else "index"
    if phase == "index": index(src, out)
    else: log(f"phase {phase!r} is not built yet (copy and the speech / picture pass come after the Clinton video)")
