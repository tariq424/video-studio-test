"""Label a folder of your own trip media (owner, 2026-10-24: "label the Bermuda videos so we can find them").

Phase "index" (light, safe beside a render): reads each file's metadata (time taken, GPS, length, camera) with ffprobe for
videos and EXIF for photos (HEIC needs pillow-heif), groups files taken within ~150 m of each other into places, names each
place from OpenStreetMap (Nominatim, 1 request a second), and writes <out>/index.csv + <out>/places.json.
Originals are never changed. Copying into <out> with descriptive names, and the speech / picture pass (Whisper + the local
vision model) for files without GPS, are later phases.

Phase "catalog" (runs by itself, below-normal priority, resumable): for every file, one small description file in
<out>/catalog/<descriptive name>.json + .txt pointing to the original: time, GPS place, length, what is SAID (Whisper,
CPU) and what is SEEN (the PC's local vision model, 2 frames per video / the photo itself), people / face close-up flags,
readable sign or plaque text. Also <out>/catalog.csv for searching. Originals are never changed or copied.

Run: python scripts/label_media.py F:\\bermuda F:\\bermuda\\labeled index|catalog
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


SEE = """Look at this picture from a traveller's own phone video or photo (Bermuda trip). Reply with JSON only:
{"description": "one sentence: the place type, the main subject, what is happening", "subject": "2-4 words for a file name",
 "tags": ["up to 6 words: beach, harbour, church, street, house, car interior, mosque, food, people, sign, plaque, sunset, ..."],
 "people": "none|one|few|crowd", "face_closeup": true|false, "readable_text": "any sign / plaque text you can read, else empty",
 "quality": "good|shaky|dark|blurry"}"""


def _frames(p, dur, tmp):
    out = []
    for k, f in enumerate((0.25, 0.65) if dur >= 3 else (0.5,)):
        o = tmp / f"f{k}.jpg"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0.0, dur * f):.2f}", "-i", str(p), "-frames:v", "1", "-vf", "scale=768:-2", str(o)],
                       capture_output=True, timeout=120)
        if o.exists() and o.stat().st_size > 1000: out.append(o)
    return out


def _photo_jpg(p, tmp):
    from PIL import Image
    if p.suffix.lower() == ".heic":
        import pillow_heif; pillow_heif.register_heif_opener()
    im = Image.open(p); im.thumbnail((768, 768)); o = tmp / "photo.jpg"; im.convert("RGB").save(o, quality=88); return o


def _see(cfg, img):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
    from studio import footage
    from studio.llm import parse_json
    return parse_json(footage._vision(dict(cfg, vet_provider="local"), img, SEE))   # this PC's own vision model (Ollama), no account


def _hear(model, p, tmp):
    wav = tmp / "a.wav"
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(p), "-map", "0:a:0", "-ac", "1", "-ar", "16000", str(wav)], capture_output=True, timeout=600)
    if r.returncode or not wav.exists(): return ""
    segs, _ = model.transcribe(str(wav), language="en", vad_filter=True, beam_size=1)
    return " ".join(x.text.strip() for x in segs)[:1500]


def catalog(src, out):
    try:   # HEIC photos need pillow-heif; one-time install into this environment
        import pillow_heif  # noqa: F401
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "pillow-heif"], capture_output=True, timeout=600)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
    from studio import config
    cfg = config.load()
    mf, pf = out / "meta.json", out / "places.json"
    if not mf.exists(): index(src, out)
    meta = json.loads(mf.read_text(encoding="utf-8"))
    places = json.loads(pf.read_text(encoding="utf-8")).get("places", []) if pf.exists() else []
    where = {f: (pl.get("name") or {}) for pl in places for f in pl["files"]}
    cd = out / "catalog"; cd.mkdir(parents=True, exist_ok=True); tmp = out / "_tmp"; tmp.mkdir(exist_ok=True)
    done, failed = set(), {}
    for f in cd.glob("*.json"):
        r = json.loads(f.read_text(encoding="utf-8"))
        if "vision failed" in str(r.get("description", "")) or r.get("error"): failed[r.get("original_rel")] = f   # redo these
        else: done.add(r.get("original_rel"))
    todo = [r for r in sorted(meta, key=lambda r: meta[r].get("time") or "9999") if r not in done]
    log(f"catalog: {len(todo)} file(s) to describe ({len(done)} done)")
    whisper = None
    for n, rel in enumerate(todo):
        p = src / rel; m = meta[rel]; ext = p.suffix.lower()
        rec = {"original": str(p), "original_rel": rel, "taken": m.get("time", ""), "seconds": m.get("dur", 0), "lat": m.get("lat"), "lon": m.get("lon"),
               "place": (where.get(rel) or {}).get("name", ""), "area": (where.get(rel) or {}).get("area", ""),
               "address": (where.get(rel) or {}).get("display", ""), "camera": m.get("camera", "")}
        try:
            imgs = _frames(p, float(m.get("dur") or 0), tmp) if ext in VIDEO else [_photo_jpg(p, tmp)]
            seen = []
            for im in imgs:
                try: seen.append(_see(cfg, im))
                except Exception as e: seen.append({"description": f"(vision failed: {str(e)[:60]})"})
            j0 = seen[0] if seen else {}
            rec.update(description=" / ".join(dict.fromkeys(str(x.get("description", "")) for x in seen if x.get("description"))),
                       subject=str(j0.get("subject") or ""), tags=sorted({t for x in seen for t in (x.get("tags") or [])})[:10],
                       people=str(j0.get("people") or ""), face_closeup=any(bool(x.get("face_closeup")) for x in seen),
                       readable_text=" | ".join(x.get("readable_text") for x in seen if x.get("readable_text")),
                       quality=str(j0.get("quality") or ""))
            if ext in VIDEO and float(m.get("dur") or 0) >= 4:
                if whisper is None:
                    from faster_whisper import WhisperModel
                    whisper = WhisperModel("small.en", device="cpu", compute_type="int8", cpu_threads=4)
                rec["said"] = _hear(whisper, p, tmp)
        except Exception as e:
            rec["error"] = str(e)[:200]
        t = (m.get("time") or "")[:16].replace(":", "").replace("T", "_") or "undated"
        name = f"{t}_{slug(rec.get('place') or rec.get('area') or 'unplaced')}_{slug(rec.get('subject') or '')}_{p.stem}_{p.suffix.lstrip('.').lower()}".replace("__", "_")   # extension too: IMG_0247.MOV and IMG_0247.HEIC are different files
        if rel in failed:   # the earlier failed description is replaced
            failed[rel].unlink(missing_ok=True); failed[rel].with_suffix(".txt").unlink(missing_ok=True)
        (cd / f"{name}.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")
        (cd / f"{name}.txt").write_text(
            f"{name}\nOriginal: {p}\nTaken: {rec['taken']}  Length: {rec['seconds']}s\nPlace: {rec['place']} ({rec['address']})\n"
            f"Seen: {rec.get('description', '')}\nTags: {', '.join(rec.get('tags') or [])}\nPeople: {rec.get('people', '')}"
            f"{'  (face close-up)' if rec.get('face_closeup') else ''}\nText in picture: {rec.get('readable_text', '')}\n"
            f"Said: {rec.get('said', '')}\n", encoding="utf-8")
        if n % 10 == 0: log(f"  {n + 1}/{len(todo)}: {name}")
    rows = [json.loads(f.read_text(encoding="utf-8")) | {"name": f.stem} for f in sorted(cd.glob("*.json"))]
    with open(out / "catalog.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        cols = ["name", "original", "taken", "seconds", "place", "area", "description", "tags", "people", "face_closeup", "readable_text", "quality", "said"]
        w.writerow(cols)
        for r in rows: w.writerow([("; ".join(r.get(c) or []) if c == "tags" else r.get(c, "")) for c in cols])
    log(f"catalog done: {len(rows)} description files in {cd}; table {out / 'catalog.csv'}")


if __name__ == "__main__":
    try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    phase = sys.argv[3] if len(sys.argv) > 3 else "index"
    if phase == "index": index(src, out)
    elif phase == "catalog": catalog(src, out)
    else: log(f"unknown phase {phase!r} (index | catalog)")
