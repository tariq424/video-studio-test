"""Physics / data simulations for a beat (pause chat: "simulate the descent using real physics").

Registry of small modules with one interface:   run(params: dict) -> {"title", "unit", "series": [[t_seconds, value], ...],
"icon", "label", "notes"}   (a time series; the renderer doesn't care which module made it). The chat's router (debug.chat,
DeepSeek) picks the module and fills the parameters from the narration; the result becomes a `sim` graphic (Remotion
Sim.tsx: an animated profile with the subject riding the curve and a live readout), offered as a candidate for the beat.

Implemented (pure Python, no packages, no network):
  aircraft_flight     altitude profile: cruise -> descent at a computed rate (or the narration's start/end altitudes and duration)
                      -> optional level-off; ft vs s. Real ADS-B (OpenSky) is NOT wired: its history API needs an account.
  submarine_descent   depth vs time at a sink rate, with the hull pressure p = rho*g*h shown (crush depth marked if given)
Registered but not built yet (return None -> the beat keeps its illustration): vehicle_crash, structural_collapse,
earthquake, ship_route, weather_event. Adding one = one function here + its name in MODULES.
Compute strategy: every series is downsampled to <= 240 points and the timeline is compressed into the beat's length."""
import math

G, RHO_SEA = 9.81, 1025.0


def _down(series, n=240):
    if len(series) <= n: return series
    k = len(series) / n
    return [series[int(i * k)] for i in range(n)] + [series[-1]]


def aircraft_flight(p):
    drop = float(p.get("drop_ft") or 0); assumed = ""
    start = float(p.get("start_alt_ft") or 0); end = float(p.get("end_alt_ft") or 0)
    if drop:   # "lost 12,000 feet": the narration often gives the drop, not the altitudes
        if start and not end: end = start - drop
        elif end and not start: start = end + drop
        elif not start: start = 35000.0; end = start - drop; assumed = "start assumed at a 35,000 ft cruise; "
    start = start or 35000.0; end = end if end or end == 0 else 10000.0
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
    return {"title": p.get("title") or "Altitude", "unit": "ft", "series": _down(series), "icon": "plane",
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


def _not_built(name):
    return lambda p: None


MODULES = {
    "aircraft_flight": (aircraft_flight, "plane altitude / descent / climb profile. params: drop_ft (feet lost, when the narration says 'lost/dropped N feet'), start_alt_ft and end_alt_ft (only altitudes the narration states), descent_secs (how long it took), rate_fpm, title, label"),
    "submarine_descent": (submarine_descent, "submarine dive to depth with pressure. params: max_depth_m, sink_mps, crush_depth_m, title, label"),
    "vehicle_crash": (_not_built("vehicle_crash"), "car crash (not built yet)"),
    "structural_collapse": (_not_built("structural_collapse"), "building collapse (not built yet)"),
    "earthquake": (_not_built("earthquake"), "seismic event (not built yet)"),
    "ship_route": (_not_built("ship_route"), "vessel path (not built yet)"),
    "weather_event": (_not_built("weather_event"), "storm / hurricane (not built yet)"),
}


def describe():
    return "\n".join(f"- {k}: {v[1]}" for k, v in MODULES.items())


def run(module, params):
    """-> a `sim` graphic spec for Remotion, or None (unknown / not built / bad parameters)."""
    if module not in MODULES: return None
    try: r = MODULES[module][0](params or {})
    except Exception: return None
    if not r or len(r.get("series") or []) < 2: return None
    return {"kind": "sim", "module": module, **r}
