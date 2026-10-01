import json, requests
from pathlib import Path
OUT = Path(r"F:\videos\explainer_studio\shorts\moonshots_teaser_v2\stock"); (OUT / "clips").mkdir(exist_ok=True)
pick = json.loads((OUT / "pick.json").read_text(encoding="utf-8"))
for b, vs in pick.items():
    for v in vs:
        p = OUT / "clips" / f"{v['name']}.mp4"
        if p.exists() and p.stat().st_size > 100000: continue
        r = requests.get(v["file"], timeout=120, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status(); p.write_bytes(r.content); print(v["name"], len(r.content) // 1024, "KB", flush=True)
print("STOCK_DOWNLOAD_DONE")
