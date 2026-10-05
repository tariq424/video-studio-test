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
        if score < 1000 and INTERIOR.search(text) and not EXTERIOR.search(text):
            return None, [e["avoid"] for e in things if e["avoid"]]   # interior shot: no lock, but no exterior of such objects
        return {"name": best["name"], "brand": best["brand"], "kind": best["kind"], "colors": best["colors"]}, []
    return None, [e["avoid"] for e in things if e["avoid"]]

SCENE_WORDS = [
    ("cockpit_door", r"\b(cockpit|flight deck|pilot|captain|co-?pilot|first officer|door)\b"),
    ("cabin", r"\b(cabin|passengers?|seat|seats|aisle|row|onboard|on board|crew|attendant)\b"),
    ("aircraft_landing", r"\b(land|landing|landed|divert\w*|touch\w* down|approach|emergency)\b"),
    ("aircraft_ground", r"\b(tarmac|parked|ground|airport|gate|stairs|police|security|stand|apron|evacuat\w*|boarded|detained)\b"),
]

def recon(subject, ents, text, k=0, caption=""):
    """A Recon spec (see remotion/src/Recon.tsx) for this shot. k varies the scene when a beat needs several."""
    kind = (subject or {}).get("kind")
    people = [e for e in ents if e["kind"] == "person"]
    if not subject and people: kind = "person"
    military = re.search(r"\b(f-?\d+|fighter|military|combat|stealth|bomber|air force|jet fighter|drone|helicopter)\b",
                         ((subject or {}).get("name", "") + " " + " ".join(next((e["category_words"] for e in ents if e["name"] == (subject or {}).get("name")), []))), re.I)
    if kind == "aircraft" and military:
        # the 3D kit only has an airliner model; drawing a fighter as an airliner would be wrong, so a headline card instead
        w = text.split()
        return {"kind": "headline", "kicker": (subject or {}).get("name", "")[:30], "text": caption or " ".join(w[:9]).rstrip(",.;") + ("..." if len(w) > 9 else ""), "sub": ""}
    if kind == "aircraft":
        hits = [s for s, rx in SCENE_WORDS if re.search(rx, text, re.I)]
        order = hits + [s for s in ("aircraft_flight", "aircraft_landing", "aircraft_ground") if s not in hits]
        scene = order[k % len(order)]
    elif kind in ("vehicle",): scene = "vehicle_road"
    elif kind == "person": scene = "people"
    else: scene = "object"
    g = {"kind": "recon", "scene": scene, "name": (subject or {}).get("name", ""), "colors": (subject or {}).get("colors") or [],
         "caption": caption[:40]}
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
    return g
