"""Pure helpers (no Blender, no network): search-result parsing, relevance and object layout."""
import math
import re

CAM_AZ_DEG = -35.0  # camera azimuth passed to scene_lib.camera(); layout keeps scenery behind the hero from here

_STOP = {"the", "and", "with", "for", "of", "a", "an", "in", "on", "old", "new", "big", "small", "large",
         "realistic", "photorealistic"}


def _words(s):
    out = []
    for w in re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower()).split():
        if len(w) > 2 and w not in _STOP:
            w = re.sub(r"ies$", "y", w)
            out.append(re.sub(r"(es|s)$", "", w))
    return out


def parse_search(text):
    """search_assets text -> [{name, id, tags, category, size, desc}]"""
    out, cur = [], None
    for line in (text or "").splitlines():
        m = re.match(r"^- (.+?) \((?:ID|UID): ([^)]+)\)\s*$", line)
        if m:
            cur = {"name": m.group(1), "id": m.group(2).strip(), "tags": "", "category": "", "size": None, "desc": ""}
            out.append(cur)
            continue
        if cur is None:
            continue
        t = line.strip()
        if t.startswith("Tags: "):
            cur["tags"] = t[6:]
        elif t.startswith("Category: "):
            cur["category"] = t[10:]
        elif t.startswith("Real-world size: "):
            cur["size"] = [float(x) for x in re.findall(r"([\d.]+)m", t)] or None
        elif t and not re.match(r"^(Type|By|Attributes|Up to|Downloads|Licen[cs]e|Faces):", t) and not t.startswith("http"):
            cur["desc"] += " " + t
    return out


def relevance(query, asset):
    q = _words(query)
    if not q:
        return 1.0
    hay = set(_words(f"{asset['name']} {asset['tags']} {asset['category']} {asset['desc']}"))
    return sum(1 for w in q if w in hay) / len(q)


def _rng(seed):
    s = [seed & 0xFFFFFFFF or 1]

    def nxt():
        s[0] = (s[0] * 1664525 + 1013904223) & 0xFFFFFFFF
        return s[0] / 4294967296
    return nxt


def layout(plan, dims):
    """Hero (or what it rests on) at the origin; other ground objects pushed clear of it and kept
    behind it as seen from the camera; "on" objects sit on their support. -> {name: [[x, y, rot, z], ...]}"""
    rand = _rng(len(plan["title"]) * 7919 + len(plan["objects"]))
    by_name = {o["name"]: o for o in plan["objects"]}

    def radius(n):
        d = dims.get(n) or [1, 1, 1]
        return max(d[0], d[1]) / 2

    def support(o):
        s = o.get("on")
        return s if s and s in dims and s in by_name and not by_name[s].get("on") else None

    hero = by_name.get(plan.get("hero"))
    anchor = (support(hero) or hero["name"]) if hero else ""
    anchor_r = radius(anchor) if anchor else 0.0
    a = math.radians(CAM_AZ_DEG)
    cx, cy = math.sin(a), -math.cos(a)
    out = {}

    for i, o in enumerate(plan["objects"]):
        if o["name"] not in dims or support(o):
            continue
        r = radius(o["name"])
        bx, by = (0.0, 0.0) if o["name"] == anchor else (o["x"], o["y"])
        min_d = (anchor_r + r) * 1.15 + 0.1
        if o["name"] != anchor and anchor:
            d = math.hypot(bx, by)
            if d < min_d:
                ang = math.atan2(by, bx) if d > 1e-3 else i * 2.4 + 0.6
                bx, by = math.cos(ang) * min_d, math.sin(ang) * min_d
        pts = []
        for k in range(o["count"]):
            x, y = bx, by
            if o["count"] > 1:
                ang, d = rand() * math.pi * 2, math.sqrt(rand()) * max(o["spread_m"], r * 3)
                x, y = x + math.cos(ang) * d, y + math.sin(ang) * d
            if o["name"] != anchor and anchor:
                ln = math.hypot(x, y)
                dot = x * cx + y * cy  # > 0: towards the camera
                if dot > -0.3 * ln:
                    k2 = dot + 0.6 * ln
                    x, y = x - k2 * cx, y - k2 * cy
                ln = math.hypot(x, y)
                if ln < min_d:
                    x, y = x * min_d / max(ln, 1e-3), y * min_d / max(ln, 1e-3)
            pts.append([round(x, 3), round(y, 3), o["rotation_deg"] + (rand() * 360 if o["count"] > 1 else 0), 0.0])
        out[o["name"]] = pts

    for o in plan["objects"]:
        s = support(o)
        if o["name"] not in dims or not s or s not in out:
            continue
        sx, sy = out[s][0][0], out[s][0][1]
        sd = dims[s]
        pts = []
        for k in range(o["count"]):
            centre = o["name"] == plan.get("hero") and k == 0
            dx = 0.0 if centre else (rand() - 0.5) * sd[0] * 0.6
            dy = 0.0 if centre else (rand() - 0.5) * sd[1] * 0.6
            pts.append([round(sx + dx, 3), round(sy + dy, 3), o["rotation_deg"] + (rand() * 360 if k else 0), round(sd[2], 3)])
        out[o["name"]] = pts
    return out
