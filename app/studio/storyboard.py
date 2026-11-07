"""Storyboard rung (owner, 2026-11-07): a style-locked storyboard for a beat.

Adapted from a public "content engine" prompt (its State 6-8 idea, not its channel cloning): lock ONE visual style profile per
video from real frames of the source, cut the beat's narration into ~3-5 s pieces (WPS x 4 words), and write one STANDALONE
image prompt per piece that restates the locked profile, plus a motion prompt for image-to-video. Every picture then shares
one look and the video gets a new picture every few seconds instead of one per 20-30 s beat.

Non-interactive: it makes every choice itself (style frames, beat split, prompts) and never waits for anyone. The Claude Code
skill (.claude/skills/storyboard) can run the same steps with a human checking each one, on request.

Where it runs: (1) the editor's beat chat ("storyboard this beat") -> candidates for the beat; (2) the Short ladder at rung 3,
only when storyboard_rung is on (default OFF) and only for a beat with no usable stock that needs 2+ pictures. Pictures come
from the image services (Cloudflare first, ~5 s each; no Google); WanGP is never used here.
Files: short/storyboard/style.json (the locked profile), short/storyboard/<beat>.json (pieces + prompts)."""
import json, re
from pathlib import Path

from . import media

STYLE = """These are frames from one source video. Describe its VISUAL STYLE so new images can match it (how it looks, not what
happens). Reply with JSON only:
{"art_style": "...", "palette": "...", "lighting": "...", "camera": "lens feel and typical shot sizes", "composition": "...",
 "texture": "detail level / grain", "mood": "..."}"""

PROMPTS = """You storyboard one beat of a news video. A new picture appears every few seconds while this narration plays.
What the whole video is about: "{story}"
LOCKED VISUAL STYLE (restate it in every prompt): {style}
Narration pieces of this beat, in order:
{pieces}
For EACH piece write one picture. Rules:
- Standalone: each prompt alone describes subject, setting, camera angle, lighting, mood and action, and restates the locked
  style. Never refer to another prompt ("same man as before").
- Show what that piece says, in the story's real place; no flags, maps or landmarks from outside the story.
- No real, named or recognisable people (show hands, crowds from behind, places, objects, documents instead); no text or logos.
- "motion": one short image-to-video instruction (camera move + subject motion, ~4 s).
Reply with JSON only: {{"shots": [{{"piece": 1, "prompt": "...", "motion": "..."}}, ...]}} with exactly {n} shots."""

DEFAULT_STYLE = {"art_style": "photorealistic documentary", "palette": "natural, slightly muted", "lighting": "soft natural light",
                 "camera": "35-50 mm, medium and wide shots", "composition": "clean, subject centred or on thirds",
                 "texture": "fine detail, light film grain", "mood": "serious, observational"}


def _dir(sd):
    d = Path(sd) / "storyboard"; d.mkdir(parents=True, exist_ok=True); return d


def style_text(p):
    return "; ".join(f"{k.replace('_', ' ')}: {v}" for k, v in p.items() if v)


def _style_frames(sd, k=4):
    """Real frames of the source: the saved snapshots first, then frames from the source excerpts. -> [paths]"""
    sd = Path(sd); out = [p for p in sorted((sd / "source_excerpts").glob("*_snap.png"))][:k]
    for mp in sorted((sd / "source_excerpts").glob("*.mp4")):
        if len(out) >= k: break
        d = media.dur(mp) or 0
        if d < 1: continue
        f = _dir(sd) / f"frame_{mp.stem[:12]}.jpg"
        if not f.exists(): media.ff("-ss", f"{d / 2:.2f}", "-i", mp, "-frames:v", 1, "-vf", "scale=640:-2", f, check=False, timeout=120)
        if f.exists(): out.append(f)
    return out[:k]


def _sheet(frames, out):
    from PIL import Image
    ims = [Image.open(f).convert("RGB") for f in frames]
    h = 360; ims = [i.resize((max(1, int(i.width * h / i.height)), h)) for i in ims]
    W = sum(i.width for i in ims[:2]); rows = [ims[:2], ims[2:4]]
    sheet = Image.new("RGB", (W, h * (2 if len(ims) > 2 else 1)), (0, 0, 0)); y = 0
    for r in rows:
        x = 0
        for i in r: sheet.paste(i, (x, y)); x += i.width
        if r: y += h
    sheet.save(out, "JPEG", quality=88); return out


def style_profile(cfg, sd, log=print):
    """The video's locked visual style, from up to 4 real source frames (cached per job). Never raises."""
    f = _dir(sd) / "style.json"
    if f.exists():
        try: return json.loads(f.read_text(encoding="utf-8"))
        except ValueError: pass
    prof, src = dict(DEFAULT_STYLE), "default"
    frames = _style_frames(sd)
    if frames:
        try:
            from . import footage
            from .llm import parse_json
            sheet = _sheet(frames, _dir(sd) / "style_sheet.jpg")
            j = parse_json(footage._vision(dict(cfg, vet_provider=cfg.get("vet_provider") if cfg.get("vet_provider") not in (None, "", "off") else "local"),
                                           sheet, STYLE)) or {}
            got = {k: str(j.get(k) or "").strip()[:120] for k in DEFAULT_STYLE}
            if sum(1 for v in got.values() if v) >= 4: prof, src = {k: got[k] or DEFAULT_STYLE[k] for k in DEFAULT_STYLE}, f"{len(frames)} source frame(s)"
        except Exception as e:
            log(f"  storyboard: style from the source failed ({str(e)[:100]}); default documentary style")
        finally:
            try:
                from . import footage; footage.unload_vet_model(cfg)
            except Exception: pass
    prof["_from"] = src
    f.write_text(json.dumps(prof, indent=1, ensure_ascii=False), encoding="utf-8")
    log(f"  storyboard: visual style locked from {src}: {style_text({k: v for k, v in prof.items() if not k.startswith('_')})[:160]}")
    return prof


def pieces(text, wpm, secs=4.0, min_words=6):
    """Cut narration into ~secs-second pieces at word boundaries, preferring sentence ends. -> [str]"""
    words = str(text or "").split()
    if not words: return []
    n = max(min_words, round(wpm / 60.0 * secs))
    out, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= n or (len(cur) >= max(min_words, n * 0.6) and re.search(r"[.!?]$", w)):
            out.append(" ".join(cur)); cur = []
    if cur:
        if out and len(cur) < min_words: out[-1] += " " + " ".join(cur)
        else: out.append(" ".join(cur))
    return out


def write_prompts(cfg, sec, parts, prof, story, log=print):
    """-> [{"piece", "text", "prompt", "motion"}] one per piece. Raises on a malformed answer (the caller logs and moves on)."""
    from .llm import LLM
    st = style_text({k: v for k, v in prof.items() if not k.startswith("_")})
    def chk(x):
        sh = x.get("shots")
        if not isinstance(sh, list) or len(sh) != len(parts): raise ValueError(f"need exactly {len(parts)} shots")
        for s in sh:
            if len(str(s.get("prompt", "")).split()) < 15: raise ValueError("a prompt is too short to stand alone")
    with LLM(cfg, log, lambda: False) as llm:
        j = llm.chat_json("You are a precise storyboard artist for news video. Reply with JSON only.",
                          PROMPTS.format(story=str(story)[:600].replace('"', "'"), style=st.replace('"', "'"), n=len(parts),
                                         pieces="\n".join(f'{i + 1}. "{p}"' for i, p in enumerate(parts)).replace('"', "'")),
                          max_tokens=300 * len(parts) + 200, check=chk)
    out = []
    for i, (p, s) in enumerate(zip(parts, j["shots"])):
        pr = str(s["prompt"]).strip()
        if prof.get("art_style") and prof["art_style"].lower()[:20] not in pr.lower(): pr += f" Style: {st}."   # the lock, if the AI dropped it
        out.append({"piece": i + 1, "text": p, "prompt": pr[:1500], "motion": str(s.get("motion") or "")[:200]})
    return out


def plan(cfg, sd, sec, story, log=print, max_shots=None):
    """Style lock + pieces + prompts for one beat, saved as short/storyboard/<beat>.json (status "planned"). -> the plan dict.
    Raises on failure (the callers log it)."""
    from . import tts
    prof = style_profile(cfg, sd, log)
    parts = pieces(sec.get("vo", ""), tts.wpm(cfg))[: int(max_shots or cfg.get("storyboard_max_shots", 6))]
    if len(parts) < 2: raise ValueError("narration too short to split")
    p = {"style": prof, "shots": write_prompts(cfg, sec, parts, prof, story, log), "status": "planned"}
    (_dir(sd) / f"{sec['id']}.json").write_text(json.dumps(p, indent=1, ensure_ascii=False), encoding="utf-8")
    return p


def saved(sd, bid):
    f = Path(sd) / "storyboard" / f"{bid}.json"
    try: return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
    except ValueError: return None


def beat(cfg, sd, sec, story, log=print, aspect="9:16", max_shots=None, use_saved=False):
    """Storyboard one beat. -> [bg items] ({"type": "image", "src", "tag", "rung": "storyboard", ...}), possibly empty. Never raises
    (cancel aside). Pictures come from the image services, Cloudflare first; a piece without a picture is simply left out.
    use_saved: generate from the plan already saved for this beat (the editor's "check prompts first" path)."""
    from . import imagegen, qc_repair
    sd = Path(sd); bid = sec["id"]
    try:
        p = saved(sd, bid) if use_saved else None
        if not (p and p.get("shots")): p = plan(cfg, sd, sec, story, log, max_shots)
        prof, shots = p["style"], p["shots"]
    except Exception as e:
        if str(e) == "cancelled": raise
        log(f"  {bid}: storyboard failed ({type(e).__name__}: {str(e)[:120]}); next rung"); return []
    p["status"] = "generated"
    (_dir(sd) / f"{bid}.json").write_text(json.dumps(p, indent=1, ensure_ascii=False), encoding="utf-8")
    c = qc_repair._cfg_no_google(cfg); items = []
    for s in shots:
        key = f"{bid}_sb{s['piece']}"
        res = imagegen.generate_many(c, sd, {"id": bid, "vo": s["text"], "described_prompt": s["prompt"]}, key, log, aspect=aspect)
        if not res: log(f"  {bid}: storyboard piece {s['piece']}: no image service produced a picture"); continue
        site = imagegen.last_site() or "image service"
        items.append({"type": "image", "src": str(Path(res[0][0]).resolve().relative_to(sd.resolve())).replace("\\", "/"), "fit": "frame",
                      "tag": f"GENERATED · {str(site).upper()}", "rung": "storyboard", "site": site, "piece": s["piece"],
                      "text": s["text"], "motion": s["motion"]})
    log(f"  {bid}: storyboard {len(items)} of {len(shots)} picture(s), style locked ({prof.get('_from')})")
    return items
