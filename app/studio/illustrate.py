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
    ("radar", r"\b(radar|transponder|squawk\w*|air traffic control\w*|air traffic controllers?|flight ?radar|hijack (code|signal))\b"),
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


DIVE = r"\b(descen\w*|dropp?\w*|dives?|dived|dove|diving|plunge\w*|plummet\w*|fell|fall\w*|lost altitude|losing altitude|nose-?dive\w*|sank|sinking|crash\w*)\b"
CLIMB = r"\b(climb\w*|took off|taking off|take-?off|gained altitude|ascend\w*|rose|rising|soar\w*)\b"
BANK = r"\b(bank\w*|turn\w*|veer\w*|swerv\w*|circl\w*|divert\w*|u-?turn)\b"


def attitude(text, ph):
    """Aircraft attitude from the narration's verb: dive | climb | bank | level; the verb wins over the phase (a beat about a dive
    that also mentions the later landing still shows the dive); without a verb, landing / ground from the phase."""
    if re.search(DIVE, text, re.I): return "dive"
    if re.search(CLIMB, text, re.I): return "climb"
    if re.search(BANK, text, re.I) and ph not in ("ground",): return "bank"
    if ph == "ground": return "ground"
    if ph == "landing": return "landing"
    return "level"


def pose(text):
    """Cars / people: moving (drive, race, flee, run, walk...) or still. Buildings have no pose."""
    return "moving" if re.search(r"\b(driv\w*|drove|speed\w*|rac\w*|chas\w*|flee\w*|fled|run\w*|ran|rush\w*|walk\w*|march\w*|evacuat\w*)\b", text, re.I) else "still"


def ground(text):
    if re.search(r"\b(desert|sand\w*|saudi|arabia|dubai|gulf|emirates?|qatar|egypt|sahara)\b", text, re.I): return "desert"
    if re.search(r"\b(sea|ocean|coast\w*)\b", text, re.I): return "sea"
    return "green"


def shape_of(subject, text, ents):
    kind = (subject or {}).get("kind")
    if kind == "aircraft" or re.search(AIRCRAFT, text, re.I):
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
    aero = (subject or {}).get("kind") == "aircraft" or bool(re.search(AIRCRAFT, look, re.I))
    ph = (coherence.phase(vo) if moment is None else moment) if aero else ""   # flight phases only mean something in an aviation beat
    tod, att, gr = time_of_day(look), (attitude(vo, ph) if aero else "level"), ground(look)
    seed = 3 + int(re.sub(r"\D", "", sec.get("id", "0")) or 0) * 7 + k
    scenes = [name for name, rx in SCENES if re.search(rx, vo, re.I)]
    if (subject or {}).get("interior") and "cockpit" not in scenes: scenes.insert(0, "cockpit")
    if aero:
        if att in ("dive", "climb", "bank"): scenes = ["sky"] + [s for s in scenes if s != "sky"]
        elif ph in ("ground", "landing"): scenes = ["airport"] + [s for s in scenes if s != "airport"]
        elif "sky" not in scenes: scenes.insert(0 if ph == "air" or not scenes else 1, "sky")
    if aero and (ph == "air" or att in ("dive", "climb", "bank")):   # in the air (or the verb says so): never on a runway, the sky first
        scenes = [s for s in scenes if s != "airport"]
        if "sky" in scenes: scenes = ["sky"] + [s for s in scenes if s != "sky"]
    out = []
    for s in dict.fromkeys(scenes):
        g = {"kind": "illustration", "scene": s, "time": tod, "attitude": "landing" if s == "airport" and ph == "landing" else att,
             "ground": gr, "seed": seed}
        if s == "cockpit": g["alarm"] = bool(re.search(r"\b(alarm\w*|warning|emergency|fight\w*|fought|struggl\w*|hijack\w*|attack\w*)\b", vo, re.I))
        out.append({"type": "graphic", "g": g, "rung": "illustration", "tag": "ILLUSTRATION"})
    sh = shape_of(subject, vo, ents)
    if sh:
        # a black shape needs a light sky behind it: night and day become dusk. No text: the beat's own graphics carry the words.
        out.append({"type": "graphic", "g": {"kind": "silhouette", "shape": sh, "time": "storm" if tod == "storm" else "dusk",
                    "attitude": att if sh in ("airliner", "jet") else "level", "pose": pose(vo), "seed": seed},
                    "rung": "silhouette", "tag": "SILHOUETTE"})
    return out


def pick(sec, ents, moment=None, k=0):
    """The k-th option for slot k of this beat (cycling), or None when nothing fits."""
    opts = options(sec, ents, moment, k)
    return opts[k % len(opts)] if opts else None


AIRCRAFT = (r"\b(planes?|jets?|jetliners?|aircraft|airliners?|airplanes?|aeroplanes?|boeing|airbus|cessna|embraer|bombardier|turboprops?|"
            r"helicopters?|choppers?|drones?|fighters?|f-?\d{1,3}s?|[ab]3\d\d|7[2-8]7(-\d+)?|mig-?\d+|su-?\d+|airframe|fuselage|cockpit)\b")
VEHICLE = r"\b(cars?|trucks?|lorr(y|ies)|bus(es)?|vans?|trains?|locomotives?|ships?|boats?|vessels?|tankers?|ferr(y|ies)|tanks?|motorcycles?|vehicles?)\b"
LANDMARK = (r"\b(white house|kremlin|capitol|parliament|embassy|palace|cathedral|mosque|temple|stadium|headquarters|tower|bridge|"
            r"pentagon|ministry building|airport terminal)\b")


def wangp_lock(sec, ents, moment=None):
    """Why WanGP must NOT draw this beat ("" = it may): aircraft (narration or still prompt names one, or the beat is in the air /
    at an airport), vehicles, specific buildings, real people. These are exactly the subjects whose anatomy WanGP hallucinates
    (four wings, wrong engines, wrong attitude, wrong livery)."""
    from .cloudgen import has_person
    vo = sec.get("vo", ""); sp = sec.get("still_prompt") or ""; both = vo + " " + sp
    kind = (sec.get("subject") or {}).get("kind")
    ph = coherence.phase(vo) if moment is None else moment
    if kind == "aircraft" or re.search(AIRCRAFT, both, re.I): return "aircraft beat"
    if re.search(r"\b(airport|runway|tarmac|apron|flight|pilots?|airline)\b", both, re.I) and ph in ("air", "landing", "ground"):
        return "aircraft beat (in the air / at an airport)"
    if kind in ("vehicle", "ship", "train") or re.search(VEHICLE, both, re.I): return "vehicle beat"
    if kind == "building" or re.search(LANDMARK, both, re.I): return "specific building"
    if kind == "person" or has_person(vo, ents): return "names a real person"
    return ""
