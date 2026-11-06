"""media-poc r11 (Blender over MCP): pure helpers + the real MCP safe-mode validator."""
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parents[1] / "media-poc"
sys.path.insert(0, str(POC))

from blender_mcp.layout import CAM_AZ_DEG, layout, parse_search, relevance  # noqa: E402
from blender_mcp.planner import normalize  # noqa: E402

SEARCH = """2 assets on Poly Haven match 'airplane'
Showing 2:

- Vintage Spacecraft Instrument (ID: vintage_spacecraft_instrument)
  Type: models  |  https://polyhaven.com/a/vintage_spacecraft_instrument
  Category: Electronics & Appliances/Devices & Instruments
  Tags: vintage, analog, retro, rocket, space
  Real-world size: 0.410287m x 0.204402m x 0.269286m (W x D x H)
  Free 8K model of a weathered vintage spacecraft panel.

- Painted Wooden Chair 02 (ID: painted_wooden_chair_02)
  Type: models  |  https://polyhaven.com/a/painted_wooden_chair_02
  Category: Furniture/Seating/Chairs
  Tags: old, wooden, vintage, chair
  Real-world size: 0.63939m x 0.662098m x 1.26377m (W x D x H)
"""


def _obj(name, on="", x=0.0, y=0.0, count=1, spread=0.0):
    return {"name": name, "query": name, "size_m": 1, "x": x, "y": y, "rotation_deg": 0, "count": count,
            "spread_m": spread, "motion": "none", "motion_speed": 1, "on": on}


def test_parse_search_reads_ids_and_sizes():
    found = parse_search(SEARCH)
    assert [a["id"] for a in found] == ["vintage_spacecraft_instrument", "painted_wooden_chair_02"]
    assert found[1]["size"] == pytest.approx([0.63939, 0.662098, 1.26377])


def test_relevance_rejects_wrong_subject():
    spacecraft, chair = parse_search(SEARCH)
    assert relevance("airplane", spacecraft) < 0.5      # search always returns *something*
    assert relevance("wooden chair", chair) == 1.0


def test_layout_puts_object_on_its_support():
    plan = {"title": "t", "hero": "camera", "objects": [_obj("camera", on="table"), _obj("table", x=2, y=1)]}
    spots = layout(plan, {"camera": [0.1, 0.1, 0.14], "table": [1.1, 0.7, 0.8]})
    assert spots["table"][0][:2] == [0.0, 0.0]          # what the hero rests on anchors the shot
    assert spots["camera"][0] == [0.0, 0.0, 0, 0.8]     # hero centred on the table top


def test_layout_keeps_scenery_behind_hero_from_the_camera():
    plan = {"title": "t", "hero": "barrel",
            "objects": [_obj("barrel"), _obj("shelf", x=-1, y=-2), _obj("screen", x=2)]}
    spots = layout(plan, {"barrel": [0.9, 0.9, 1.0], "shelf": [1.1, 0.5, 2.1], "screen": [1.1, 0.9, 1.8]})
    a = math.radians(CAM_AZ_DEG)
    cx, cy = math.sin(a), -math.cos(a)
    for name in ("shelf", "screen"):
        x, y = spots[name][0][:2]
        assert x * cx + y * cy < 0, f"{name} sits between camera and hero"
        assert math.hypot(x, y) > 0.9                   # and doesn't intersect the hero


def test_normalize_dedupes_names_and_drops_bad_supports():
    p = normalize({"title": "x", "hero": "crate", "objects": [
        {"name": "crate", "query": "crate", "on": "nowhere"}, {"name": "crate", "query": "crate", "on": "crate"}]})
    assert [o["name"] for o in p["objects"]] == ["crate", "crate 2"]
    assert p["objects"][0]["on"] == ""                  # unknown support dropped
    assert p["objects"][1]["on"] == "crate"             # valid support kept
    assert p["camera"]["move"] == "orbit" and p["sky"]["time_of_day"] == "afternoon"


@pytest.mark.skipif(not shutil.which("uvx"), reason="uvx not installed")
def test_scene_library_passes_mcp_safe_mode():
    """Every call the route makes must pass BLENDER_MCP_SAFE_MODE=1, checked with the server's own validator."""
    lib = (POC / "blender_mcp" / "scene_lib.py").read_text(encoding="utf-8")
    scripts = [lib + f"\n{fn}(*json.loads({json.dumps(json.dumps([]))}))\n"
               for fn in ("reset", "render_status", "start_render", "free_memory")]
    scripts.append("import bpy\nbpy.context.scene.blendermcp_use_polyhaven = True\nprint('{\"ok\": true}')")
    checker = ("import json,sys\nfrom blender_mcp.safe_mode import validate_code, SandboxViolation\n"
               "bad=[]\nfor s in json.load(sys.stdin):\n"
               "    try: validate_code(s)\n    except SandboxViolation as e: bad.append(str(e))\nprint(json.dumps(bad))")
    try:
        r = subprocess.run(["uvx", "--from", "mcp-for-blender", "python", "-I", "-c", checker],
                           input=json.dumps(scripts), capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        pytest.skip("uvx timed out fetching mcp-for-blender")
    if r.returncode != 0:
        pytest.skip("mcp-for-blender unavailable: " + r.stderr[-200:])
    assert json.loads(r.stdout.strip().splitlines()[-1]) == []
