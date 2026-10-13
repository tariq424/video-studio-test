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


FIGHTER = (r"\b(f-?\d{1,3}[a-z]?s?|fighters?(\s+jets?)?|fighter\s+jets?|warplanes?|combat\s+(jets?|aircraft)|stealth\s+(jets?|fighters?)|"
           r"mig-?\d+s?|su-?\d{2}s?|eurofighters?|rafales?|gripens?|interceptors?|military\s+jets?|air\s+force\s+jets?)\b")
AIRLINER = r"\b(airliners?|jetliners?|passenger\s+(jets?|planes?)|boeing|airbus|7[2-8]7(-\d+)?|[ab]3\d\d(neo)?|embraer|bombardier|airlines?)\b"
SCRAMBLE = r"\b(scrambl\w*|launch\w*|intercept\w*|took off|taking off|take-?off|sent up|dispatch\w*|escort\w*)\b"


def _subject_type(subject):
    if (subject or {}).get("kind") != "aircraft": return None
    return "fighter" if re.search(MILITARY, subject.get("name", ""), re.I) else "airliner"


def aircraft_for(sec, pos=None):
    """Which aircraft this slot draws: {"type": "fighter" | "airliner", "count", "attitude" (or None = the beat's)} or None.
    A beat can name two aircraft ("the jet ... scrambled F-35 fighters"): the beat's subject is one, the narration names another.
    pos = (slot index, slots in the beat): slot i of n plays during the i-th n-th of the narration, so it draws the aircraft named
    in that part (a fighter mention there wins: it is the specific new picture). pos None: the subject, else the first aircraft named."""
    vo = sec.get("vo", ""); sub = _subject_type(sec.get("subject"))
    ments = [(m.start(), "fighter", m.group(0)) for m in re.finditer(FIGHTER, vo, re.I)]
    ments += [(m.start(), "airliner", m.group(0)) for m in re.finditer(AIRLINER, vo, re.I)
              if not any(abs(m.start() - p) < 3 for p, _, _ in ments)]
    # "the jet", "the plane", "the aircraft" with no type: the beat's own aircraft, or an airliner (fighters are always named)
    ments += [(m.start(), sub or "airliner", m.group(0)) for m in re.finditer(AIRCRAFT, vo, re.I)
              if not re.match(r"cockpit", m.group(0), re.I) and not any(abs(m.start() - p) < 6 for p, _, _ in ments)]
    ments.sort()
    if not ments: return {"type": sub, "count": 1, "attitude": None} if sub else None
    if pos is None or not pos[1]:
        typ = sub or ments[0][1]
        pick = next((m for m in ments if m[1] == typ), None)
    else:
        i, n = pos; L = max(1, len(vo)); lo, hi = L * i / n, L * (i + 1) / n
        inside = [m for m in ments if lo <= m[0] < hi]
        pick = (next((m for m in inside if m[1] == "fighter"), None) or (inside[0] if inside else None)
                or min(ments, key=lambda m: min(abs(m[0] - lo), abs(m[0] - hi))))
        typ = pick[1]
    if not pick: return {"type": typ, "count": 1, "attitude": None}
    # the clause around the mention decides plural and attitude (a scramble climbs), not the whole beat
    a = max(vo.rfind(c, 0, pick[0]) for c in ".;,!?") + 1; b = min([x for x in (vo.find(c, pick[0]) for c in ".;!?") if x >= 0] or [len(vo)])
    clause = vo[a:b]
    plural = bool(re.search(r"(s|\bjets|\bfighters|\bwarplanes)$", pick[2], re.I)) or bool(re.search(r"\b(two|pair|several|squadron|jets|fighters|warplanes|f-?\d{1,3}s)\b", clause, re.I))
    att = "climb" if typ == "fighter" and re.search(SCRAMBLE, clause, re.I) else None
    return {"type": typ, "count": 2 if typ == "fighter" and plural else 1, "attitude": att}


def options(sec, ents, moment=None, k=0, pos=None):
    """Every illustration / silhouette that fits this beat, best first: [{"type": "graphic", "g": ..., "rung", "tag"}].
    pos = (slot index, slots in the beat), for the aircraft that part of the narration names (aircraft_for)."""
    vo = sec.get("vo", ""); look = vo + " " + (sec.get("still_prompt") or "")
    subject = sec.get("subject")
    aero = (subject or {}).get("kind") == "aircraft" or bool(re.search(AIRCRAFT, look, re.I))
    ph = (coherence.phase(vo) if moment is None else moment) if aero else ""   # flight phases only mean something in an aviation beat
    ac = aircraft_for(sec, pos) if aero else None
    tod, att, gr = time_of_day(look), (attitude(vo, ph) if aero else "level"), ground(look)
    if ac and ac.get("attitude"): att = ac["attitude"]
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
        if ac and s in ("sky", "airport"):
            g["aircraft"] = ac["type"]; g["count"] = ac["count"]
            if ac["type"] == "airliner":   # the airline the beat names / is about wears its livery (liveries.py)
                from . import liveries
                lv = liveries.pick(vo, f"{(subject or {}).get('name', '')} {(subject or {}).get('brand', '')}", liveries.story_text(ents))
                if lv: g["livery"] = lv
        out.append({"type": "graphic", "g": g, "rung": "illustration", "tag": "ILLUSTRATION"})
    if ac and ac["type"] == "fighter":   # a fighter slot: the fighter in the sky first (a cockpit / radar scene would hide it)
        out.sort(key=lambda o: o["g"].get("scene") != "sky")
    sh = shape_of(subject, vo, ents)
    if ac and sh in ("airliner", "jet"): sh = "jet" if ac["type"] == "fighter" else "airliner"
    if sh:
        # a black shape needs a light sky behind it: night and day become dusk. No text: the beat's own graphics carry the words.
        out.append({"type": "graphic", "g": {"kind": "silhouette", "shape": sh, "time": "storm" if tod == "storm" else "dusk",
                    "attitude": att if sh in ("airliner", "jet") else "level", "pose": pose(vo), "seed": seed},
                    "rung": "silhouette", "tag": "SILHOUETTE"})
    return out


def variants(sec, ents, moment=None):
    """For the review menu: the beat's options for every aircraft it names (a beat with the airliner and the scrambled fighters
    offers both), duplicates removed."""
    out, seen = [], set()
    for pos in (None, (0, 4), (1, 4), (2, 4), (3, 4)):
        for o in options(sec, ents, moment, 0, pos):
            g = o["g"]; key = (g["kind"], g.get("scene"), g.get("shape"), g.get("aircraft"))
            if key not in seen: seen.add(key); out.append(o)
    return out


def pick(sec, ents, moment=None, k=0, pos=None):
    """The k-th option for slot k of this beat (cycling), or None when nothing fits."""
    opts = options(sec, ents, moment, k, pos)
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
