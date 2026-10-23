"""Smoke test of the story subject guard on still images (no job, no pipeline): each image is checked as if it were a stock
clip in a story about <brand> set in <country text>. Report next to the images (guard_report.md / .json).
    app\\env\\Scripts\\python.exe scripts\\guard_probe.py <image folder> [brand] [story text]"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from studio import config, footage  # noqa: E402


def main():
    folder = Path(sys.argv[1]); brand = sys.argv[2] if len(sys.argv) > 2 else "Tesla"
    story = sys.argv[3] if len(sys.argv) > 3 else f"{brand}'s car sales in China"
    cfg = config.load()
    work = folder / "_frames"; work.mkdir(exist_ok=True)
    guard = {"kinds": {"vehicle": [brand]}, "side": footage.drive_side(story)}
    rows = []
    imgs = sorted(p for p in folder.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"))
    print(f"{len(imgs)} images; story: {story!r}; guard {guard}", flush=True)
    for p in imgs:
        cid = p.stem
        for k in range(4): _jpg(p, work / f"{cid}_f{k}.jpg")
        t0 = time.time()
        ok, why = footage.make_check(cfg, {"id": cid}, work / f"{cid}.jpg", guard, story, print)
        raw = ""
        try:
            what, who = footage.KIND_WORDS["vehicle"]
            raw = footage._vision(dict(cfg, vet_provider="local"), work / f"{cid}_pair.jpg", footage.MAKE.format(what=what, who=who)).strip()[:300]
        except Exception as e: raw = f"(raw failed: {e})"[:200]
        rows.append({"image": p.name, "verdict": "KEEP" if ok else "DROP", "why": why, "secs": round(time.time() - t0, 1), "raw": raw})
        print(f"     raw: {raw}", flush=True)
        print(f"  {p.name}: {'KEEP' if ok else 'DROP'} {why} ({rows[-1]['secs']}s)", flush=True)
    (folder / "guard_report.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    md = [f"# Story guard probe: {brand}, \"{story}\"", "", "| Image | Verdict | Why |", "|---|---|---|"]
    md += [f"| {r['image']} | {r['verdict']} | {r['why']} |" for r in rows]
    (folder / "guard_report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("done", flush=True)


def _jpg(src, dst):
    from PIL import Image
    with Image.open(src) as im:
        im = im.convert("RGB"); im.thumbnail((640, 640)); im.save(dst, "JPEG", quality=90)


if __name__ == "__main__":
    main()
