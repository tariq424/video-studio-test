"""Render each implemented physics module in the isolated checkout only."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if ROOT != Path(r"F:\code\video-studio-test"):
    raise SystemExit("This smoke test only runs in the isolated checkout")
sys.path.insert(0, str(ROOT / "app"))
from studio import config, physics, review
from studio.render_media import inspect_video

os.environ["PORT"] = "42021"
out = Path(r"F:\videos_test\jobs\physics_modules_20261018")
out.mkdir(parents=True, exist_ok=True)
(out / "space.json").write_text(json.dumps({"w": 1280, "h": 720}))
cases = {
    "aircraft_flight": {"start_alt_ft": 30000, "end_alt_ft": 18000, "descent_secs": 40},
    "submarine_descent": {"max_depth_m": 1000, "sink_mps": 1},
    "weather_event": {"_context": "A synthetic tropical storm moves across the ocean"},
    "ship_route": {"_context": "A ship transits the Strait of Hormuz"},
    "radar_sweep": {},
}
results = {}
for name, params in cases.items():
    graphic = physics.run(name, params, config.load())
    assert graphic and graphic["kind"] in {"sim", "simmap", "motion"}, (name, graphic)
    if name == "submarine_descent":
        assert min(point[1] for point in graphic["series"]) == -1000
    if name == "aircraft_flight":
        assert min(point[1] for point in graphic["series"]) == 18000
    video = out / f"{name}.mp4"
    review._remotion(out, {"type": "graphic", "g": graphic}, 4, video,
                     config.load(), print, frames=(0, 119), scale=1)
    validation = inspect_video(video)
    assert validation["frames"] == 120, validation
    samples = []
    for seconds in (0.8, 2.8):
        samples.append(subprocess.run([
            "ffmpeg", "-v", "error", "-ss", str(seconds), "-i", str(video),
            "-frames:v", "1", "-vf", "crop=900:360:190:180,scale=160:90",
            "-pix_fmt", "rgb24", "-f", "rawvideo", "-",
        ], capture_output=True, check=True).stdout)
    assert len(samples[0]) == 160 * 90 * 3
    delta = sum(abs(a-b) for a, b in zip(*samples)) / len(samples[0])
    assert delta > 0.1, (name, delta)
    results[name] = {"graphic": graphic, "validation": validation, "motion_delta": delta}
    (out / "report.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
print(json.dumps({name: r["motion_delta"] for name, r in results.items()}, indent=2))
