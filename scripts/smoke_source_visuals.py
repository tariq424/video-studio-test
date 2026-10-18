"""Real extraction + Short/long ladder integration + Remotion source-evidence render."""
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
assert ROOT == Path(r"F:\code\video-studio-test")
os.environ["PORT"] = "42021"
sys.path.insert(0, str(ROOT / "app"))
from studio import config, media, review, short, source_visuals
from studio.render_media import inspect_video

job = Path(r"F:\videos_test\jobs\source_evidence_smoke")
(job / "src").mkdir(parents=True, exist_ok=True)
original = job / "src/source_video.mp4"
if not original.exists():
    media.ff("-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30", "-t", 6,
             "-c:v", "libx264", "-pix_fmt", "yuv420p", original)
before = hashlib.sha256(original.read_bytes()).hexdigest()
(job / "src/meta.json").write_text(json.dumps({"channel": "Owned calibration fixture", "title": "Extraction test"}))
workspace = job / "short"
(workspace / "stock").mkdir(parents=True, exist_ok=True)
(workspace / "space.json").write_text(json.dumps({"w": 1280, "h": 720}))
cfg = {**config.load(), "source_visuals": True, "source_visual_max_uses": 2, "ladder_v2": True,
       "cloud_on": False, "graphics_claude": False}
plan = {"sections": []}
for index, kind in enumerate(("screenshot", "clip")):
    plan["sections"].append({"id": f"b{index}", "vo": "Radar sweeps show direction, not proof of what was measured.",
        "queries": [], "visuals": [], "backdrop": {"kind": "headline", "text": "Our analysis"},
        "source_visual": {"kind": kind, "start": 1, "duration": 2.5,
                          "purpose": "A moving display alone cannot establish measurement accuracy"}})
(workspace / "timings.json").write_text(json.dumps({s["id"]: {"dur": 4, "words": []} for s in plan["sections"]}))
(workspace / "stock/pick.json").write_text("{}")
# Idempotent fixture reruns do not reuse a previously compiled ladder result.
for name in ("fallback.json", "fallback/chains.json"):
    (workspace / name).unlink(missing_ok=True)
class NoGenerator:
    def alive(self): return False
    def gen(self, *args, **kwargs): raise AssertionError("Source-filled slots must not call WanGP")
short.do_fallback(job, plan, cfg, NoGenerator(), print, lambda: False)
items = json.loads((workspace / "fallback.json").read_text())
report = {}
for section in plan["sections"]:
    item = items[section["id"]][0]
    assert item["rung"] == "source" and item["g"]["graphic"]["kind"] == "motion", item
    kind = item["g"]["media"]
    out = job / f"{kind}.mp4"
    review._remotion(workspace, {"type": "graphic", "g": item["g"]}, 4, out, cfg, print, frames=(0, 119), scale=1)
    checked = inspect_video(out)
    assert checked["frames"] == 120
    # At 1s the left evidence panel is present. At 3.2s it has disappeared; custom radar remains.
    for second in (1, 3.2):
        media.ff("-ss", second, "-i", out, "-frames:v", 1, job / f"{kind}-{second}.png")
    report[kind] = {"validation": checked, "source_seconds": item["g"]["seconds"], "graphic": item["g"]["graphic"]["module"]}
long_plan = {"sections": [{"id": "s0", "vo": plan["sections"][0]["vo"], "visuals": [
    {"id": "s0_0", "type": "still", "prompt": "Radar", "source_visual": plan["sections"][0]["source_visual"]}]}]}
source_visuals.apply_long(job, long_plan, cfg, print)
assert long_plan["sections"][0]["visuals"][0]["g"]["kind"] == "source_excerpt"
(workspace / "space.json").write_text(json.dumps({"w": 720, "h": 1280}))
portrait = job / "portrait.mp4"
review._remotion(workspace, {"type": "graphic", "g": items["b1"][0]["g"]}, 4, portrait,
                 cfg, print, frames=(0, 119), scale=1)
report["portrait"] = inspect_video(portrait)
assert report["portrait"]["frames"] == 120
media.ff("-ss", 1, "-i", portrait, "-frames:v", 1, job / "portrait.png")
assert before == hashlib.sha256(original.read_bytes()).hexdigest()
report["long_ladder"] = True
report["source_sha256_unchanged"] = before
(job / "report.json").write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
