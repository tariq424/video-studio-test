"""Flat illustrations and silhouettes for a beat (remotion/src/Illustration.tsx): the ladder rung after the WanGP still and
before claymation (3D reconstruction). Pure Remotion/SVG, CPU only, no model.

  illustration: a flat vector scene - sky (aircraft in flight, nose by the narration), airport (landing / on the ground),
                city skyline (officials, capital, statements), radar scope (tracking, transponder), cockpit (pilots), sea
  silhouette:   the subject's shape (airliner, fighter jet, people, buildings, car, ship) against a sky gradient, with the
                beat's short headline as optional text

Everything is chosen from the narration (and the still prompt for time of day) with keyword rules - no AI call. A beat with
nothing to draw (abstract narration, no subject) gets None, and the ladder falls back to claymation / the headline card."""
import re
from . import coherence

SCENES = [
    ("radar", r"\b(radar|transponder|squawk\w*|air traffic control\w*|controllers?|tracking|tracked|signal|flight ?radar)\b"),
    ("cockpit", r"\b(cockpit|flight deck|pilots?|captain|co-?pilot|first officer)\b"),
    ("airport", r"\b(airport|runway|tarmac|apron|land(ed|ing|s)?|touch(ed|es)? down|taxi\w*|terminal|parked|on the ground)\b"),
    ("sea", r"\b(sea|ocean|coast\w*|ship|navy|harbou?r|vessel)\b"),
    ("city", r"\b(capital|city|government|ministry|minister|officials?|parliament|embassy|newsroom|statement|press conference|authorities|announced)\b"),
]
MILITARY = r"\b(f-?\d+|fighter|military|combat|stealth|bomber|air force|warplane)s?\b"


def time_of_day(text):
    t = text.lower()
    if re.search(r"\b(storm\w*|thunder\w*|lightning|turbulen\w*|rain\w*)\b", t): return "storm"
    if re.search(r"\b(night\w*|midnight|darkness|overnight)\b", t): return "night"
    if re.search(r"\b(morning|noon|midday|afternoon|daylight|sunny|blue sky)\b", t): return "day"
    return "dusk"


def attitude(text, ph):
    if ph == "ground": return "ground"
    if ph == "landing": return "landing"
    if re.search(r"\b(descen\w*|dropp?\w*|dive|diving|plunge\w*|plummet\w*|fell|fall\w*|lost altitude|losing altitude|nosedive\w*)\b", text, re.I): return "down"
    if re.search(r"\b(climb\w*|took off|taking off|gained altitude|ascend\w*)\b", text, re.I): return "up"
    return "level"


def ground(text):
    if re.search(r"\b(desert|sand\w*|saudi|arabia|dubai|gulf|emirates?|qatar|egypt|sahara)\b", text, re.I): return "desert"
    if re.search(r"\b(sea|ocean|coast\w*)\b", text, re.I): return "sea"
    return "green"


def shape_of(subject, text, ents):
    kind = (subject or {}).get("kind")
    if kind == "aircraft" or re.search(r"\b(plane|jet|airliner|aircraft|flight|boeing|airbus)\b", text, re.I) or re.search(MILITARY, text, re.I):
        mil = re.search(MILITARY, (subject or {}).get("name", ""), re.I) if subject else re.search(MILITARY, text, re.I)
        return "jet" if mil else "airliner"
    if kind == "vehicle" or re.search(r"\b(car|truck|bus|vehicle)\b", text, re.I): return "car"
    if kind == "ship" or re.search(r"\b(ship|vessel|boat|tanker)\b", text, re.I): return "ship"
    if kind == "building" or re.search(r"\b(building|ministry|embassy|parliament|palace|headquarters)\b", text, re.I): return "building"
    if kind == "person" or re.search(r"\b(passengers?|people|crew|officials?|pilots?|analysts?|experts?|witness\w*|minister|spokes\w*)\b", text, re.I):
        return "people" if re.search(r"\b(passengers|people|crew|officials|pilots|analysts|experts|witnesses)\b", text, re.I) else "person"
    return None


def options(sec, ents, moment=None, k=0):
    """Every illustration / silhouette that fits this beat, best first: [{"type": "graphic", "g": ..., "rung", "tag"}]."""
    vo = sec.get("vo", ""); look = vo + " " + (sec.get("still_prompt") or "")
    subject = sec.get("subject")
    ph = coherence.phase(vo) if moment is None else moment
    tod, att, gr = time_of_day(look), attitude(vo, ph), ground(look)
    seed = 3 + int(re.sub(r"\D", "", sec.get("id", "0")) or 0) * 7 + k
    scenes = [name for name, rx in SCENES if re.search(rx, vo, re.I)]
    if (subject or {}).get("interior") and "cockpit" not in scenes: scenes.insert(0, "cockpit")
    if (subject or {}).get("kind") == "aircraft" or re.search(r"\b(plane|jet|airliner|aircraft|flight)\b", vo, re.I):
        if ph in ("ground", "landing"): scenes = ["airport"] + [s for s in scenes if s != "airport"]
        elif "sky" not in scenes: scenes.insert(0 if ph == "air" or not scenes else 1, "sky")
    if ph == "air": scenes = [s for s in scenes if s != "airport"]   # in the air: never on a runway
    out = []
    for s in dict.fromkeys(scenes):
        g = {"kind": "illustration", "scene": s, "time": tod, "attitude": "landing" if s == "airport" and ph == "landing" else att,
             "ground": gr, "seed": seed}
        if s == "cockpit": g["alarm"] = bool(re.search(r"\b(alarm\w*|warning|emergency|fight\w*|fought|struggl\w*|hijack\w*|attack\w*)\b", vo, re.I))
        out.append({"type": "graphic", "g": g, "rung": "illustration", "tag": "ILLUSTRATION"})
    sh = shape_of(subject, vo, ents)
    if sh:
        bd = sec.get("backdrop") or {}
        text = (bd.get("text") or "")[:60] if bd.get("kind") == "headline" else ""
        out.append({"type": "graphic", "g": {"kind": "silhouette", "shape": sh, "time": tod if tod != "day" else "dusk",
                    "attitude": att if sh in ("airliner", "jet") else "level", "text": text, "seed": seed},
                    "rung": "silhouette", "tag": "SILHOUETTE"})
    return out


def pick(sec, ents, moment=None, k=0):
    """The k-th option for slot k of this beat (cycling), or None when nothing fits."""
    opts = options(sec, ents, moment, k)
    return opts[k % len(opts)] if opts else None
