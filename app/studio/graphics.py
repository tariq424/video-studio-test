"""Visual ladder v2, rung 5: Remotion graphics (label GRAPHICS). Only runs with settings "ladder_v2": true.

A beat that stock, real photos, the cloud and WanGP didn't cover gets a code-generated animated clip:
  1. Templates (default): eight parameterised compositions in remotion/src/Templates.tsx -
     stat, quote, timeline, compare, route (map with route), chart, list (stacked cards), abstract (gradient / particles + text).
     classify() picks one. It REUSES the beat analysis the script AI already wrote (the beat's backdrop map and its on-screen
     graphics: stat / quote / timeline / compare / icons) - no model call for those beats. Only when that analysis has nothing
     that maps to a template does it make ONE small JSON call (the script provider: DeepSeek by default) that picks a template
     from the narration and fills its data, or answers "none".
  2. Claude-generated (fallback, "graphics_claude"): when no template fits, Claude writes a Remotion component for that one beat
     (remotion/src/gen/, deleted after the render). Static checks first (imports limited to react / remotion / ../theme; no network,
     files, eval, external URLs); one repair round with the render error. Cost cap: "graphics_claude_max_per_video" (default 3)
     compositions per video, counted in <workspace>/graphics/state.json.
Both paths give the same thing: an MP4 of "graphics_secs" (6-10 s) at the workspace's frame size, colour range normalised to
limited (tv) like every other clip. make() -> {"ok", "path", "how": "template:<t>" | "claude", "why", "hard"}.
hard=True means a HARD failure (crash, no output, timeout) - the only thing that can send a beat to CapCut (rung 7); a template
that simply doesn't fit is not a failure of the rung, it's "none"."""
import hashlib, json, re, shutil, subprocess, time
from pathlib import Path
from . import media

TEMPLATES = ("stat", "quote", "timeline", "compare", "route", "chart", "list", "abstract")
FPS = 30

CLASSIFY = """A vertical news video needs an animated GRAPHIC for one beat (no footage fits it). The narrator says:
"{vo}"
{ctx}
Pick the ONE template that shows this beat best, and fill its data ONLY with facts in the narration (never invent numbers, names
or quotes). Templates and their data:
- stat: one striking quantity. {{"value": 5, "decimals": 0, "prefix": "$", "suffix": "B", "label": "2-5 words", "sub": "optional short line", "kicker": "1-2 words"}}
- quote: words someone actually said in the narration. {{"text": "max 18 words", "who": "name", "role": "optional"}}
- timeline: 3-5 events in order. {{"title": "short", "steps": [{{"when": "1-2 words", "label": "2-4 words"}}]}}
- compare: two sides. {{"title": "", "badge": "vs", "left": {{"icon": "emoji", "head": "1-3 words", "value": "optional number", "body": "2-6 words"}}, "right": {{...}}, "note": ""}}
- route: places / a journey with real coordinates. {{"title": "2-5 words", "points": [{{"name": "Dubai", "lat": 25.25, "lon": 55.36, "role": "origin|stop|actual|planned|place"}}]}}
- chart: 3-8 values of one measure (over time or across things). {{"title": "short", "style": "bar" or "line", "unit": "", "prefix": "", "suffix": "", "decimals": 0, "points": [{{"label": "2019", "value": 12}}]}}
- list: 3-5 parallel points. {{"title": "short", "items": [{{"icon": "emoji", "text": "2-6 words"}}]}}
- abstract: a general statement with no data, place or sequence. {{"kicker": "1-2 words", "text": "4-10 words summing up the beat", "sub": "optional"}}
- none: the beat needs a specific picture of a process, mechanism, object or scene that none of these can show.
Reply with ONLY JSON: {{"template": "stat|quote|timeline|compare|route|chart|list|abstract|none", "data": {{...}}, "why": "max 12 words"}}"""

GEN = """Write ONE Remotion (React + TypeScript) component that animates this beat of a news video for {secs} seconds.
Narration: "{vo}"
{ctx}
Frame: {w}x{h} at 30 fps ({orient}). {zones}
Rules:
- Export exactly: export const Gen: React.FC<{{ dur: number }}> = ({{ dur }}) => {{ ... }};
- Imports ONLY from "react", "remotion" (AbsoluteFill, useCurrentFrame, useVideoConfig, interpolate, spring, Easing, Sequence)
  and "../theme" (C = colours {{bg, card, line, text, mut, gold, red, teal}}, HEAD and BODY = font families). Nothing else.
- Draw everything with JSX / inline SVG / CSS. No images, videos, fonts, files, network requests, fetch, timers or randomness
  (use a seeded formula if you need variety); every frame must be a pure function of useCurrentFrame().
- Show what the narration describes (a process, a mechanism, a relation) as clear motion: shapes, arrows, labels of at most 4 words.
  Use only facts in the narration. No logos, brand marks, flags or human faces.
- Dark background (#070a12 to #13203a), white text, gold #FFC83D / teal #2EE6C5 accents, big readable type (>= 34 px).
- Under 220 lines. Reply with ONLY the code in one ```tsx block."""

BAD = re.compile(r"\b(fetch|XMLHttpRequest|WebSocket|require|eval|Function|import\s*\(|process\.|child_process|localStorage|sessionStorage|"
                 r"document\.cookie|window\.location|setTimeout|setInterval|Math\.random|Date\.now|new Date)\b|https?://")
IMPORT = re.compile(r"^\s*import\s+(?:[^'\"]+\s+from\s+)?['\"]([^'\"]+)['\"]", re.M)
OK_IMPORTS = {"react", "remotion", "../theme"}


def _ws_space(sd):
    from .ladder import space
    return space(sd)


# ---------------------------------------------------------------- 1. classify (reuses the beat analysis)
def _from_analysis(sec):
    """-> (template, data, why) from what the script AI already wrote for the beat, or None."""
    bd = sec.get("backdrop") or {}
    pts = [p for p in bd.get("points") or [] if isinstance(p, dict) and _num(p.get("lat")) is not None and _num(p.get("lon")) is not None]
    if bd.get("kind") == "map" and len(pts) >= 2:
        return "route", {"title": bd.get("title", ""), "points": pts}, "the beat's route map"
    for v in sec.get("visuals") or []:
        g = v.get("chart") or v.get("g") or {}
        k = g.get("kind")
        if k == "stat" and _num(g.get("value")) is not None:
            return "stat", {k2: g.get(k2) for k2 in ("value", "decimals", "prefix", "suffix", "label", "sub")}, "the beat's stat"
        if k == "quote" and g.get("text"): return "quote", {"text": g["text"], "who": g.get("who", "")}, "the beat's quote"
        if k == "timeline" and len(g.get("steps") or []) >= 2: return "timeline", {"title": g.get("title", ""), "steps": g["steps"]}, "the beat's timeline"
        if k == "compare" and g.get("left") and g.get("right"):
            return "compare", {k2: g.get(k2) for k2 in ("left", "right", "badge", "note")}, "the beat's comparison"
        if k == "icons" and len(g.get("items") or []) >= 3:
            return "list", {"title": g.get("title", ""), "items": [{"icon": i.get("icon", ""), "text": i.get("label", "")} for i in g["items"]]}, "the beat's icon list"
    return None


def _num(x):
    try: return float(x)
    except (TypeError, ValueError): return None


def _valid(t, d):
    """Minimal shape check of a template's data (the model fills it); -> cleaned data or None."""
    if not isinstance(d, dict): return None
    if t == "stat": return d if _num(d.get("value")) is not None and d.get("label") else None
    if t == "quote": return d if d.get("text") else None
    if t == "timeline": return d if len(d.get("steps") or []) >= 2 else None
    if t == "compare": return d if isinstance(d.get("left"), dict) and isinstance(d.get("right"), dict) else None
    if t == "route":
        pts = [p for p in d.get("points") or [] if isinstance(p, dict) and _num(p.get("lat")) is not None and _num(p.get("lon")) is not None]
        return {**d, "points": pts} if len(pts) >= 2 else None
    if t == "chart":
        pts = [p for p in d.get("points") or [] if isinstance(p, dict) and _num(p.get("value")) is not None]
        return {**d, "points": pts} if len(pts) >= 2 else None
    if t == "list": return d if len(d.get("items") or []) >= 2 else None
    if t == "abstract": return d if d.get("text") else None
    return None


def classify(cfg, sec, log, ctx=""):
    """-> {"template": t | None, "data", "why", "how": "analysis" | "model"}. Never raises."""
    from .physics import synthetic_motion
    motion = synthetic_motion(sec)
    if motion:
        return {"template": "motion", "data": motion, "why": "physical motion requires animation", "how": "synthetic"}
    a = _from_analysis(sec)
    if a: return {"template": a[0], "data": a[1], "why": a[2], "how": "analysis"}
    from .llm import LLM
    c = dict(cfg)
    if c.get("script_provider") == "claude" and not c.get("anthropic_api_key"): c["script_provider"] = "deepseek" if c.get("deepseek_api_key") else "local"
    def chk(j):
        t = j.get("template")
        if t not in TEMPLATES + ("none",): raise ValueError("unknown template")
        if t != "none" and _valid(t, j.get("data")) is None: raise ValueError(f"data does not fit the {t} template")
    try:
        with LLM(c, log, lambda: False) as llm:
            j = llm.chat_json("You design news graphics. Reply with JSON only.", CLASSIFY.format(vo=sec.get("vo", "")[:700].replace('"', "'"), ctx=ctx),
                              max_tokens=900, check=chk)
    except Exception as e:
        return {"template": None, "data": None, "why": f"classifier unavailable ({str(e)[:80]})", "how": "model"}
    t = j.get("template")
    if t == "none": return {"template": None, "data": None, "why": str(j.get("why") or "no template fits")[:90], "how": "model"}
    return {"template": t, "data": _valid(t, j.get("data")), "why": str(j.get("why") or "")[:90], "how": "model"}


# ---------------------------------------------------------------- rendering
def _normalise(raw, out):
    """Remotion writes full-range video; mixed with limited-range clips in one concat it corrupted a section (see render.py)."""
    media.ff("-i", raw, "-an", "-vf", "scale=in_range=pc:out_range=tv,format=yuv420p", "-color_range", "tv", "-c:v", "libx264",
             "-preset", "veryfast", "-crf", 16, out)
    Path(raw).unlink(missing_ok=True)


def _hard(e):
    s = str(e)
    if isinstance(e, subprocess.TimeoutExpired) or "timed out" in s.lower(): return f"timeout ({s[:80]})"
    return f"crash ({s[:120]})"


def render_template(cfg, sd, t, data, secs, out, log, tag=None):
    """Template -> MP4 at out. tag (e.g. "GRAPHICS") burns the label in (explainers); Shorts get it from Shot instead."""
    from . import review
    bg = {"type": "graphic", "g": data if t == "motion" else {"kind": "tpl", "t": t, "d": data}}
    if tag: bg["tag"] = tag
    raw = Path(out).with_name(Path(out).stem + "_raw.mp4")
    review._remotion(sd, bg, secs, raw, cfg, log, frames=(0, int(secs * FPS) - 1), scale=1, crf=16, timeout=int(cfg.get("graphics_timeout", 300)))
    _normalise(raw, out)
    return out


def _state(sd):
    f = Path(sd) / "graphics" / "state.json"
    try: return f, (json.loads(f.read_text(encoding="utf-8")) if f.exists() else {})
    except Exception: return f, {}


def _code(text):
    m = re.search(r"```(?:tsx|typescript|ts|jsx)?\s*\n(.*?)```", text, re.S)
    return (m.group(1) if m else text).strip()


def check_code(code):
    """-> "" if the component may be rendered, else the reason."""
    if "export const Gen" not in code: return "no `export const Gen` component"
    bad = [m for m in IMPORT.findall(code) if m not in OK_IMPORTS]
    if bad: return f"imports not allowed: {', '.join(sorted(set(bad)))}"
    m = BAD.search(code)
    if m: return f"not allowed in a composition: {m.group(0)}"
    if len(code) > 30000: return "too long"
    return ""


def _gen_llm(cfg, log):
    from .llm import LLM
    c = dict(cfg)
    if c.get("anthropic_api_key"):
        c["script_provider"] = "claude"
        if c.get("graphics_claude_model"): c["script_model"] = c["graphics_claude_model"]
    return LLM(c, log, lambda: False)


def _render_gen(cfg, sd, code, secs, out, log, tag=None):
    """Write the component + a one-composition entry into remotion/src/gen/, render it, clean up. Raises on failure."""
    from . import short
    rdir = short._ensure_remotion(log); gdir = Path(rdir) / "src" / "gen"; gdir.mkdir(parents=True, exist_ok=True)
    sp = _ws_space(sd); w, h = sp["w"], sp["h"]
    name = "G" + hashlib.sha1((code + str(time.time())).encode()).hexdigest()[:10]
    lab = ("" if True else   # rung labels are never burned in (2026-10-21); tag stays in the logs
           f'<div style={{{{position:"absolute",top:{250 if h > w else 40},left:{40 if h > w else 48},fontFamily:"Inter, sans-serif",fontWeight:800,'
           f'fontSize:{28 if h > w else 24},letterSpacing:3,color:"#111",background:"rgba(255,200,61,0.95)",borderRadius:8,padding:"8px 16px"}}}}>{tag}</div>')
    (gdir / f"{name}.tsx").write_text(code, encoding="utf-8")
    (gdir / f"{name}.entry.tsx").write_text(
        'import React from "react";\nimport { AbsoluteFill, Composition, registerRoot } from "remotion";\nimport "../theme";\n'
        f'import {{ Gen }} from "./{name}";\n'
        f'const Clip: React.FC<{{ dur: number }}> = ({{ dur }}) => <AbsoluteFill style={{{{ background: "#070a12" }}}}><Gen dur={{dur}} />{lab}</AbsoluteFill>;\n'
        f'registerRoot(() => <Composition id="Gen" component={{Clip as any}} fps={{{FPS}}} width={{{w}}} height={{{h}}} '
        f'durationInFrames={{{int(secs * FPS)}}} defaultProps={{{{ dur: {secs} }}}} />);\n', encoding="utf-8")
    raw = Path(out).with_name(Path(out).stem + "_raw.mp4"); Path(out).parent.mkdir(parents=True, exist_ok=True)
    cmd = [short._npx(), "remotion", "render", f"src/gen/{name}.entry.tsx", "Gen", str(raw), f"--gl={short._gl(cfg)}", "--crf=16",
           "--concurrency=2", "--log=error"]
    try:
        p = subprocess.run(cmd, cwd=rdir, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=int(cfg.get("graphics_timeout", 300)))
        if p.returncode != 0 or not raw.exists():
            raise RuntimeError(" / ".join((p.stdout + p.stderr).strip().splitlines()[-6:])[:600] or "no output")
    finally:
        for f in (gdir / f"{name}.tsx", gdir / f"{name}.entry.tsx"): f.unlink(missing_ok=True)
    _normalise(raw, out)
    return out


def claude_generate(cfg, sd, sec, secs, out, log, tag=None, ctx=""):
    """Claude writes a composition for this beat (one write + one repair). -> {"ok", "path", "why", "hard"}.
    Counts against graphics_claude_max_per_video; over the cap -> not attempted (not a hard failure)."""
    f, st = _state(sd); used = int(st.get("claude_used", 0)); cap = int(cfg.get("graphics_claude_max_per_video", 3))
    if used >= cap: return {"ok": False, "path": None, "why": f"Claude-generated cap reached ({cap} per video)", "hard": False}
    sp = _ws_space(sd); tall = sp["h"] > sp["w"]
    zones = ("Keep the top 380 px (title tag, progress bar) and the bottom 520 px (captions) free of text." if tall
             else "Keep the bottom 160 px (captions) free of text.")
    prompt = GEN.format(secs=secs, vo=sec.get("vo", "")[:700].replace('"', "'"), ctx=ctx, w=sp["w"], h=sp["h"],
                        orient="portrait" if tall else "landscape", zones=zones)
    st["claude_used"] = used + 1; f.parent.mkdir(parents=True, exist_ok=True); f.write_text(json.dumps(st), encoding="utf-8")
    try:
        with _gen_llm(cfg, log) as llm:
            code = _code(llm.chat("You write small, correct Remotion components. Reply with code only.", prompt, max_tokens=6000))
            for attempt in range(2):
                why = check_code(code)
                if not why:
                    try:
                        _render_gen(cfg, sd, code, secs, out, log, tag=tag)
                        if media.ok(out) and media.dur(out) >= 1: return {"ok": True, "path": out, "why": "", "hard": False}
                        why = "render produced no usable output"
                    except subprocess.TimeoutExpired as e: return {"ok": False, "path": None, "why": _hard(e), "hard": True}
                    except Exception as e: why = f"render error: {str(e)[:400]}"
                if attempt == 0:
                    log(f"  graphics: Claude's composition failed ({why[:120]}); one repair")
                    code = _code(llm.chat("You write small, correct Remotion components. Reply with code only.",
                                          prompt + f"\n\nYour previous component failed: {why}\nPrevious code:\n```tsx\n{code[:12000]}\n```\nFix it.", max_tokens=6000))
            return {"ok": False, "path": None, "why": f"crash ({why[:140]})", "hard": True}
    except Exception as e:
        return {"ok": False, "path": None, "why": _hard(e), "hard": True}


# ---------------------------------------------------------------- the rung
def make(cfg, sd, sec, key, log, tag=None, ctx=""):
    """Rung 5 for one slot. sd = the workspace (job/short, or an explainer stills workspace with space.json); the clip goes to
    sd/graphics/<key>.mp4. -> {"ok", "path", "how", "why", "hard", "template"}."""
    secs = max(6, min(10, int(cfg.get("graphics_secs", 8))))
    out = Path(sd) / "graphics" / f"{key}.mp4"; out.parent.mkdir(parents=True, exist_ok=True)
    if media.ok(out): return {"ok": True, "path": out, "how": "cached", "why": "", "hard": False, "template": None}
    c = classify(cfg, sec, log, ctx)
    if c["template"]:
        try:
            render_template(cfg, sd, c["template"], c["data"], secs, out, log, tag=tag)
            if media.ok(out) and media.dur(out) >= 1:
                return {"ok": True, "path": out, "how": f"template:{c['template']} ({c['how']})", "why": c["why"], "hard": False, "template": c["template"]}
            res = {"ok": False, "why": "template render produced no output", "hard": True}
        except Exception as e: res = {"ok": False, "why": _hard(e), "hard": True}
        log(f"  graphics {key}: template {c['template']} failed ({res['why'][:120]})")
        if not cfg.get("graphics_claude", True): return {**res, "path": None, "how": f"template:{c['template']}", "template": c["template"]}
    elif not cfg.get("graphics_claude", True):
        return {"ok": False, "path": None, "how": "none", "why": f"no template fits ({c['why']}); Claude-generated off", "hard": False, "template": None}
    g = claude_generate(cfg, sd, sec, secs, out, log, tag=tag, ctx=ctx)
    return {**g, "how": "claude", "template": None, "why": g["why"] or c["why"]}


def render_payload(cfg, sd, payload, key, log, tag=None):
    """Rung 6 for a physics payload: Remotion renders the payload's spec (route map, storm track, altitude / depth profile,
    synthetic motion) into an MP4 like any other GRAPHICS clip. -> path, or raises."""
    from . import review
    secs = max(6, min(10, int(cfg.get("graphics_secs", 8))))
    out = Path(sd) / "graphics" / f"{key}_physics.mp4"; out.parent.mkdir(parents=True, exist_ok=True)
    if media.ok(out): return out
    bg = {"type": "graphic", "g": payload["spec"]}
    if tag: bg["tag"] = tag
    raw = out.with_name(out.stem + "_raw.mp4")
    review._remotion(sd, bg, secs, raw, cfg, log, frames=(0, int(secs * FPS) - 1), scale=1, crf=16, timeout=int(cfg.get("graphics_timeout", 300)))
    _normalise(raw, out)
    if not (media.ok(out) and media.dur(out) >= 1): raise RuntimeError("Remotion produced no usable physics clip")
    return out
