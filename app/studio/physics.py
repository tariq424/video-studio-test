"""Physics / data simulations for a beat (pause chat: "simulate the descent using real physics").

Registry of small modules with one interface:   run(params: dict) -> {"title", "unit", "series": [[t_seconds, value], ...],
"icon", "label", "notes"}   (a time series; the renderer doesn't care which module made it). The chat's router (debug.chat,
DeepSeek) picks the module and fills the parameters from the narration; the result becomes a `sim` graphic (Remotion
Sim.tsx: an animated profile with the subject riding the curve and a live readout), offered as a candidate for the beat.

Implemented (pure Python, no packages, no network):
  aircraft_flight     altitude profile: cruise -> descent at a computed rate (or the narration's start/end altitudes and duration)
                      -> optional level-off; ft vs s. Real ADS-B (OpenSky) is NOT wired: its history API needs an account.
  submarine_descent   depth vs time at a sink rate, with the hull pressure p = rho*g*h shown (crush depth marked if given)
  weather_event       hurricane / tropical storm / cyclone track on a map (Sim.tsx SimMapBackdrop, kind "simmap"). Data, in order:
                      NOAA NHC CurrentStorms.json + that storm's forecast advisory (active storms: forecast points, so a cone),
                      NOAA HURDAT2 best tracks (past Atlantic / NE Pacific storms, by name + year; cached under <studio>/cache/noaa),
                      else the points the narration gives. Cone = circles of an approximate NHC average track error per
                      forecast hour (labelled approximate), joined along the track.
  ship_route          vessel path through the narration's waypoints (ports / straits with coordinates) with a vessel marker;
                      AIS: with "aisstream_api_key" and an MMSI, the vessel's live position (aisstream.io, ~20 s) is added as
                      the last point. Historical AIS tracks are not wired (no free source).
Stubs (return None -> the beat falls to the next rung): vehicle_crash, structural_collapse, earthquake - deliberately not built.
Adding one = one function here + its name in MODULES (+ a ROUTES entry so the v2 ladder can pick it).
route(sec) (visual ladder v2, rung 6) picks a module ONLY when the beat's subject matches one; fill() takes its parameters from the
narration (one small JSON call; regex defaults without a model).
Compute strategy: every series is downsampled to <= 240 points and the timeline is compressed into the beat's length."""
import json, math, re, time
from pathlib import Path

G, RHO_SEA = 9.81, 1025.0
KT_MPH = 1.15078
CACHE = Path(__file__).resolve().parent.parent.parent / "cache" / "noaa"
UA = {"User-Agent": "VideoStudio/1.0 (local news-video tool)"}


def _down(series, n=240):
    if len(series) <= n: return series
    k = len(series) / n
    return [series[int(i * k)] for i in range(n)] + [series[-1]]


def aircraft_flight(p):
    drop = float(p.get("drop_ft") or 0); assumed = ""
    start = float(p.get("start_alt_ft") or 0)
    end = None if p.get("end_alt_ft") in (None, "") else float(p["end_alt_ft"])   # 0 only when given (a crash / landing)
    if drop:   # "lost 12,000 feet": the narration often gives the drop, not the altitudes
        if start and end is None: end = start - drop
        elif end is not None and not start: start = end + drop
        elif not start: start = 35000.0; end = start - drop; assumed = "start assumed at a 35,000 ft cruise; "
    start = start or 35000.0; end = end if end is not None else 10000.0
    dur = float(p.get("descent_secs") or 0)
    rate = float(p.get("rate_fpm") or 0)   # feet per minute
    if not dur: dur = abs(start - end) / (rate or 6000) * 60
    cruise = float(p.get("cruise_secs") or max(10.0, dur * 0.25)); after = float(p.get("level_secs") or max(10.0, dur * 0.25))
    series, t = [], 0.0
    step = max(0.5, (cruise + dur + after) / 400)
    while t <= cruise + dur + after:
        if t < cruise: alt = start
        elif t < cruise + dur:
            x = (t - cruise) / dur; alt = start + (end - start) * (0.5 - 0.5 * math.cos(math.pi * x))   # smooth push-over / level-off
        else: alt = end
        series.append([round(t, 2), round(alt)]); t += step
    fpm = abs(start - end) / dur * 60 if dur else 0
    return {"title": p.get("title") or "Altitude", "unit": "ft", "series": _down(series), "icon": "plane", "livery": p.get("livery"),
            "label": p.get("label") or f"{start:,.0f} ft -> {end:,.0f} ft in {dur:.0f} s", "notes": f"{assumed}average {'descent' if end < start else 'climb'} {fpm:,.0f} ft/min",
            "marks": [{"t": cruise, "text": "descent begins"}, {"t": cruise + dur, "text": "levels off"}]}


def submarine_descent(p):
    depth = float(p.get("max_depth_m") or 3800); rate = float(p.get("sink_mps") or 1.0); crush = p.get("crush_depth_m")
    dur = depth / max(rate, 0.05); series, t = [], 0.0; step = max(1.0, dur / 400)
    while t <= dur:
        series.append([round(t, 1), round(-rate * t, 1)]); t += step
    pmax = RHO_SEA * G * depth / 1e5   # bar
    marks = [{"t": dur, "text": f"{depth:,.0f} m · {pmax:,.0f} bar"}]
    if crush: marks.insert(0, {"t": float(crush) / max(rate, 0.05), "text": f"crush depth {float(crush):,.0f} m"})
    return {"title": p.get("title") or "Depth", "unit": "m", "series": _down(series), "icon": "sub",
            "label": p.get("label") or f"to {depth:,.0f} m at {rate:g} m/s", "notes": f"pressure at the bottom: {pmax:,.0f} bar (p = rho*g*h)",
            "marks": marks}


# ---------------------------------------------------------------- weather_event (NOAA)
# Approximate NHC cone radii (nautical miles) by forecast hour: the cone is drawn so ~2/3 of historical official-forecast errors
# fall inside it. NHC updates these every season; these are rounded recent Atlantic values - the graphic says "approximate".
CONE_NM = [(0, 0), (12, 26), (24, 40), (36, 54), (48, 68), (60, 84), (72, 100), (96, 140), (120, 200)]


def _cone_km(h):
    for (h0, r0), (h1, r1) in zip(CONE_NM, CONE_NM[1:]):
        if h <= h1: return (r0 + (r1 - r0) * (h - h0) / (h1 - h0 or 1)) * 1.852
    return CONE_NM[-1][1] * 1.852


def _get(url, timeout=25):
    import requests
    r = requests.get(url, headers=UA, timeout=timeout); r.raise_for_status(); return r


def _ll(lat, lon):
    """'25.3N', '80.1W' -> (25.3, -80.1)"""
    a = float(lat[:-1]) * (-1 if lat[-1] in "Ss" else 1); b = float(lon[:-1]) * (-1 if lon[-1] in "Ww" else 1)
    return a, b


def _hurdat_files():
    """The latest HURDAT2 files (Atlantic, NE + central Pacific), cached for 30 days."""
    CACHE.mkdir(parents=True, exist_ok=True); out = []
    for basin, rx in (("atl", r'href="(hurdat2-1851-\d{4}-\d+\.txt)"'), ("pac", r'href="(hurdat2-nepac-1949-\d{4}-\d+\.txt)"')):
        have = sorted(CACHE.glob(f"hurdat_{basin}_*.txt"))
        if have and time.time() - have[-1].stat().st_mtime < 30 * 86400: out.append(have[-1]); continue
        try:
            names = sorted(re.findall(rx, _get("https://www.nhc.noaa.gov/data/hurdat/").text))
            if names:
                f = CACHE / f"hurdat_{basin}_{names[-1]}"; f.write_text(_get("https://www.nhc.noaa.gov/data/hurdat/" + names[-1], 60).text, encoding="utf-8")
                out.append(f); continue
        except Exception: pass
        if have: out.append(have[-1])
    return out


def _hurdat_track(name, year):
    """Best track of storm `name` in `year` -> [{"lat","lon","label","v","wind_kt"}] (6-hourly), or []."""
    name = str(name or "").strip().upper(); year = str(year or "").strip()
    if not name: return []
    for f in _hurdat_files():
        lines = f.read_text(encoding="utf-8").splitlines(); i = 0
        while i < len(lines):
            h = [x.strip() for x in lines[i].split(",")]
            if len(h) >= 3 and re.fullmatch(r"[A-Z]{2}\d{6}", h[0] or ""):
                n = int(h[2] or 0)
                if h[1] == name and (not year or h[0][-4:] == year):
                    pts = []
                    for ln in lines[i + 1:i + 1 + n]:
                        c = [x.strip() for x in ln.split(",")]
                        try: la, lo = _ll(c[4], c[5]); kt = int(c[6])
                        except Exception: continue
                        pts.append({"lat": la, "lon": lo, "wind_kt": kt, "v": f"{round(kt * KT_MPH / 5) * 5} mph", "date": c[0], "rec": c[2], "status": c[3]})
                    return pts
                i += n + 1
            else: i += 1
    return []


def _active_storm(name):
    """An active NHC storm by name -> (current track points, forecast points with hours) or None."""
    try: cs = _get("https://www.nhc.noaa.gov/CurrentStorms.json").json()
    except Exception: return None
    st = next((s for s in cs.get("activeStorms", []) if str(s.get("name", "")).upper() == str(name or "").upper()), None)
    if not st: return None
    try: cur = {"lat": float(st["latitudeNumeric"]), "lon": float(st["longitudeNumeric"]), "label": "now",
                "v": f"{round(float(st.get('intensity') or 0) * KT_MPH / 5) * 5} mph"}
    except Exception: return None
    fc = []
    url = ((st.get("forecastAdvisory") or {}).get("url"))
    if url:
        try:
            txt = _get(url).text
            for m in re.finditer(r"(FORECAST|OUTLOOK) VALID\s+(\d{2})/(\d{4})Z\s+(\d+\.\d+[NS])\s+(\d+\.\d+[EW])(?:.*?MAX WIND\s+(\d+)\s*KT)?", txt, re.S):
                la, lo = _ll(m.group(4), m.group(5)); fc.append({"lat": la, "lon": lo, "kt": int(m.group(6) or 0)})
        except Exception: pass
    hours = [12, 24, 36, 48, 60, 72, 96, 120]
    for k, p in enumerate(fc[:len(hours)]): p["h"] = hours[k]
    return [cur], fc[:len(hours)]


def weather_event(p):
    name = str(p.get("storm_name") or p.get("name") or "").strip(); year = p.get("year")
    track, fc, src = [], [], ""
    act = _active_storm(name) if name else None
    if act: track, fc = act; src = "NOAA NHC (active storm, latest advisory)"
    if not track and name:
        bt = _hurdat_track(name, year)
        if bt:
            track = bt; src = f"NOAA HURDAT2 best track{f' ({year})' if year else ''}"
            peak = max(bt, key=lambda x: x["wind_kt"])
            for x in bt:   # label the start, landfalls and the peak (not every 6-hour point)
                if x is bt[0]: x["label"] = x["date"][4:6] + "/" + x["date"][6:]
                elif x.get("rec") == "L": x["label"] = "landfall"
                elif x is peak: x["label"] = f"peak {x['v']}"
    if not track:   # the narration's own points
        for q in p.get("points") or []:
            try: track.append({"lat": float(q["lat"]), "lon": float(q["lon"]), "label": str(q.get("label") or q.get("name") or "")[:18],
                               "v": f"{q['wind_mph']} mph" if q.get("wind_mph") else ""})
            except Exception: pass
        src = "positions from the narration" if track else ""
        for q in p.get("forecast") or []:
            try: fc.append({"lat": float(q["lat"]), "lon": float(q["lon"]), "h": float(q.get("hours") or 24 * (len(fc) + 1))})
            except Exception: pass
    if len(track) + len(fc) < 2:
        return synthetic_motion({"vo": p.get("_context") or "Storm moving across the ocean"})
    if len(track) > 60: k = len(track) / 60; track = [track[int(i * k)] for i in range(60)] + [track[-1]]
    fpts = [{"lat": q["lat"], "lon": q["lon"], "r_km": round(_cone_km(q.get("h", 24))), "label": f"+{int(q.get('h', 0))}h" if q.get("h") in (24, 72, 120) else ""} for q in fc]
    if len(track) < 2 and len(fpts) >= 1: track = track + [{"lat": fpts[0]["lat"], "lon": fpts[0]["lon"], "label": ""}]
    title = p.get("title") or (f"{p.get('kind_word') or 'Storm'} {name.title()}".strip() if name else "Storm track")
    return {"kind": "simmap", "module": "weather_event", "title": title, "label": p.get("label") or src, "icon": "storm",
            "track": [{k: v for k, v in x.items() if k in ("lat", "lon", "label", "v")} for x in track], "forecast": fpts,
            "notes": ("cone: approximate NHC average track error" if fpts else "") + (f" · {src}" if src and fpts else ""), "source": src}


# ---------------------------------------------------------------- ship_route
def _ais_position(key, mmsi, wait=20):
    """Live position of one vessel from aisstream.io (free key) -> {"lat","lon","name"} or None. Needs websocket-client."""
    try: import websocket   # websocket-client
    except Exception: return None
    try:
        ws = websocket.create_connection("wss://stream.aisstream.io/v0/stream", timeout=wait)
        ws.send(json.dumps({"APIKey": key, "BoundingBoxes": [[[-90, -180], [90, 180]]], "FiltersShipMMSI": [str(mmsi)],
                            "FilterMessageTypes": ["PositionReport"]}))
        t0 = time.time()
        while time.time() - t0 < wait:
            m = json.loads(ws.recv()); md = m.get("MetaData") or {}
            if md.get("latitude") is not None:
                ws.close(); return {"lat": float(md["latitude"]), "lon": float(md["longitude"]), "name": str(md.get("ShipName") or "").strip()}
        ws.close()
    except Exception: return None
    return None


def ship_route(p, cfg=None):
    wps = []
    for q in p.get("waypoints") or p.get("points") or []:
        try: wps.append({"lat": float(q["lat"]), "lon": float(q["lon"]), "name": str(q.get("name") or "")[:22]})
        except Exception: pass
    src = "route from the narration"
    key = (cfg or {}).get("aisstream_api_key"); mmsi = re.sub(r"\D", "", str(p.get("mmsi") or ""))
    if key and len(mmsi) == 9:
        pos = _ais_position(key, mmsi)
        if pos: wps.append({"lat": pos["lat"], "lon": pos["lon"], "name": "AIS: now"}); src = "route from the narration + live AIS position (aisstream.io)"
    if len(wps) < 2:
        return synthetic_motion({"vo": p.get("_context") or "Ships moving along a shipping route"})
    track = []   # densify each leg so the vessel glides (straight in Mercator: the waypoints carry the real path round land)
    for a, b in zip(wps, wps[1:]):
        for i in range(12): k = i / 12; track.append({"lat": a["lat"] + (b["lat"] - a["lat"]) * k, "lon": a["lon"] + (b["lon"] - a["lon"]) * k})
    track.append({"lat": wps[-1]["lat"], "lon": wps[-1]["lon"]})
    km = sum(_hav(a, b) for a, b in zip(wps, wps[1:]))
    vessel = str(p.get("vessel") or "").strip()
    return {"kind": "simmap", "module": "ship_route", "title": p.get("title") or (vessel or "Vessel route"), "icon": "ship",
            "label": p.get("label") or f"{km:,.0f} km · {km / 1.852:,.0f} nautical miles", "track": track,
            "places": [w for w in wps if w["name"]], "notes": src, "source": src}


def _hav(a, b):
    r = 6371.0; la1, la2 = math.radians(a["lat"]), math.radians(b["lat"]); dl = math.radians(b["lon"] - a["lon"])
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _not_built(name):
    return lambda p: None


MODULES = {
    "aircraft_flight": (aircraft_flight, "plane altitude / descent / climb profile. params: drop_ft (feet lost, when the narration says 'lost/dropped/descended N feet'), start_alt_ft and end_alt_ft (only altitudes the narration states; a take-off starts at 0, a crash ends at 0), descent_secs (how long it took), rate_fpm, title (2-4 words, e.g. 'Sudden descent'), label"),
    "submarine_descent": (submarine_descent, "submarine dive to depth with pressure. params: max_depth_m, sink_mps, crush_depth_m, title, label"),
    "vehicle_crash": (_not_built("vehicle_crash"), "car crash (not built yet)"),
    "structural_collapse": (_not_built("structural_collapse"), "building collapse (not built yet)"),
    "earthquake": (_not_built("earthquake"), "seismic event (not built yet)"),
    "ship_route": (ship_route, "vessel path on a map. params: waypoints [{name, lat, lon}] (ports / straits in order, real coordinates in decimal degrees; add waypoints so the path stays at sea), vessel (name), mmsi (9 digits, only if the narration gives it), title, label"),
    "radar_sweep": (lambda p: synthetic_motion({"vo": "Radar sweeps across the weather panel"}), "Illustrative radar sweep; synthetic angles, not live radar observations."),
    "weather_event": (weather_event, "hurricane / tropical storm / cyclone track with an uncertainty cone (NOAA data). params: storm_name, year, kind_word (Hurricane / Typhoon / Cyclone / Tropical Storm), points [{lat, lon, label, wind_mph}] and forecast [{lat, lon, hours}] only when the narration gives positions, title, label"),
}

# v2 ladder (rung 6): a module only when the beat's subject matches it - never speculatively
ROUTES = [
    ("radar_sweep", r"\bradar\b", None),
    ("weather_event", r"\b(hurricanes?|typhoons?|cyclones?|tropical (storm|depression)s?|storm surge|landfall|eye ?wall)\b", None),
    ("submarine_descent", r"\b(submarines?|submersibles?|sub)\b", r"\b(depth|deep|feet|metres?|meters?|dive|dived|descen\w*|sank|sinking|implo\w*|crush\w*)\b"),
    ("aircraft_flight", None, r"\b(feet|altitude|descen\w*|dropp?\w*|plung\w*|plummet\w*|dive|dove|diving|climb\w*|lost height|nosedive\w*|"
                              r"took off|taking off|takes? off|crash(ed|es|ing)?)\b"),
    ("ship_route", r"\b(ships?|vessels?|tankers?|freighters?|cargo ship|container ship|bulk carrier|ferr(y|ies)|warships?|frigates?|destroyers?|"
                   r"aircraft carriers?|cruise ships?|supertankers?|LNG carrier)\b", r"\b(sail\w*|route|voyage|strait|canal|port|harbou?r|bound for|"
                   r"heading|en route|diverted|transit\w*|crossed|shipping lane|seized|hijack\w*|anchored|docked)\b"),
]


# ---------------------------------------------------------------- action beats (ladder v2: animation before stills)
# A beat that describes an ACTION (something moving / changing) must be shown moving: a still photo of the subject with a slow zoom
# contradicts "the plane plunged 15,000 feet". action(sec) -> (verb, module or None). The verb list is deliberately physical;
# "the market crashed" has no aircraft / vessel and gets no module (it still counts as action: graphics / animated illustration).
ACTION = (r"\b(descen(d|ds|ded|ding|t)|dove|dive[ds]?|diving|nose-?div\w*|plung\w*|plummet\w*|dropp(ed|ing)|fell|falling|"
          r"climb(ed|s|ing)?|took off|takes? off|taking off|lift(ed)? off|crash(ed|es|ing)?|sank|sinks?|sinking|implod\w*|"
          r"explod\w*|blew up|swerv\w*|roll(ed|ing)|bank(ed|ing)|veer\w*|spiral\w*|lost (altitude|height|\d[\d,]* feet)|"
          r"capsiz\w*|collid\w*|slammed|tumbl\w*)\b")


# Actions of people and events (owner, 2026-11-07: a beat that narrates one is shown moving - stock, source, or Meta/Flow video -
# rather than as a still). Kept apart from ACTION, which drives the physics modules.
EVENT_ACTION = (r"\b(storm(ed|ing)|march(ed|ing)|fled|flee(ing|s)?|chas(ed|ing)|rac(ed|ing) (to|toward|through|across)|"
                r"charg(ed|ing) (at|into|toward)|stampede\w*|riot(ed|ing)|clash(ed|ing)|fought|brawl\w*|punch(ed|ing)|"
                r"set (\w+ )?(on )?fire|burn(ed|ing|t) (down|through)|went up in flames|erupt(ed|ing)|flood(ed|ing)|"
                r"collaps(ed|ing)|toppl(ed|ing)|bomb(ed|ing)|shell(ed|ing)|fired (missiles?|rockets?|shots?)|launch(ed|ing) (a |an )?"
                r"(missile|rocket|strike|attack|raid|drone)s?|struck|rammed|swarm(ed|ing)|evacuat(ed|ing)|rescu(ed|ing)|"
                r"dragg(ed|ing)|tore down|bulldoz(ed|ing)|demolish(ed|ing))\b")
_HYPO = (r"\b(tried|attempt\w*|threaten\w*|nearly|almost|would|could|might|may|plan\w*|want\w*|feared|risk\w*|thought|believed|"
         r"expected|stopped|prevent\w*|avert\w*|avoid\w*|no)( to)?\s+(\w+\s+)?$")


def event_action(text):
    """-> the event action an actual sentence of the narration describes (not a hypothetical), or ""."""
    vo = str(text or "")
    m = next((x for x in re.finditer(EVENT_ACTION, vo, re.I) if not re.search(_HYPO, vo[max(0, x.start() - 30):x.start()], re.I)), None)
    return m.group(0) if m else ""


def action(sec, text=None):
    """-> (verb, module) for a beat whose narration describes an action, else ("", None). module: the physics module that can
    animate it (aircraft_flight / submarine_descent / weather_event / ship_route), or None (no module fits)."""
    vo = text if text is not None else sec.get("vo", "")
    m = next((x for x in re.finditer(ACTION, vo, re.I)   # "tried to crash", "nearly sank", "could explode": not an action that happened
              if not re.search(r"\b(tried|attempt\w*|threaten\w*|nearly|almost|would|could|might|may|plan\w*|want\w*|feared|risk\w*|"
                               r"thought|believed|expected|stopped|prevent\w*|avert\w*|avoid\w*|no)( to)?\s+(\w+\s+)?$",
                               vo[max(0, x.start() - 30):x.start()], re.I)), None)
    mod = route({**sec, "vo": vo})
    if mod == "aircraft_flight" and not m: mod = None   # "feet" / "altitude" talk alone isn't an action to animate
    if not m and mod not in ("weather_event", "ship_route", "radar_sweep"): return "", None   # a storm track / voyage is motion by itself
    return (m.group(0) if m else mod), mod


def slot_text(vo, pos, pad=6):
    """The words visual slot i of n plays over (slots split the narration about evenly), +pad words of context; pos None -> all."""
    if not pos or not pos[1] or pos[1] <= 1: return vo
    w = vo.split(); i, n = pos; a, b = int(len(w) * i / n), int(len(w) * (i + 1) / n)
    return " ".join(w[max(0, a - pad):min(len(w), b + pad)])


def route(sec):
    """-> module name for this beat, or None. aircraft_flight only for an aircraft subject (or aircraft words) with altitude talk."""
    vo = sec.get("vo", ""); subj = sec.get("subject") or {}
    for mod, subject_rx, action_rx in ROUTES:
        if mod == "aircraft_flight":
            aero = subj.get("kind") == "aircraft" or re.search(r"\b(planes?|jets?|aircraft|airliners?|flights?)\b", vo, re.I)
            if aero and re.search(action_rx, vo, re.I): return mod
            continue
        if subject_rx and not re.search(subject_rx, vo + " " + str(subj.get("name", "")), re.I): continue
        if action_rx and not re.search(action_rx, vo, re.I): continue
        return mod
    return None


FILL = """A news video shows a data simulation for this beat. Narration: "{vo}"
Module: {mod} - {desc}
Fill its parameters ONLY from facts in the narration (or well-known facts it names, like a storm's name and year, a port's coordinates).
Leave out anything not given. Numbers as plain numbers. Reply with ONLY JSON: {{"params": {{...}}}}"""


def fill(cfg, mod, sec, log):
    """Parameters for module `mod` from the narration: one small JSON call (script provider); regex defaults without a model.
    aircraft_flight also gets the airline livery the narration / subject names (liveries.pick; None = generic airliner)."""
    p = {} if mod == "radar_sweep" else _fill(cfg, mod, sec, log)
    if mod == "aircraft_flight":
        from . import liveries
        sj = sec.get("subject") or {}
        p["livery"] = liveries.pick(sec.get("vo", ""), f"{sj.get('name', '')} {sj.get('brand', '')}", sec.get("_story", ""))
        if not p.get("drop_ft") and not p.get("start_alt_ft"):   # no model: "from 30,000 feet to 15,000 feet" / "descended 15,000 feet"
            vo = sec.get("vo", "")
            m = re.search(r"\bfrom\b(.{1,60}?\b(?:feet|ft))\s+(?:down |up )?to\b(.{1,60}?\b(?:feet|ft))", vo, re.I)
            a, b = (_feet(m.group(1)), _feet(m.group(2))) if m else (None, None)
            if a and b is not None: p["start_alt_ft"], p["end_alt_ft"] = a, b
            else:
                ft = _feet(vo)
                if ft: p["drop_ft"] = ft
    p["_context"] = sec.get("vo", "")
    return p


_NUM = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
                                       "sixteen seventeen eighteen nineteen".split())}
_NUM.update({w: 10 * (i + 2) for i, w in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split())})

def _feet(vo):
    """First "N feet" in the narration, digits or words ("fifteen thousand feet", "twelve thousand five hundred feet") -> float."""
    m = re.search(r"([\d,]{3,7})\s*(feet|ft)\b", vo, re.I)
    if m: return float(m.group(1).replace(",", ""))
    m = re.search(r"((?:(?:%s|hundred|thousand|and)[\s-]+)+)(feet|ft)\b" % "|".join(_NUM), vo, re.I)
    if not m: return None
    total = cur = 0
    for w in re.split(r"[\s-]+", m.group(1).lower().strip()):
        if w in _NUM: cur += _NUM[w]
        elif w == "hundred": cur *= 100
        elif w == "thousand": total += cur * 1000; cur = 0
    return float(total + cur) or None


def _fill(cfg, mod, sec, log):
    from .llm import LLM
    c = dict(cfg)
    if c.get("script_provider") == "claude" and not c.get("anthropic_api_key"): c["script_provider"] = "deepseek" if c.get("deepseek_api_key") else "local"
    try:
        with LLM(c, log, lambda: False) as llm:
            j = llm.chat_json("You extract numbers and places for simulations. Reply with JSON only.",
                              FILL.format(vo=sec.get("vo", "")[:700].replace('"', "'"), mod=mod, desc=MODULES[mod][1]), max_tokens=700)
        return j.get("params") or {}
    except Exception as e:
        log(f"  physics: parameter model unavailable ({str(e)[:80]}); defaults from the narration")
    vo = sec.get("vo", "")
    if mod == "weather_event":
        m = re.search(r"\b(?:hurricane|typhoon|cyclone|tropical storm)\s+([A-Z][a-z]+)", vo); y = re.search(r"\b(19|20)\d{2}\b", vo)
        return {"storm_name": m.group(1) if m else "", "year": y.group(0) if y else ""}
    return {}


def describe():
    return "\n".join(f"- {k}: {v[1]}" for k, v in MODULES.items())


def run(module, params, cfg=None):
    """-> a `sim` (time series) or `simmap` (track on a map) graphic spec for Remotion, or None (unknown / stub / bad parameters)."""
    if module not in MODULES: return None
    fn = MODULES[module][0]
    try: r = fn(params or {}, cfg) if module == "ship_route" else fn(params or {})
    except Exception:
        if module in ("ship_route", "weather_event", "radar_sweep"):
            context = (params or {}).get("_context") or {"ship_route": "Ships moving on a route", "weather_event": "Storm moving across the ocean", "radar_sweep": "Radar sweep"}[module]
            return synthetic_motion({"vo": context})
        return None
    if not r: return None
    if r.get("kind") == "motion": return r
    if r.get("kind") == "simmap": return r if len(r.get("track") or []) >= 2 else None
    if len(r.get("series") or []) < 2: return None
    return {"kind": "sim", "module": module, **r}


# Physics only models things that physically move. A beat about a laptop, an app, an AI model or a website gets no
# physics (a schematic path for a MacBook is meaningless), unless it also names a real moving thing (a car, a storm...).
REAL_MOVERS = (r"\b(drones?|jets?|aircraft|airplanes?|planes?|airliners?|flights?|helicopters?|ships?|vessels?|boats?|tankers?|submarines?|"
               r"missiles?|rockets?|spacecraft|satellites?|troops|convoys?|cars?|trucks?|vehicles?|evs?|buses|trains?|bikes?|"
               r"storms?|hurricanes?|typhoons?|cyclones?|tornado\w*|winds?|rivers?|floods?|waves?|ocean|tides?|lava|wildfires?|"
               r"radars?|balls?|fluids?|particles?|projectiles?|bullets?|asteroids?|comets?|planets?|orbits?)\b")
NON_PHYSICAL = (r"\b(mac ?books?|macbook\w*|laptops?|notebooks?|computers?|pcs?|desktops?|macs?|imacs?|ipads?|iphones?|phones?|smartphones?|"
                r"tablets?|screens?|monitors?|keyboards?|software|apps?|applications?|websites?|web|browsers?|windows|macos|ios|android|"
                r"ai|chatgpt|gpt\w*|gemini|claude|llms?|models?|chatbots?|prompts?|apis?|code|coding|cloud|servers?|chips?|processors?|"
                r"[cgt]pus?|algorithms?|data|databases?|online|internet|pinterest|youtube|tiktok|instagram|feature|updates?|ocr|"
                r"text|images?|photos?|pixels?|files?|downloads?|uploads?|tokens?|stocks?|shares|markets?|prices?|revenue)\b")


def non_physical(sec, text=None):
    """-> the non-physical thing the beat is about (e.g. "MacBook"), or "" when physics may model it."""
    text = str(text if text is not None else sec.get("vo") or "")
    subj = sec.get("subject") or {}
    name = " ".join(str(subj.get(k) or "") for k in ("name", "brand"))
    if re.search(REAL_MOVERS, text, re.I) or re.search(REAL_MOVERS, name, re.I):
        return ""
    m = re.search(NON_PHYSICAL, name, re.I) or re.search(NON_PHYSICAL, text, re.I)
    if m: return (subj.get("name") if re.search(NON_PHYSICAL, name, re.I) else m.group(0)) or m.group(0)
    if str(subj.get("kind") or "").lower() in ("software", "app", "website", "company", "ai model", "model", "service"):
        return str(subj.get("name") or subj.get("kind"))
    return ""


# ---------------------------------------------------------------- synthetic profiles (2026-11-06)
# When no module has real data, the beat still gets REAL PHYSICS on SYNTHETIC DATA: a small law of motion (travel, braking,
# free fall with drag, launch, rising water, strengthening storm) driven by the narration's own numbers, with typical values for
# that kind of object filling the gaps (listed as "assumed" on screen). Drawn by Sim.tsx like the aircraft / submarine profiles,
# labelled SYNTHETIC. Replaces the old `physical_flow` schematic (a fixed sine wave that ignored the narration).
# kind -> (typical cruise speed km/h, icon)
MOVERS = [
    (r"\b(trains?|railway|rail)\b", "train", 120, "train"), (r"\b(trucks?|lorr(y|ies)|convoys?)\b", "truck", 80, "car"),
    (r"\b(cars?|vehicles?|evs?|buses|taxis?)\b", "car", 100, "car"), (r"\b(bikes?|bicycles?|cyclists?)\b", "bike", 25, "dot"),
    (r"\b(ships?|vessels?|tankers?|freighters?|ferr(y|ies)|boats?|cargo)\b", "ship", 26, "ship"),   # ~14 kn
    (r"\b(troops|soldiers|marchers|people|crowds?)\b", "troops", 5, "dot"),
    (r"\b(drones?)\b", "drone", 120, "dot"), (r"\b(helicopters?)\b", "helicopter", 250, "plane"),
    (r"\b(jets?|aircraft|airplanes?|planes?|airliners?|flights?)\b", "aircraft", 850, "plane"),
]
LAUNCH = r"\b(rockets?|missiles?|spacecraft|launch\w*|lift(ed)? off|blast(ed)? off)\b"
FALL = r"\b(fell|falls?|falling|dropp(ed|ing)|plung\w*|plummet\w*|debris|collaps\w*|tumbl\w*)\b"
BRAKE = r"\b(crash(ed|es|ing)?|collid\w*|slammed|smashed|brak\w*|skid\w*|stopp(ed|ing)|halted|impact)\b"
WATER = r"\b(floods?|flooding|river|rising water|water levels?|tides?|storm surge|dam)\b"
STORM = r"\b(storms?|hurricanes?|typhoons?|cyclones?|tornado\w*|winds?|gusts?)\b"
TRAVEL = r"\b(travel\w*|drove|driv\w*|sail\w*|flew|fly\w*|cross\w*|transit\w*|head(ed|ing)|en route|journey|moved|moving|went|raced|sped|accelerat\w*)\b"
PHYS_MODELS = ("travel", "brake", "free_fall", "launch", "water_rise", "storm_build")


def _num_unit(text, units):
    """First "<number> <unit>" in the text (digits with commas) for any of the unit regexes. -> (value, matched unit) or (None, "")."""
    m = re.search(r"([\d][\d,]*(?:\.\d+)?)\s*(" + "|".join(units) + r")\b", text, re.I)
    return (float(m.group(1).replace(",", "")), m.group(2).lower()) if m else (None, "")


def _speed_kmh(text):
    v, u = _num_unit(text, [r"km/h", r"kph", r"kilomet(?:er|re)s? (?:an|per) hour", r"mph", r"miles (?:an|per) hour", r"knots?", r"kn"])
    if v is None: return None
    return v * (1.609 if u.startswith("m") else 1.852 if u.startswith("kn") else 1.0)


def _metres(text):
    v, u = _num_unit(text, [r"feet", r"ft", r"met(?:er|re)s?", r"m", r"kilomet(?:er|re)s?", r"km", r"miles?"])
    if v is None: return None
    return v * {"f": 0.3048, "k": 1000.0}.get(u[0], 1609.0 if u.startswith("mi") else 1.0)


def _secs(text):
    v, u = _num_unit(text, [r"seconds?", r"secs?", r"minutes?", r"mins?", r"hours?", r"hrs?", r"days?"])
    if v is None: return None
    return v * (60 if u.startswith("mi") else 3600 if u.startswith("h") else 86400 if u.startswith("d") else 1)


def _ease(a, b, x):   # smooth start/stop between two values (0 <= x <= 1)
    return a + (b - a) * (0.5 - 0.5 * math.cos(math.pi * max(0.0, min(1.0, x))))


def _tl(secs):   # readable duration for labels
    return f"{secs / 3600:.1f} h" if secs >= 5400 else f"{secs / 60:.0f} min" if secs >= 120 else f"{secs:.0f} s"


def _profile(model, p, kind="object", icon="dot"):
    """One physics law -> Sim.tsx spec (series [[t_s, value]]). p holds narration numbers; anything missing gets a typical value
    and is listed in `assumed`. -> spec or None."""
    assumed, s, marks = [], [], []
    def a(name, val, why):
        if p.get(name) in (None, "", 0): p[name] = val; assumed.append(why)
        return float(p[name])
    if model == "travel":   # accelerate to cruise, hold, slow to a stop; drawn as DISTANCE covered (a flat speed line says nothing)
        v = a("speed_kmh", dict((k, c) for _, k, c, _ in MOVERS).get(kind, 60), f"typical {kind} speed")
        if p.get("distance_km") and not p.get("secs"): p["secs"] = float(p["distance_km"]) / max(v, 1) * 3600 * 1.1   # stated distance
        T = a("secs", 60 * {"car": 30, "truck": 120, "train": 60, "ship": 720, "aircraft": 120, "helicopter": 60, "drone": 20,
                            "bike": 60, "troops": 240}.get(kind, 30), f"typical {kind} trip length")
        acc = {"car": 3.0, "truck": 1.2, "train": 0.5, "ship": 0.05, "aircraft": 2.0}.get(kind, 1.5)   # m/s^2
        ta = min(T * 0.3, (v / 3.6) / acc)
        speed = lambda t: _ease(0, v, t / ta) if t < ta else (_ease(v, 0, (t - (T - ta)) / ta) if t > T - ta else v)
        d, prev = 0.0, 0.0
        for i in range(241):
            t = T * i / 240
            d += (speed(prev) + speed(t)) / 2 / 3.6 * (t - prev) / 1000; prev = t   # km, trapezoid rule
            s.append([round(t, 2), round(d, 2)])
        marks = [{"t": T * 0.5, "text": f"cruising at {v:,.0f} km/h"}]
        return {"title": p.get("title") or f"{kind.capitalize()} journey", "unit": "km", "series": s, "icon": icon, "marks": marks,
                "label": f"about {d:,.{0 if d >= 100 else 1}f} km in {_tl(T)} at {v:,.0f} km/h", "assumed": assumed}
    if model == "brake":    # cruise, then a hard stop (braking) or an impact (crash): speed vs time
        v = a("speed_kmh", dict((k, c) for _, k, c, _ in MOVERS).get(kind, 80), f"typical {kind} speed")
        crash = bool(p.get("impact"))
        dec = float(p.get("decel_mps2") or 0) or (300.0 if crash else 7.0)   # an impact stops in ~0.1 s; firm braking ~7 m/s^2
        if not p.get("decel_mps2"): assumed.append("impact deceleration" if crash else "braking deceleration (dry road)")
        tb = (v / 3.6) / dec; lead = max(1.0, tb * (3 if not crash else 20)); T = lead + tb + lead * 0.5
        for i in range(241):
            t = T * i / 240
            val = v if t < lead else max(0.0, v - (t - lead) * dec * 3.6)
            s.append([round(t, 3), round(val, 1)])
        g_load = dec / G
        marks = [{"t": lead, "text": "impact" if crash else "brakes on"}]
        return {"title": p.get("title") or ("Impact" if crash else "Braking"), "unit": "km/h", "series": s, "icon": icon, "marks": marks,
                "label": f"{v:,.0f} km/h to 0 in {tb:.2f} s ({g_load:,.0f} g)", "assumed": assumed}
    if model == "free_fall":   # height vs time with air drag: v(t) = vt*tanh(g t / vt), h = h0 - (vt^2/g) ln cosh(g t / vt)
        h0 = a("height_m", 100.0, "drop height"); vt = a("terminal_mps", 55.0, "terminal speed (~55 m/s, a person-sized object)")
        T = vt / G * math.acosh(math.exp(min(h0 * G / vt ** 2, 700)))   # time to reach the ground
        for i in range(241):
            t = T * i / 240
            h = h0 - (vt ** 2 / G) * math.log(math.cosh(G * t / vt))
            s.append([round(t, 3), round(max(0.0, h), 1)])
        v_end = vt * math.tanh(G * T / vt)
        return {"title": p.get("title") or "Fall", "unit": "m", "series": s, "icon": "drop", "marks": [{"t": T, "text": f"ground at {v_end * 3.6:,.0f} km/h"}],
                "label": f"{h0:,.0f} m in {T:.1f} s", "assumed": assumed}
    if model == "launch":      # powered climb then coast: altitude vs time (no atmosphere model; illustrative ascent)
        acc = a("accel_mps2", 25.0, "thrust acceleration (~2.5 g)"); burn = a("burn_secs", 60.0, "engine burn time")
        T = burn * 2.2; vb = acc * burn; hb = 0.5 * acc * burn ** 2
        for i in range(241):
            t = T * i / 240
            h = 0.5 * acc * t * t if t <= burn else hb + vb * (t - burn) - 0.5 * G * (t - burn) ** 2
            s.append([round(t, 2), round(max(0.0, h) / 1000, 2)])
        return {"title": p.get("title") or "Launch", "unit": "km", "series": s, "icon": "rocket", "marks": [{"t": burn, "text": f"burnout at {vb * 3.6:,.0f} km/h"}],
                "label": f"{acc / G:.1f} g for {burn:.0f} s", "assumed": assumed}
    if model == "water_rise":  # logistic rise to a crest: level vs time
        rise = a("rise_m", 3.0, "rise to the crest"); T = a("secs", 12 * 3600.0, "hours to crest")
        for i in range(241):
            t = T * 1.2 * i / 240
            s.append([round(t), round(rise / (1 + math.exp(-10 * (t / T - 0.5))), 3)])
        return {"title": p.get("title") or "Water level", "unit": "m", "series": s, "icon": "wave", "marks": [{"t": T, "text": "crest"}],
                "label": f"+{rise:,.1f} m in {_tl(T)}", "assumed": assumed}
    if model == "storm_build":  # sustained wind strengthening to a peak: wind vs time
        w0 = a("start_mph", 40.0, "starting wind"); w1 = a("peak_mph", 120.0, "peak wind"); T = a("secs", 36 * 3600.0, "hours to peak")
        for i in range(241):
            t = T * 1.15 * i / 240
            s.append([round(t), round(_ease(w0, w1, t / T), 2)])   # whole numbers drew a staircase
        cat = next((c for c, lo in ((5, 157), (4, 130), (3, 111), (2, 96), (1, 74)) if w1 >= lo), 0)
        return {"title": p.get("title") or "Wind speed", "unit": "mph", "series": s, "icon": "storm",
                "marks": [{"t": T, "text": f"peak {w1:,.0f} mph" + (f" (cat {cat})" if cat else "")}], "label": f"{w0:,.0f} to {w1:,.0f} mph in {_tl(T)}", "assumed": assumed}
    return None


SYNTH_PICK = """A news video needs an animated physics graph for this beat. Narration: "{vo}"
Pick ONE model and fill its parameters ONLY with numbers the narration states (leave any other parameter out: typical values are
added and shown as assumed). Models:
- travel: something moving along (vehicle, train, ship, aircraft, troops). params: kind (car/truck/train/ship/aircraft/drone/bike/troops), speed_kmh, secs (trip time), distance_km
- brake: something stopping hard or crashing. params: kind, speed_kmh, impact (true for a crash/collision), decel_mps2
- free_fall: something falling. params: height_m, terminal_mps
- launch: rocket / missile going up. params: accel_mps2, burn_secs
- water_rise: flood / river / surge rising. params: rise_m, secs (time to crest)
- storm_build: storm / hurricane strengthening. params: start_mph, peak_mph, secs
- none: no physical motion here (figurative, markets, software, opinions)
Also give title: 2-4 words for the graph (e.g. "Braking from 100 km/h").
Reply with ONLY JSON: {{"model": "...", "params": {{...}}, "title": "..."}}"""


def _pick_model(text):
    """Offline choice of a physics model from the narration's words. -> (model, kind, icon) or (None, ...)."""
    kind, icon = next(((k, ic) for rx, k, _, ic in MOVERS if re.search(rx, text, re.I)), ("object", "dot"))
    if re.search(LAUNCH, text, re.I) and not re.search(BRAKE, text, re.I): return "launch", kind, icon
    if re.search(STORM, text, re.I) and re.search(r"\b(strengthen\w*|intensif\w*|grew|grow\w*|built|build\w*|picked up|gain\w*|category)\b", text, re.I):
        return "storm_build", kind, icon
    if re.search(WATER, text, re.I) and re.search(r"\b(ris\w*|rose|swell\w*|surg\w*|crest\w*|flood\w*|burst|overflow\w*)\b", text, re.I):
        return "water_rise", kind, icon
    if re.search(BRAKE, text, re.I) and kind != "object": return "brake", kind, icon
    if re.search(FALL, text, re.I) and kind in ("object", "drone"): return "free_fall", kind, icon
    if kind != "object" and re.search(TRAVEL + r"|\bflows?\b", text, re.I): return "travel", kind, icon
    return None, kind, icon   # e.g. "water flows through a river": no event to model, so graphics draw it instead


def synthetic_profile(sec, cfg=None, log=None):
    """REAL physics on SYNTHETIC data for a beat with physical motion and no real data. The script model picks the law and copies
    the narration's numbers (when cfg has a provider); offline, the words pick it and regexes read the numbers. -> sim spec or None."""
    text = str(sec.get("vo") or "")
    if not text or non_physical(sec, text): return None
    model, kind, icon = _pick_model(text)
    params, title = {}, ""
    if cfg and (cfg.get("script_provider") or cfg.get("deepseek_api_key") or cfg.get("anthropic_api_key")):
        try:
            from .llm import LLM
            c = dict(cfg)
            if c.get("script_provider") == "claude" and not c.get("anthropic_api_key"): c["script_provider"] = "deepseek" if c.get("deepseek_api_key") else "local"
            def chk(j):
                if j.get("model") not in PHYS_MODELS + ("none",): raise ValueError("unknown model")
            with LLM(c, log or (lambda _: None), lambda: False) as llm:
                j = llm.chat_json("You set up physics simulations for news graphics. Reply with JSON only.",
                                  SYNTH_PICK.format(vo=text[:700].replace('"', "'")), max_tokens=500, check=chk)
            if j.get("model") == "none": return None
            model = j["model"]; params = {k: v for k, v in (j.get("params") or {}).items() if v not in (None, "")}; title = str(j.get("title") or "")[:40]
            kind = str(params.pop("kind", "") or kind).lower()
            icon = next((ic for _, k, _, ic in MOVERS if k == kind), icon)
        except Exception as e:
            (log or (lambda _: None))(f"  physics: model picker unavailable ({str(e)[:80]}); words decide")
    if not model: return None
    if not params:   # offline: the narration's own numbers
        sp, m, sec_ = _speed_kmh(text), _metres(text), _secs(text)
        if not sp and m and sec_ and model == "travel" and m >= 1000:   # "400 km in 5 hours" -> 80 km/h
            sp = m / 1000 / (sec_ / 3600)
        if sp and model != "storm_build": params["speed_kmh"] = sp
        if m and model == "travel" and not sp: params["distance_km"] = m / 1000   # "travels 300 km": the stated distance
        if sec_: params["secs"] = sec_
        if model == "storm_build":   # winds in mph (or km/h, knots): the highest is the peak, a lower one the start
            ws = [float(x.replace(",", "")) * f for x, u in re.findall(r"([\d][\d,]*)\s*(mph|km/h|kph|knots?|kn)\b", text, re.I)
                  for f in [{"m": 1.0, "k": 0.621}.get(u[0].lower(), 1.0) if not u.lower().startswith("kn") else 1.151]]
            if ws: params["peak_mph"] = max(ws)
            if len(ws) > 1: params["start_mph"] = min(ws)
        if m and model == "free_fall": params["height_m"] = m
        if m and model == "water_rise" and m < 30: params["rise_m"] = m
        if model == "brake" and re.search(r"\b(crash\w*|collid\w*|slammed|smashed|impact)\b", text, re.I): params["impact"] = True
    try:
        params = {k: (float(v) if k not in ("impact", "title") and not isinstance(v, bool) else v) for k, v in params.items()}
    except (TypeError, ValueError):
        params = {}
    # owner, 2026-11-07: never invent numbers. A chart whose every number is a "typical" fill-in ("sailing journey 297 km",
    # "from snow to sand 1,353 km at 850 km/h" on a personal story with no distance in it) is fiction dressed as data: no chart.
    if not any(isinstance(v, (int, float)) and not isinstance(v, bool) and v for k, v in params.items() if k not in ("title", "impact")):
        (log or (lambda _: None))("  physics: the narration states no number for this motion; no modelled chart (it would be invented)")
        return None
    if title: params["title"] = title
    r = _profile(model, params, kind, icon)
    if not r or len(r["series"]) < 2: return None
    notes = "Modelled from the narration, not measured" + (": assumed " + ", ".join(r.pop("assumed")) if r.get("assumed") else "")
    r.pop("assumed", None)
    return {"kind": "sim", "module": f"synthetic_{model}", **r, "notes": notes, "synthetic": True, "source": "synthetic"}


# Deterministic, offline illustrative motion. Never presented as observations.
def synthetic_motion(sec, cfg=None, log=None):
    text = str(sec.get("vo") or "")
    if non_physical(sec, text): return None
    radar = re.search(r"\b(radar|radars)\b", text, re.I)
    moving = re.search(r"\b(mov\w*|sweep\w*|flow\w*|travel\w*|sail\w*|transit\w*|cross\w*|heading|en route|route|tracking|track)\b", text, re.I)
    ship = re.search(r"\b(ships?|vessels?|tankers?|shipping)\b", text, re.I)
    if not radar and not (ship and moving and re.search(r"hormuz", text, re.I)):
        # everything else: a physics law on the narration's numbers; synthetic_profile has its own gate (a real mover or a
        # physical event: crash, fall, launch, flood, storm) so "the market moves higher" still gets nothing
        return synthetic_profile(sec, cfg, log)
    if ship:
        params = {"title": "Strait of Hormuz transit", "waypoints": [
            {"name": "", "lat": 26.5, "lon": 55.6},
            {"name": "Strait of Hormuz", "lat": 26.6, "lon": 56.3},
            {"name": "Gulf of Oman", "lat": 25.6, "lon": 57.4}]}
        result = ship_route(params)
        result.update(synthetic=True, label="SYNTHETIC • illustrative route, not live AIS",
                      notes="Illustrative coordinates and timing; no observed vessel track.", source="synthetic")
        return result
    if not radar:   # everything else that moves: a physics law on the narration's numbers (no more fixed sine "physical_flow")
        return synthetic_profile(sec, cfg, log)
    return {"kind": "motion", "module": "radar_sweep", "title": "Radar sweep",
            "synthetic": True, "source": "synthetic",
            "label": "SYNTHETIC • schematic, not live tracking",
            "angles": [i * 6 for i in range(121)],
            "points": [[0.15 + i * 0.7 / 60, 0.5] for i in range(61)],
            "targets": [[0.25, 0.3], [0.7, 0.4], [0.55, 0.75]]}


MOTION_WORDS = (r"\b(flew|fly|flying|flight|sail\w*|travel\w*|drove|driv\w*|head(ed|ing)|en route|route|diverted|crossed|cross\w*|"
                r"transit\w*|moved|moving|went|returned|landed|took off|departed|arrived|bound for|spread|swept|tracked|track\w*)\b")


def _map_route(sec, backdrop, text):
    """The script's own map (real coordinates the script AI wrote for this beat) as a track, when the slot describes travel."""
    pts = [p for p in (backdrop or {}).get("points") or [] if isinstance(p, dict) and p.get("lat") is not None and p.get("lon") is not None]
    if (backdrop or {}).get("kind") != "map" or len(pts) < 2 or not re.search(MOTION_WORDS, text, re.I): return None
    order = {"origin": 0, "stop": 1, "planned": 3, "actual": 2, "place": 1}
    act = [p for p in pts if p.get("role") != "planned"] if any(p.get("role") == "actual" for p in pts) else pts
    act = sorted(act, key=lambda p: order.get(p.get("role"), 1))
    try: way = [{"lat": float(p["lat"]), "lon": float(p["lon"]), "name": str(p.get("name") or "")[:22]} for p in act]
    except (TypeError, ValueError): return None
    if len(way) < 2: return None
    track = []
    for a, b in zip(way, way[1:]):
        for i in range(16): k = i / 16; track.append({"lat": a["lat"] + (b["lat"] - a["lat"]) * k, "lon": a["lon"] + (b["lon"] - a["lon"]) * k})
    track.append({"lat": way[-1]["lat"], "lon": way[-1]["lon"]})
    subj = (sec.get("subject") or {}).get("kind")
    return {"kind": "simmap", "module": "route", "title": backdrop.get("title") or "Route", "icon": "ship" if subj == "ship" else None,
            "label": " -> ".join(w["name"] for w in way if w["name"])[:80], "track": track, "places": [w for w in way if w["name"]],
            "notes": "route from the script's coordinates", "source": "script map"}


def provide(cfg, sec, backdrop, log, pos=None, story=""):
    """Physics as a DATA PROVIDER (visual ladder rung 5). -> payload or None:
    {"module", "source": "real data" | "narration" | "script map" | "synthetic", "verb", "spec": <Remotion graphic spec>, "params"}.
    Order: a matching module with real data / the narration's numbers (NOAA storm tracks, AIS, altitude/depth profiles) ->
    the script's own map coordinates when the slot describes travel -> a labelled synthetic motion path.
    Rung 6 (Remotion graphics) draws the spec; nothing here renders."""
    text = slot_text(sec.get("vo", ""), pos)
    off = non_physical(sec, sec.get("vo", ""))
    if off:
        log(f"  {sec.get('id', 'beat')}: physics off: '{off}' is not a physical object")
        return None
    verb, mod = action(sec, text)
    if not mod: verb, mod = action(sec)
    if mod:
        params = fill(cfg, mod, {**sec, "_story": story}, log)
        spec = run(mod, params, cfg)
        if spec:
            src = spec.get("source") or ""
            kind = "real data" if any(k in src for k in ("NOAA", "AIS", "HURDAT")) else ("synthetic" if spec.get("synthetic") else "narration")
            return {"module": mod, "source": kind, "verb": verb, "spec": spec, "params": params}
    spec = _map_route(sec, backdrop, text)
    if spec: return {"module": "route", "source": "script map", "verb": "travel", "spec": spec, "params": {}}
    spec = synthetic_motion({**sec, "vo": text}, cfg, log)
    if not spec and re.search(MOTION_WORDS + r"|\b(dive[sd]?|diving|launch\w*|fired|struck|strike|charg\w*|chas\w*|fell|falling|rose|climb\w*|accelerat\w*|"
                              r"crash\w*|collid\w*|brak\w*|flood\w*|strengthen\w*|intensif\w*)\b", text, re.I):
        # physical motion the specific modules don't cover: a physics law on synthetic data (the old fixed sine path is gone)
        spec = synthetic_profile({**sec, "vo": text}, cfg, log)
    if spec: return {"module": spec.get("module", "motion"), "source": "synthetic", "verb": "motion", "spec": spec, "params": {}}
    return None
