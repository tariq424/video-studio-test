"""Search Pexels (portrait videos) for each teaser beat; save metadata + thumbnails for vetting.
The API key is read from the project .env at run time and never printed."""
import json, sys, time, requests
from pathlib import Path
ENV = Path(__file__).resolve().parent.parent / ".env"
KEY = next((l.split("=", 1)[1].strip().strip('"\'') for l in ENV.read_text().splitlines() if l.startswith("PEXELS_API_KEY=")), "")
if not KEY: sys.exit("no PEXELS_API_KEY in project .env")
OUT = Path(r"F:\videos\explainer_studio\shorts\moonshots_teaser_v2\stock"); (OUT / "thumbs").mkdir(parents=True, exist_ok=True)
Q = json.loads((OUT / "queries.json").read_text(encoding="utf-8"))
res = {}
for beat, queries in Q.items():
    res[beat] = []
    for q in queries:
        r = requests.get("https://api.pexels.com/videos/search", headers={"Authorization": KEY},
                         params={"query": q, "orientation": "portrait", "per_page": 6, "size": "medium"}, timeout=30)
        if r.status_code != 200: print(beat, q, "HTTP", r.status_code); continue
        for v in r.json().get("videos", []):
            files = sorted([f for f in v["video_files"] if f.get("width") and f.get("height") and f["height"] > f["width"]],
                           key=lambda f: abs(f["height"] - 1920))
            if not files: continue
            vid = str(v["id"]); thumb = OUT / "thumbs" / f"{vid}.jpg"
            if not thumb.exists():
                t = requests.get(v["image"], timeout=30)
                if t.ok: thumb.write_bytes(t.content)
            res[beat].append({"id": vid, "query": q, "dur": v["duration"], "w": files[0]["width"], "h": files[0]["height"],
                              "file": files[0]["link"], "page": v["url"], "author": v["user"]["name"]})
        time.sleep(0.4)
    print(beat, len(res[beat]), "candidates")
(OUT / "candidates.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
print("STOCK_SEARCH_DONE")
