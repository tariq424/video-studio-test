"""Text -> shot plan with a local Ollama model and a strict JSON schema.

The model only decides WHAT is in the shot; geometry (framing, distances, ground
contact) is computed in Blender, so a small model can't break the shot.
keep_alive=0 unloads the model right after, so Cycles gets the whole GPU.
"""
import json
import os
import re

import requests

OLLAMA = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
MODEL = os.environ.get("BLENDER_PLANNER_MODEL", "qwen3:14b")

MOTIONS = ["none", "spin", "float", "fall", "drive", "flight_tumble"]
MOVES = ["static", "orbit", "dolly_in", "dolly_out", "pan_left", "pan_right", "crane_up", "flyover", "tracking"]
TIMES = ["sunrise", "morning", "midday", "afternoon", "golden hour", "sunset", "dusk", "night", "overcast"]

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "sky": {"type": "object", "properties": {
            "query": {"type": "string"},
            "time_of_day": {"type": "string", "enum": TIMES},
            "strength": {"type": "number"}}, "required": ["query", "time_of_day", "strength"]},
        "ground": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        "water": {"type": "boolean"},
        "objects": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "query": {"type": "string"}, "size_m": {"type": "number"},
            "x": {"type": "number"}, "y": {"type": "number"}, "rotation_deg": {"type": "number"},
            "count": {"type": "integer"}, "spread_m": {"type": "number"},
            "motion": {"type": "string", "enum": MOTIONS}, "motion_speed": {"type": "number"},
            "on": {"type": "string"}},
            "required": ["name", "query", "size_m", "x", "y", "rotation_deg", "count", "spread_m",
                         "motion", "motion_speed", "on"]}},
        "hero": {"type": "string"},
        "camera": {"type": "object", "properties": {
            "move": {"type": "string", "enum": MOVES}, "lens_mm": {"type": "number"},
            "handheld": {"type": "boolean"}, "depth_of_field": {"type": "boolean"}, "speed": {"type": "number"}},
            "required": ["move", "lens_mm", "handheld", "depth_of_field", "speed"]},
        "fog": {"type": "number"},
        "exposure": {"type": "number"},
    },
    "required": ["title", "sky", "ground", "water", "objects", "hero", "camera", "fog", "exposure"],
}

SYSTEM = """You are a cinematographer and set dresser planning ONE photorealistic shot that Blender (Cycles) will render.
Assets come from Poly Haven (CC0): HDRI skies, PBR ground textures, and realistic 3D models.
Poly Haven HAS: furniture, chairs, tables, sofas, lamps, shelves, kitchenware, food, fruit, bottles, books, tools,
barrels, crates, boxes, rocks, boulders, tree stumps, logs, plants, potted plants, ferns, bushes, flowers,
street props, benches, fences, statues, some vehicles (covered car, old truck, bicycle), electronics, cameras.
Poly Haven does NOT have: people, animals, aircraft, spaceships, buildings, modern sports cars. If the description
needs those, still list them (the app will report they are unavailable) but build the rest of the shot well.

Rules:
- Units are metres. Ground is z=0. x/y are positions on the ground; the hero goes at x=0, y=0.
- size_m = real largest dimension (chair 1.0, table 1.6, apple 0.08, boulder 2.5, barrel 0.9, car 4.5).
- Use 1-6 objects. Keep everything within ~8 m of the hero unless it is scenery.
- on: the name of the object this one rests on ("camera on a table" -> the camera has on="<table name>"),
  or "" when it stands on the ground. Only one level (no stacks of stacks).
- Do NOT add lights, softboxes or lighting equipment: the HDRI lights the scene. Only visible physical things.
- count > 1 only for repeated things (rocks, plants, crates); spread_m = radius they scatter over.
- sky.query: short HDRI search, e.g. "sunset clear sky", "overcast forest", "night city", "studio softbox".
  strength 0.6-1.5. For indoor/studio shots use a studio HDRI and a floor texture like "wooden floor".
- ground.query: a floor or terrain texture ("forest floor leaves", "sand beach", "asphalt road", "grass meadow").
  Use "" only for pure sky/water shots. water=true for sea/lake shots.
- motion: what the text implies; most props are "none". "fall" drops from above, "drive" slides across,
  "flight_tumble" = drop, roll and recover (for flying things), "spin" turntable, "float" gentle bob.
- camera.move: orbit (default hero shot), dolly_in (reveal), crane_up (establishing), flyover (landscape),
  tracking (follows a moving hero), pan_left/right (scan), static. lens_mm 24-35 wide, 50 natural,
  85-100 close-up. speed 0.5-1.5.
- fog 0-1 (0 clear, 0.3 haze, 0.7 thick). exposure -1..1 (0 normal). title: 2-6 words.
Return ONLY the JSON object."""


def available():
    """(up, has_model)"""
    try:
        r = requests.get(f"{OLLAMA}/api/tags", timeout=2)
        names = {m.get("name") for m in r.json().get("models", [])} | {m.get("model") for m in r.json().get("models", [])}
        return True, MODEL in names
    except Exception:
        return False, False


def plan_shot(prompt):
    r = requests.post(f"{OLLAMA}/api/chat", timeout=300, json={
        "model": MODEL, "stream": False, "think": False, "keep_alive": 0, "format": SCHEMA,
        "options": {"temperature": 0.4, "num_ctx": 8192},
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": f"Shot description: {prompt}"}]})
    r.raise_for_status()
    raw = re.sub(r"^```(json)?|```$", "", (r.json().get("message") or {}).get("content", "").strip()).strip()
    try:
        return normalize(json.loads(raw))
    except json.JSONDecodeError as e:
        raise ValueError(f"planner returned invalid JSON: {raw[:200]}") from e


def unload():
    """Belt and braces: make sure the planner model is out of VRAM."""
    try:
        requests.post(f"{OLLAMA}/api/generate", json={"model": MODEL, "keep_alive": 0}, timeout=20)
    except Exception:
        pass


def _clamp(v, lo, hi, d):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return d
    return d if v != v else min(hi, max(lo, v))


def normalize(p):
    objs = []
    for i, o in enumerate((p.get("objects") or [])[:6]):
        name = re.sub(r"[^\w -]", "", str(o.get("name") or o.get("query") or f"object{i}")).strip()[:40] or f"object{i}"
        objs.append({
            "name": name, "query": str(o.get("query") or name)[:80],
            "size_m": _clamp(o.get("size_m"), 0.03, 60, 1), "x": _clamp(o.get("x"), -60, 60, 0),
            "y": _clamp(o.get("y"), -60, 60, 0), "rotation_deg": _clamp(o.get("rotation_deg"), -360, 360, 0),
            "count": int(round(_clamp(o.get("count"), 1, 24, 1))), "spread_m": _clamp(o.get("spread_m"), 0, 40, 0),
            "motion": o.get("motion") if o.get("motion") in MOTIONS else "none",
            "motion_speed": _clamp(o.get("motion_speed"), 0.2, 3, 1), "on": str(o.get("on") or "").strip()})
    used = set()
    for o in objs:  # unique names (the model sometimes repeats one)
        n, k = o["name"], 2
        while n.lower() in used:
            n = f"{o['name']} {k}"; k += 1
        used.add(n.lower()); o["name"] = n
    names = [o["name"] for o in objs]
    for o in objs:
        if o["on"] not in names or o["on"] == o["name"]:
            o["on"] = ""
    sky, cam = p.get("sky") or {}, p.get("camera") or {}
    return {
        "title": str(p.get("title") or "Untitled shot")[:60],
        "sky": {"query": str(sky.get("query") or "clear sky")[:60],
                "time_of_day": sky.get("time_of_day") if sky.get("time_of_day") in TIMES else "afternoon",
                "strength": _clamp(sky.get("strength"), 0.2, 3, 1)},
        "ground": {"query": str((p.get("ground") or {}).get("query") or "")[:60]},
        "water": bool(p.get("water")),
        "objects": objs,
        "hero": p.get("hero") if p.get("hero") in names else (names[0] if names else ""),
        "camera": {"move": cam.get("move") if cam.get("move") in MOVES else "orbit",
                   "lens_mm": _clamp(cam.get("lens_mm"), 14, 135, 35), "handheld": bool(cam.get("handheld")),
                   "depth_of_field": cam.get("depth_of_field") is not False, "speed": _clamp(cam.get("speed"), 0.3, 2, 1)},
        "fog": _clamp(p.get("fog"), 0, 1, 0),
        "exposure": _clamp(p.get("exposure"), -2, 2, 0),
    }
