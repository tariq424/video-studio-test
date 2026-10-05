"""Story-level coherence: what identifiable things is this story about, which shots must show exactly them, and what to show
when no real footage of them exists.

1. entities(): one LLM call lists the story's identifiable subjects (a named airline's aircraft, a car model, a ship, a product,
   named people) with their category words and colours. Cached in <job>/entities.json, shared by the long video and the Short.
2. assign(): every shot whose search phrases / image prompt mention an entity's CATEGORY (e.g. "passenger jet", "wing", "SUV")
   is locked to that entity - not only shots that name it. Interior shots (cabin, dashboard) aren't locked, but like every other
   unlocked shot they must not show any object of a locked category, so a generic beat can't show another airline's plane.
3. recon(): the 3D reconstruction (Remotion, remotion/src/Recon.tsx) used when nothing real passes: low-poly model in the
   entity's colours, labelled, never a logo or a face."""
import json, re
from .llm import LLM

ENTITIES = """Story title: {title}

Story text:
{text}

List the identifiable real things this story is about that viewers would expect to SEE: a particular airline's aircraft, a specific
car make/model, a named ship, train, product or building, and the named people involved. At most 6. For each:
- "name": as specific as the story allows ("flydubai Boeing 737-800", "Mitsubishi Outlander Sport", "Captain (name withheld)")
- "brand": the brand/operator/maker if any ("flydubai", "Mitsubishi"), else ""
- "kind": "aircraft" | "vehicle" | "ship" | "train" | "product" | "building" | "person" | "other"
- "category_words": 4-10 lowercase words or short phrases a stock-footage search for this KIND of thing would use (for an airline's
  plane: ["plane","airplane","aircraft","jet","airliner","passenger jet","wing","runway","takeoff","landing"]; for a car: ["car",
  "suv","vehicle","driving","crossover"]). Empty for people.
- "avoid": one sentence describing ANY object of this kind as it might appear in a clip, so a checker can spot one (e.g. "the
  outside of any airliner: fuselage, wing, engine, winglet or tail, including a wing seen from a cabin window"). Empty for people.
- "colors": 3 hex colours of its real scheme [body, accent, trim/tail] if you know them (e.g. flydubai: ["#ffffff","#1b4e9b","#f26b21"]),
  else []
- "role": for people only: 2-5 words ("Captain", "First officer", "Passenger, row 13")
- "row": for people only: seat row number if the story gives one, else null
Only things actually in the story. Reply with ONLY JSON: {{"entities": [ ... ]}}"""

KINDS = ("aircraft", "vehicle", "ship", "train", "product", "building", "person", "other")
# safety net: common category words per kind, added to what the script AI gives
BASE_WORDS = {
    "aircraft": ["plane", "airplane", "aeroplane", "aircraft", "jet", "jetliner", "airliner", "boeing", "airbus", "wing", "winglet",
                 "fuselage", "tail fin", "runway", "takeoff", "take off", "landing", "taxiing", "flight", "flying", "airline"],
    "vehicle": ["car", "cars", "suv", "vehicle", "truck", "pickup", "sedan", "hatchback", "crossover", "driving", "road trip"],
    "ship": ["ship", "vessel", "boat", "tanker", "ferry", "cruise ship", "freighter", "yacht"],
    "train": ["train", "locomotive", "railway", "rail line", "carriage"],
}
INTERIOR = re.compile(r"\b(cabin|interior|inside|seat|seats|seated|aisle|passengers?|galley|dashboard|steering|overhead bins?|tray table|"
                      r"window seat|boarding|crew|flight attendant)\b", re.I)
EXTERIOR = re.compile(r"\b(wing|winglet|tail|fuselage|engine|runway|takeoff|take off|landing|landed|taxi\w*|tarmac|parked|exterior|"
                      r"outside|in flight|flying|sky|clouds|aerial|road|driving|highway)\b", re.I)
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

def _clean(e):
    if not isinstance(e, dict) or not str(e.get("name", "")).strip(): return None
    kind = e.get("kind") if e.get("kind") in KINDS else "other"
    words = [str(w).lower().strip() for w in (e.get("category_words") or []) if str(w).strip()][:12]
    if kind != "person": words = sorted(set(words + BASE_WORDS.get(kind, [])), key=len, reverse=True)
    cols = [c for c in (e.get("colors") or []) if isinstance(c, str) and HEX.match(c)][:3]
    row = e.get("row")
    try: row = int(row) if row not in (None, "") else None
    except Exception: row = None
    return {"name": str(e["name"]).strip()[:60], "brand": str(e.get("brand") or "").strip()[:40], "kind": kind,
            "category_words": [] if kind == "person" else words, "avoid": "" if kind == "person" else str(e.get("avoid") or "")[:220],
            "colors": cols, "role": str(e.get("role") or "")[:40], "row": row}

def entities(cfg, job, title, text, log, stop, llm=None):
    f = job / "entities.json"
    if f.exists():
        try: return json.loads(f.read_text(encoding="utf-8"))
        except Exception: pass
    def run(l):
        try: return l.chat_json("You are a precise video researcher.", ENTITIES.format(title=title, text=text[:14000]), max_tokens=2500)
        except Exception as e: log(f"  subject list failed ({str(e)[:80]}); no subject locks"); return {}
    j = run(llm) if llm else None
    if j is None:
        with LLM(cfg, log, stop) as l: j = run(l)
    out = [x for x in (_clean(e) for e in (j.get("entities") or [])) if x][:6]
    f.write_text(json.dumps(out, indent=1), encoding="utf-8")
    things = [e["name"] for e in out if e["kind"] != "person"]
    if things: log(f"  story subjects: {', '.join(things)}; every shot of that kind must show exactly that")
    return out

def _mentions(text, words):
    t = " " + re.sub(r"[^a-z0-9 ]+", " ", text.lower()) + " "
    return any(f" {w} " in t or f" {w}s " in t or f" {w}es " in t for w in words)

def assign(ents, text):
    """-> (subject or None, avoid list). subject: the entity this shot must show (dict with name/brand/kind/colors).
    avoid: descriptions of categories the clip must NOT show (for unlocked shots)."""
    things = [e for e in ents if e["kind"] != "person" and e["category_words"]]
    low = text.lower(); best, score = None, 0
    for e in things:   # the most specific match wins: a name/brand beats "fighter jet", which beats "jet"
        brand = e["brand"].lower()
        if (brand and brand in low) or e["name"].lower() in low: sc = 1000 + len(e["name"])
        else:
            hits = [w for w in e["category_words"] if _mentions(text, [w])]
            sc = max((len(w) for w in hits), default=0)
            # words that are this entity's OWN (not shared with another entity) count double
            own = [w for w in hits if not any(w in o["category_words"] for o in things if o is not e)]
            sc += 100 * bool(own)
        if sc > score: best, score = e, sc
    if best:
        sj = {"name": best["name"], "brand": best["brand"], "kind": best["kind"], "colors": best["colors"]}
        if score < 1000 and INTERIOR.search(text) and not EXTERIOR.search(text) and \
                not re.search(r"\b(jets?|planes?|airplanes?|airliners?|aircraft|cars?|suvs?|vehicles?|ships?|trains?)\b", text, re.I):
            # inside the subject (its cabin, its cockpit): stock or AI interiors would be some other airline's cabin, so this is
            # locked too and shown as the cabin/cockpit reconstruction
            sj["interior"] = True
        return sj, []
    return None, [e["avoid"] for e in things if e["avoid"]]

SCENE_WORDS = [
    ("cockpit_door", r"\b(cockpit|flight deck|pilot|captain|co-?pilot|first officer|door)\b"),
    ("cabin", r"\b(cabin|passengers?|seat|seats|aisle|row|onboard|on board|crew|attendant)\b"),
    ("aircraft_landing", r"\b(land|landing|landed|divert\w*|touch\w* down|approach)\b"),
    ("aircraft_ground", r"\b(tarmac|parked|ground|airport|gate|stairs|police|security|stand|apron|evacuat\w*|boarded|detained|disembark\w*)\b"),
]

# what moment of a flight a beat (or a photo) is about - so a parked plane isn't shown while the narration says it is diving
PHASE_WORDS = [
    ("ground", r"\b(parked|on the ground|tarmac|apron|gate|stand|disembark\w*|deplan\w*|evacuat\w*|police|detained|stairs|after (it )?landed|"
               r"after landing|on arrival|kept on board|replacement (aircraft|plane)|exit the (aircraft|plane))\b"),
    ("air", r"\b(descen\w*|dropp\w*|dive|diving|plunge\w*|altitude|feet|ft\b|signals?|squawk\w*|transponder|transmitt\w*|mid-?air|in flight|"
            r"airspace|scrambled|intercept\w*|hijack\w*|cockpit fight|radar|climb\w*|cruis\w*|crash\w*|suicide|kill (him|her)self|"
            r"over (saudi|the sea|iraq|jordan))\b"),
    ("landing", r"\b(landed|touch(ed)? down|final approach|emergency landing|made (a|an) \w* ?landing)\b"),
]

def phase(text):
    """'ground' | 'landing' | 'air' | '' (no particular moment)."""
    t = text.lower()
    for ph, rx in PHASE_WORDS:
        if re.search(rx, t): return ph
    return ""

def beat_phases(sections):
    """Moment of every beat, from its NARRATION only (search phrases are noisy). A beat with no moment of its own (reactions,
    speculation, background) inherits the moment the story is at, so a comment made after the landing doesn't show the plane
    in the air, and vice versa."""
    out, cur = {}, ""
    strong_air = re.compile(r"\b(dropped|descended|dived|plunged|transmitted|squawked|scrambled|lost altitude|took off|was flying)\b", re.I)
    for s in sections:
        ph = phase(s.get("vo", ""))
        # once the plane is on the ground, talk about what "could have" happened ("if it had crashed", "a hijacking") stays on the
        # ground; only a beat that clearly narrates an in-air event again goes back to the air
        if cur == "ground" and ph == "air" and not strong_air.search(s.get("vo", "")): ph = "ground"
        if ph: cur = ph
        out[s["id"]] = ph or cur
    return out

def phase_ok(beat_phase, photo_phase):
    """May a photo taken in photo_phase illustrate a beat about beat_phase?"""
    if not beat_phase: return True
    ok = {"air": ("air",), "landing": ("landing", "air"), "ground": ("ground", "taxi", "landing")}
    return (photo_phase or "") in ok.get(beat_phase, (photo_phase,))

NUM_WORDS = {"ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
             "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
             "ninety": 90, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9}

def _altitudes(text):
    """Altitudes in feet mentioned in the narration, in order ('30,000 feet', 'thirty thousand feet', '15-16,000 feet')."""
    out = []
    for m in re.finditer(r"(\d{1,3}(?:,\d{3})+|\d{4,5})\s*(?:-\s*\d{1,3}(?:,\d{3})?\s*)?(?:feet|ft)\b", text, re.I):
        out.append(int(m.group(1).replace(",", "")))
    for m in re.finditer(r"\b((?:twenty|thirty|forty|fifty|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
                         r"one|two|three|four|five|six|seven|eight|nine)(?:[- ](?:one|two|three|four|five|six|seven|eight|nine))?) thousand\b", text, re.I):
        out.append(sum(NUM_WORDS[w] for w in re.split(r"[- ]", m.group(1).lower())) * 1000)
    return [a for a in out if 500 <= a <= 45000]

def _squawks(text):
    t = text.lower(); out = []
    for code, rx in (("7700", r"7700|seven[- ]seven[- ]hundred|seventy[- ]seven hundred|seven seven zero zero"),
                     ("7500", r"7500|seven[- ]five[- ]hundred|seventy[- ]five hundred|seven five zero zero"),
                     ("7600", r"7600|seven[- ]six[- ]hundred|seventy[- ]six hundred|seven six zero zero")):
        m = re.search(rx, t)
        if m: out.append((m.start(), code))
    if not out and re.search(r"\b(signal|code|squawk|transponder)", t):   # named but not numbered: the standard codes
        for code, rx in (("7700", r"general emergency|emergency signal|emergency code"), ("7500", r"hijack"), ("7600", r"radio failure|lost (radio|communication)")):
            m = re.search(rx, t)
            if m: out.append((m.start(), code))
    return [c for _, c in sorted(out)]

def recon(subject, ents, text, k=0, caption="", moment=None):
    """A Recon spec (see remotion/src/Recon.tsx) for this shot. k varies the scene when a beat needs several.
    The scene follows the moment the narration describes: a descent becomes a dive with the altimeter counting down, emergency
    codes appear on a transponder readout, a cockpit attack shows the door open with an injured crew member."""
    kind = (subject or {}).get("kind")
    people = [e for e in ents if e["kind"] == "person"]
    if not subject and people: kind = "person"
    own = next((e for e in ents if e["name"] == (subject or {}).get("name")), {})
    military = bool(re.search(r"\b(f-?\d+|fighter|military|combat|stealth|bomber|air force|jet fighter)\b",
                              (subject or {}).get("name", "") + " " + " ".join(own.get("category_words", [])), re.I))
    ph = phase(text) if moment is None else moment
    alts, codes = _altitudes(text), _squawks(text)
    if kind == "aircraft":
        if military: order = ["aircraft_flight", "aircraft_flight"]
        else:
            hits = [s for s, rx in SCENE_WORDS if re.search(rx, text, re.I)]
            if ph == "air": hits = ["aircraft_flight"] + [h for h in hits if h in ("cockpit_door", "cabin")]   # in the air: never parked
            elif ph == "landing": hits = [h for h in hits if h != "aircraft_ground"] or ["aircraft_landing"]
            order = hits + [s for s in ("aircraft_flight", "aircraft_landing", "aircraft_ground") if s not in hits]
            if ph == "air":   # in the air: the aircraft in flight (and the cockpit when the beat is about the pilots)
                order = (["cockpit_door"] if re.search(r"\b(cockpit|flight deck|pilots?|captain|co-?pilot|first officer)\b", text, re.I) else []) + ["aircraft_flight"]
            if ph == "ground": order = ["aircraft_ground"] + [o for o in order if o != "aircraft_ground"]
            if (subject or {}).get("interior"):   # a shot inside the aircraft: cabin / cockpit only
                order = [h for h in hits if h in ("cockpit_door", "cabin")] or ["cabin", "cockpit_door"]
        scene = order[k % len(order)]
    elif kind in ("vehicle",): scene = "vehicle_road"
    elif kind == "person": scene = "people"
    else: scene = "object"
    g = {"kind": "recon", "scene": scene, "name": (subject or {}).get("name", ""), "colors": (subject or {}).get("colors") or [],
         "caption": caption[:40]}
    if military: g["model"] = "fighter"; g["colors"] = []
    if scene == "aircraft_flight":
        # attitude from the narration: descending -> dive, climbing -> climb, a struggle/loss of control -> unstable, else level
        if re.search(r"\b(descen\w*|dropp\w*|dive|diving|plunge\w*|nosedive\w*|lost altitude|losing altitude)\b", text, re.I) or len(alts) >= 2:
            g["motion"] = "dive" if k % 2 == 0 else "unstable"
        elif re.search(r"\b(fight\w*|fought|struggl\w*|turbulen\w*|erratic\w*|shook|shaking|lurch\w*|unstable|out of control|wrestl\w*|grabb\w*)\b", text, re.I):
            g["motion"] = "unstable"
        elif re.search(r"\b(climb\w*|took off|taking off|gained altitude|ascend\w*)\b", text, re.I):
            g["motion"] = "climb"
        else:
            g["motion"] = "cruise"
        if len(alts) >= 2: g["altitude"] = [max(alts[0], alts[1]), min(alts[0], alts[1])] if g.get("motion") == "dive" else alts[:2]
        if codes: g["squawk"] = codes[:3]
    named = [p for p in people if p["name"].split()[0].lower() in text.lower() or (p["role"] and p["role"].split(",")[0].lower() in text.lower())]
    if scene == "cabin":
        seated = [p for p in (named or people) if p["row"]][:3]
        g["labels"] = [{"text": p["name"][:26], "sub": p["role"] or f"Row {p['row']}", "row": p["row"], "seat": 2 + i} for i, p in enumerate(seated)]
    elif scene == "people":
        ppl = (named or people)[:5]
        g["labels"] = [{"text": p["role"] or p["name"], "sub": p["name"] if p["role"] else ""} for p in ppl]
        g["people"] = max(1, len(ppl)); g["name"] = ""
    elif scene == "cockpit_door":
        g["labels"] = []
        if re.search(r"\b(blood\w*|injur\w*|stab\w*|attack\w*|wound\w*|kill\w*|door (was )?open\w*|opened)\b", text, re.I): g["door"] = "open"
    return g
