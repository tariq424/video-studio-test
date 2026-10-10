"""Vertical YouTube Short (2-3 min): script -> stock footage (Pexels, auto-vetted) -> narration -> Remotion render.
Almost no GPU: only the narration (WanGP TTS) and the clip vetting (small vision model) touch the GPU."""
import base64, io, json, math, os, re, shutil, subprocess, time
from pathlib import Path
import requests
from . import config, media
from .llm import LLM, parse_json
from .writer import SYSTEM, make_notes, fact_check

GAP, TAIL, MAX_SECS = 0.35, 2.2, 176.0   # YouTube Shorts allow up to 180 s; keep a margin
SMOKE_WORDS = 58   # smoke-test Short: 2 beats of narration (the model runs ~10% long); with the ~12-word closing line about 75 words (~30 s)
KINDS = {"hook", "quote", "stat", "compare", "icons", "timeline"}

SHORT = """You are writing a vertical YouTube Short of about {secs} seconds (about {words} words of narration in total)
that condenses "{title}" by {channel}. The goal: a viewer who watches only this Short understands the main ideas and the
most striking facts, and wants more.

People in the source (use these full names and spellings; captions often mishear names): {people}

NOTES ON THE SOURCE (use only these facts):
{notes}

Write {nb} beats that tell one story. Each beat is 30-48 words (about 11-17 seconds spoken). The total must be {words} words (+/- 5%);
YouTube Shorts are cut off at 3 minutes, so do not go over.
- Beat 1 is the hook: one short line framing what this is (who is talking, about what), then the most surprising claim or number,
  in plain words (no jargon in the first sentence). No greetings, no "in this video".
- Tell events in the order they happened. Once the story has moved on (e.g. the plane has landed), don't go back to an earlier
  moment (what happened in the air) in a later beat; put background and reactions after the events, clearly as such.
- Middle beats: the strongest points, ONE idea per beat (never two unrelated topics in one beat), concrete (numbers, names, examples).
  Attribute opinions and predictions to who said them (first name is fine in narration).
- Last beat: the payoff / biggest takeaway, ending on a strong line.
Narration: spoken, punchy, short sentences, plain words, numbers written as spoken words ("ten billion dollars", "twenty thirty").
No markdown, no stage directions. Never invent numbers, quotes or names.

For each beat also give:
- "graphics": 1 or 2 on-screen graphics. The first appears as the beat starts ("at": null). An optional second one appears when
  the word in "at" is spoken ("at" must be ONE word that appears in that beat's narration, from its second half). Kinds:
   {{"kind":"hook","lines":["2-4 lines of at most 3 words each, in capitals"],"accent":1}}   (accent = index of the line to highlight; use for beat 1 and big questions)
   {{"kind":"quote","text":"max 16 words","who":"speaker name"}}
   {{"kind":"stat","value":5,"decimals":0,"prefix":"","suffix":"x","label":"2-4 words","sub":"optional short line"}}
   {{"kind":"compare","badge":"vs","note":"short source line","left":{{"icon":"one emoji","head":"1-3 words","body":"2-5 words"}},"right":{{"icon":"one emoji","head":"1-3 words","body":"2-5 words"}}}}
   {{"kind":"icons","title":"short title","items":[{{"icon":"one emoji","label":"1-2 words"}}]}}   (3-4 items)
   {{"kind":"timeline","title":"short title","steps":[{{"when":"1-2 words","label":"2-4 words"}}]}}   (3 steps)
  Vary the kinds across beats. Keep all graphic text short. Quotes and stats name the person in full ("who"/"sub").
  A stat must be a real quantity from the notes (a percentage, multiple, count, amount): never a model version, year or name.
  The number counts up on screen, so "prefix"/"suffix" are only symbols or units ("$", ">", "%", "x", "B"), never numbers or ranges.
- "queries": 2 stock-video search phrases (3-5 words each) for what to SHOW while this beat plays. Be specific and visual:
  subject + action + setting, people doing things where possible, e.g. "hands signing contract close-up", "trader watching
  stock screens", "surgeon in operating room", "students walking campus". No abstract words ("AI", "future", "concept",
  "technology", "innovation"), no famous people, nothing that is mostly text. Match the MOOD and the PLACE of the beat: for an
  emergency, attack or crisis ask for tense, urgent scenes ("emergency lights flashing at night", "worried passengers holding
  armrests"), never routine or happy ones; for a named country ask for that country ("jerusalem city skyline", not "parliament
  building"), or for something neutral if you can't (a map, a newsroom, a radar screen). When the beat is about a named
  government, agency or official, ask for places, documents or screens ("kremlin at night", "classified folder on desk"),
  never for a person who would be taken to be that official or agent. No brand names, EXCEPT when the beat has a
  "subject": then include the subject's brand and model in the phrases (e.g. "flydubai plane landing", "flydubai boeing 737").
- "subject": set it ONLY when viewers would expect to SEE one specific identifiable real thing during this beat - a particular
  airline's aircraft, a car make and model, a named product, ship, building or landmark - as
  {{"name": "flydubai Boeing 737", "brand": "flydubai"}} or {{"name": "Mitsubishi Outlander Sport", "brand": "Mitsubishi"}}.
  Footage is then used only if it shows exactly that. Otherwise null. Never set a subject for a person.
- "backdrop": a full-screen graphic shown when no footage fits this beat. If the beat is about places, a route or a journey, use a map:
   {{"kind":"map","title":"2-5 words","points":[{{"name":"Dubai","lat":25.25,"lon":55.36,"role":"origin"}},{{"name":"Tel Aviv","lat":32.01,"lon":34.89,"role":"planned"}},{{"name":"Tabuk","lat":28.37,"lon":36.62,"role":"actual"}}]}}
   (role: "origin", "planned" = intended destination shown dashed, "actual" = where it really went, "stop" = a place on the way,
   "place" = just a location; real coordinates in decimal degrees). Otherwise a headline card:
   {{"kind":"headline","kicker":"1-3 words","text":"4-9 words summing up the beat","sub":"optional 3-8 words"}}
- "still_prompt": a 30-50 word prompt for a photorealistic AI image of THIS beat, vertical framing. Describe the subject, the
  setting and the mood, at the exact moment the narration describes (e.g. if the plane dropped, it is diving steeply; if it sat on
  the tarmac, it is parked with emergency vehicles around; tense, never cheerful, for an emergency). The AI garbles marks, so
  NEVER ask for any text, letters, numbers, logos, brand names, airline names or livery lettering, flags, registrations, signs
  or real people's faces (describe generic people from behind or at a distance). For a subject, describe it by type, shape
  and colours only (e.g. "a white single-aisle passenger jet with a plain dark blue tail, descending steeply through clouds").
- "motion": 8-15 words for animating that image for 7 seconds: what moves and how the camera moves
  (e.g. "the jet banks and descends through clouds, camera tracks alongside"). Slow, physically plausible motion.
Also give "title" (max 60 chars, YouTube title), "tag" (max 28 chars, small label shown at the top, e.g. "MOONSHOTS #293 · CONDENSED"),
"description" (2-3 sentences for YouTube that credit {channel} and the original), and "source_spoken": how a narrator would
name the source in a sentence, e.g. "the Moonshots podcast, episode two ninety-three" or "a NotebookLM briefing on battery recycling".

Reply with ONLY JSON:
{{"title":"...","tag":"...","description":"...","source_spoken":"...","beats":[{{"vo":"...","graphics":[{{"at":null,"g":{{...}}}},{{"at":"word","g":{{...}}}}],"queries":["...","..."],"subject":null,"backdrop":{{...}},"still_prompt":"...","motion":"..."}}]}}"""

def _log_none(m): pass

def _clean_backdrop(bd, vo):
    """Validate the script AI's fallback graphic; anything malformed becomes a headline card."""
    if isinstance(bd, dict) and bd.get("kind") == "map":
        pts = []
        for p in bd.get("points") or []:
            try:
                lat, lon = float(p["lat"]), float(p["lon"])
                if -85 <= lat <= 85 and -180 <= lon <= 180:
                    pts.append({"name": str(p.get("name", ""))[:28], "lat": lat, "lon": lon,
                                "role": p.get("role") if p.get("role") in ("origin", "planned", "actual", "stop", "place") else "place"})
            except Exception: continue
        if len(pts) >= 1: return {"kind": "map", "title": str(bd.get("title", ""))[:40], "points": pts[:6]}
    if isinstance(bd, dict) and bd.get("kind") == "headline" and bd.get("text"):
        return {"kind": "headline", "kicker": str(bd.get("kicker", ""))[:24], "text": str(bd["text"])[:80], "sub": str(bd.get("sub", ""))[:60]}
    words = vo.split()
    return {"kind": "headline", "kicker": "", "text": " ".join(words[:9]).rstrip(",.;") + ("..." if len(words) > 9 else ""), "sub": ""}

def _quote_in_source(text, transcript_words):
    """True if (nearly) all content words of a quote appear close together in the transcript."""
    want = [re.sub(r"[^a-z0-9]", "", w.lower()) for w in text.split()]
    want = [w for w in want if len(w) > 2]
    if not want: return True
    tw = [re.sub(r"[^a-z0-9]", "", w.lower()) for w in transcript_words]
    span = max(12, len(want) * 3)
    best = 0
    idx = {}
    for i, w in enumerate(tw): idx.setdefault(w, []).append(i)
    for start in idx.get(want[0], []) + idx.get(want[-1], []):
        win = set(tw[max(0, start - span):start + span])
        best = max(best, sum(1 for w in want if w in win) / len(want))
        if best >= 0.85: return True
    return best >= 0.85

def verify_quotes(plan, transcript, log):
    """Quote cards must be words actually said. A quote that can't be found in the source becomes a headline card
    (paraphrase) instead of being shown in quotation marks."""
    tw = transcript.split()
    for s in plan["sections"]:
        for v in s.get("visuals", []):
            g = v.get("chart") or {}
            if g.get("kind") == "quote" and not _quote_in_source(g.get("text", ""), tw):
                words = g.get("text", "").upper().split()
                lines = [" ".join(words[i:i + 3]) for i in range(0, min(len(words), 9), 3)]
                log(f"  quote not found in the source, shown as a headline instead: \"{g.get('text', '')[:70]}\"")
                v["chart"] = {"kind": "hook", "lines": lines or ["KEY POINT"], "accent": len(lines) - 1}
    return plan

# ---------------------------------------------------------------- script
def write_short(cfg, meta, transcript, secs, mode, long_title, log, stop, srcdir, smoke=False):
    wpm = cfg.get("voice_wpm", 155)
    # target = narration + a pause after each beat + the end tail + the closing line (~16 words); size the story to fill the rest
    words = int((secs - TAIL - GAP * 9 - 16 / wpm * 60) * wpm / 60)
    nb = max(7, min(12, round(words / 38)))
    minb, lo, hi = 6, 0.95, 1.05
    if smoke: words, nb, minb, lo, hi = SMOKE_WORDS, 2, 2, 0.8, 1.2   # smoke test: ~75 words in all with the closing line (~30 s spoken)
    title, channel = meta.get("title") or "the source", meta.get("channel") or meta.get("uploader") or "the creator"
    with LLM(cfg, log, stop) as llm:
        log(f"Writing the Short with {llm.name} (~{secs:.0f}s, {words} words, {nb} beats)...")
        notes = make_notes(llm, meta, transcript, max(words, 1500), log, stop, srcdir)
        tries = []   # every parsed attempt, so a near miss can be kept instead of an unchecked re-ask
        def chk(j):
            b = j.get("beats")
            if not isinstance(b, list) or len(b) < minb: raise ValueError(f"need at least {minb} beats")
            for x in b:
                if not isinstance(x.get("vo"), str) or not x.get("queries"): raise ValueError("beat missing vo or queries")
            n = sum(len(x["vo"].split()) for x in b)
            tries.append((abs(n - words), j))
            if n < words * lo: raise ValueError(f"narration is {n} words in total but must be about {words}; add detail from the notes")
            if n > words * hi: raise ValueError(f"narration is {n} words in total but must be at most {int(words * 1.05)}; cut weaker points")
        prompt = SHORT.format(secs=int(secs), words=words, title=title, channel=channel, notes=notes[:24000], nb=nb,
                              people=(meta.get("description") or "")[:1200] or "(see notes)")
        try: j = llm.chat_json(SYSTEM, prompt, max_tokens=8000, check=chk)
        except RuntimeError:
            if tries:
                j = min(tries, key=lambda x: x[0])[1]
                log(f"  length still off after 3 tries; keeping the closest ({sum(len(x['vo'].split()) for x in j['beats'])} words, target {words})")
            else:
                log("  no usable script after 3 tries; asking once more without the length check")
                j = llm.chat_json(SYSTEM, prompt, max_tokens=8000, check=lambda x: None if x.get("beats") else (_ for _ in ()).throw(ValueError("no beats")))
        if smoke: j["beats"] = j["beats"][:2]   # a smoke test stays ~30 s even if the length check gave up
        else:   # hard cut: still more than 10% long -> drop whole middle beats (keep the hook and the payoff)
            while len(j["beats"]) > minb and sum(len(x["vo"].split()) for x in j["beats"]) > words * 1.1:
                cut = j["beats"].pop(-2); log(f"  script too long; dropped a middle beat ({len(cut['vo'].split())} words)")
        plan = {"target_secs": float(secs), "title": (j.get("title") or title)[:90], "tag": (j.get("tag") or "CONDENSED")[:32].upper(),
                "source_spoken": (j.get("source_spoken") or title)[:120],
                "description": j.get("description", ""), "mode": mode, "sections": []}
        for i, b in enumerate(j["beats"]):
            gs = [g for g in (b.get("graphics") or []) if isinstance(g, dict) and isinstance(g.get("g"), dict) and g["g"].get("kind") in KINDS][:2]
            for g in gs:   # a stat must be a single number; anything else ("30k to 15k") becomes a text card (it rendered as "NaN")
                if g["g"]["kind"] == "stat":
                    try: g["g"]["value"] = float(str(g["g"].get("value")).replace(",", ""))
                    except (TypeError, ValueError):
                        g["g"] = {"kind": "hook", "lines": [str(g["g"].get("value", ""))[:18].upper(), str(g["g"].get("label", ""))[:24].upper()], "accent": 0}
            for g in gs:   # a counting-up number can't carry a range like "$5-10B"
                if g["g"]["kind"] == "stat" and re.search(r"\d", str(g["g"].get("prefix", "")) + str(g["g"].get("suffix", ""))):
                    g["g"]["kind"] = "hook"; g["g"]["lines"] = [f"{g['g'].get('prefix', '')}{g['g'].get('value', '')}{g['g'].get('suffix', '')}", str(g["g"].get("label", "")).upper()]; g["g"]["accent"] = 0
            sj = b.get("subject") if isinstance(b.get("subject"), dict) and str(b["subject"].get("name", "")).strip() else None
            plan["sections"].append({"id": f"b{i}", "title": f"Beat {i + 1}", "vo": re.sub(r"\s+", " ", b["vo"]).strip(),
                                     "queries": [q for q in b.get("queries", []) if isinstance(q, str)][:3] or ["city skyline aerial"],
                                     "subject": sj, "backdrop": _clean_backdrop(b.get("backdrop"), b["vo"]),
                                     "still_prompt": str(b.get("still_prompt") or "")[:500], "motion": str(b.get("motion") or "")[:160],
                                     "visuals": [{"type": "chart", "chart": g["g"], "at": g.get("at")} for g in gs]})
        log("Checking the Short against the source (names, attributions, numbers)...")
        plan = fact_check(llm, plan, meta, transcript, log, stop)
        from . import coherence
        ents = coherence.entities(cfg, Path(srcdir).parent, title, notes, log, stop, llm=llm)
        nl = 0
        for s in plan["sections"]:
            sj, avoid = coherence.assign(ents, " ".join(s["queries"]) + " " + s.get("still_prompt", ""))
            if sj or not s.get("subject"): s["subject"] = sj
            s["avoid"] = [] if s.get("subject") else avoid
            nl += bool(s.get("subject"))
        if nl: log(f"  {nl} beat(s) locked to a story subject")
    plan = verify_quotes(plan, transcript, log)
    if not smoke:   # the fact-check can lengthen the script after it passed the length check: cut again (render pace covers the last few %)
        while len(plan["sections"]) > minb and sum(len(x["vo"].split()) for x in plan["sections"]) > words * 1.06:
            cut = plan["sections"].pop(-2); log(f"  script grew in the fact-check; dropped a middle beat ({len(cut['vo'].split())} words)")
        for i, x in enumerate(plan["sections"]): x["id"], x["title"] = f"b{i}", f"Beat {i + 1}"
    n = sum(len(x["vo"].split()) for x in plan["sections"])
    if n > words * 1.12: log(f"  NOTE: script is {n} words (target {words}); trim it in review or it will be sped up to fit {f'{secs:.0f} s' if secs < 60 else f'{int(secs) // 60}:{int(secs) % 60:02d}'}")
    # closing call-to-action beat
    src_name = plan.get("source_spoken") or title
    if mode == "both":
        cta_vo = f"That was a short summary of {src_name}. The full breakdown is linked below."
        cta = {"kind": "cta", "badge": "FULL BREAKDOWN", "title": long_title or plan["title"], "line": "Watch it, linked below"}
    else:
        cta_vo = f"That was a short summary of {src_name}. Follow for more."
        cta = {"kind": "cta", "badge": "SUMMARIZED FROM", "title": title[:80], "line": "Follow for more", "play": False, "arrow": False}
    plan["sections"].append({"id": f"b{len(plan['sections'])}", "title": "Call to action", "vo": cta_vo, "queries": [], "cta": cta, "visuals": []})
    w = sum(len(s["vo"].split()) for s in plan["sections"])
    log(f"Short script ready: {len(plan['sections'])} beats, {w} words (~{w / cfg['wpm'] * 60 + GAP * len(plan['sections']) + TAIL:.0f}s)")
    return plan

# ---------------------------------------------------------------- stock footage
def do_stock(job, plan, cfg, log, stop):
    """Pexels + Pixabay (+ NASA for space beats): ranked by meaning, checked by the vision model, cut at high quality."""
    from . import footage
    d = job / "short" / "stock"
    slots, need = [], {}
    for s in plan["sections"]:
        if s.get("cta"):
            slots.append({"id": s["id"], "text": "calm, general background for the closing end card", "queries": ["city skyline dusk aerial", "night sky stars timelapse"]})
            need[s["id"]] = 1
        elif s.get("subject"):
            continue   # locked to a specific subject: stock libraries don't have it; real photos / reconstruction come in short_fallback
        else:
            secs = len(s["vo"].split()) / cfg.get("voice_wpm", 142) * 60 + GAP
            slots.append({"id": s["id"], "text": s["vo"], "queries": s["queries"], "subject": s.get("subject"), "avoid": s.get("avoid") or []})
            need[s["id"]] = max(2, min(3, math.ceil(secs / 6.0)))
    picked = footage.fill(cfg, slots, "portrait", need, d, log, stop, want_long_side=2560, max_secs=10.0, state_file=d / "footage.json", fallback=True)
    for s in plan["sections"]:
        if s.get("subject") and not s.get("cta"): picked.setdefault(s["id"], [])
    (d / "pick.json").write_text(json.dumps(picked, indent=1), encoding="utf-8")
    n = sum(len(v) for v in picked.values()); short_ = [k for k, v in picked.items() if len(v) < need.get(k, 0)]
    log(f"Stock footage: {n} clips ready" + (f"; fewer than wanted for {', '.join(short_)}" if short_ else ""))

# ---------------------------------------------------------------- fallback visuals (no matching footage)
FB_SECS = 7.0   # screen time one fallback visual covers

def _needs(plan, tm, pick, sd, cfg):
    """Beats whose footage doesn't cover them and that may not borrow other beats' clips: subject-locked beats, or any beat
    when there is no footage at all. -> {beat_id: number of fallback visuals}"""
    pool = [c for v in pick.values() for c in v]
    out = {}
    for s in plan["sections"]:
        if s.get("cta") or s["id"] not in tm: continue
        have = sum(_clip_len(sd, c) / 0.85 for c in pick.get(s["id"], []))
        rem = tm[s["id"]]["dur"] + GAP - have
        if rem > 0.5:   # never fill with another beat's footage: it illustrates a different sentence
            out[s["id"]] = max(1, min(3, math.ceil(rem / FB_SECS)))
    return out

def depth_free(img, prefix, size=(1080, 1920)):
    """Single-layer fallback when depth estimation is unavailable: the still, cropped to the frame."""
    from PIL import Image
    im = Image.open(img).convert("RGB"); W, H = size; r = max(W / im.width, H / im.height)
    im = im.resize((int(im.width * r + 0.5), int(im.height * r + 0.5)))
    x0, y0 = (im.width - W) // 2, (im.height - H) // 2
    p = Path(f"{prefix}_L0.jpg"); im.crop((x0, y0, x0 + W, y0 + H)).save(p, quality=92)
    return [p]

def do_fallback(job, plan, cfg, wg, log, stop, full=False, dbg=None):
    """The visual ladder for beats that step 1 didn't cover (stock footage for generic beats, real photos for subject beats):
    2a cloud still (Gemini -> ChatGPT, GENERATED · CLOUD) -> 2b WanGP still -> 3 WanGP image-to-video (on click only) -> 4 parallax of the
    still (PARALLAX) -> 5 3D reconstruction / headline card.
    Every step is checked against the beat's narration (ladder.py); a failed check escalates. A beat's map backdrop (geography)
    is kept as its first visual. Writes short/fallback.json = {beat: [bg items]} and logs one ladder line per beat.
    Also writes short/fallback/chains.json (every beat's decision chain: stock found, what was tried and why it failed, what is used)
    for the debugger and the trace. dbg (debug.Debugger): safe points for 'Pause now'; with breakpoints on, beats run one at a time
    and each is checked after its visuals are decided (normal runs keep the batched GPU order)."""
    from . import depth, coherence, photos, ladder, cloudgen
    sd = job / "short"; fd = sd / "fallback"; fd.mkdir(parents=True, exist_ok=True)
    tm = json.loads((sd / "timings.json").read_text(encoding="utf-8"))
    pick = json.loads((sd / "stock" / "pick.json").read_text(encoding="utf-8"))
    fsf = sd / "stock" / "footage.json"; fst = json.loads(fsf.read_text(encoding="utf-8")) if fsf.exists() else {}
    ff = sd / "fallback.json"; out = json.loads(ff.read_text(encoding="utf-8")) if ff.exists() else {}
    cf = fd / "chains.json"; chs = json.loads(cf.read_text(encoding="utf-8")) if cf.exists() else {}
    def save_out(): ff.write_text(json.dumps(out, indent=1), encoding="utf-8"); cf.write_text(json.dumps(chs, indent=1), encoding="utf-8")
    allneeds = base_needs = _needs(plan, tm, pick, sd, cfg)
    if full:   # Review every beat: every beat gets the whole menu, also the ones stock footage already covers (one slot)
        allneeds = {s["id"]: allneeds.get(s["id"], 1) for s in plan["sections"] if not s.get("cta") and s["id"] in tm}
    needs = {k: v for k, v in allneeds.items() if k not in out}
    beats = [s for s in plan["sections"] if not s.get("cta") and s["id"] in tm]
    def srej(bid): return [{"id": r.get("id"), "why": r.get("why", "")} for r in fst.get("rejected", {}).get(bid, [])][:12]
    def stock_beat(sec):
        bid = sec["id"]
        if bid in chs: return
        k = len(pick.get(bid, []))
        chs[bid] = {"n": int(bid[1:]) + 1, "vo": sec["vo"], "stock_found": k, "chain": [f"stock ({k} clip(s), coherent)"], "uses": ["stock"],
                    "failed": [], "stock_rejected": srej(bid), "photos_rejected": []}
    def info(sec):
        c = chs.get(sec["id"], {})
        return {"bid": sec["id"], "n": int(sec["id"][1:]) + 1, "vo": sec["vo"], "stock_found": c.get("stock_found", len(pick.get(sec["id"], []))),
                "uses": c.get("uses", []), "failed": c.get("failed", [])}
    log("Visual ladder per beat (1 stock/photo -> 2 cloud still -> 3 WanGP still -> 4 parallax -> 5 reconstruction / headline; animate on click):")
    for s in beats:   # beats step 1 covered on its own
        if s["id"] in base_needs: continue
        log(f"  {s['id']}: stock ({len(pick.get(s['id'], []))} clip(s), coherent)"); stock_beat(s)
    if not needs and not dbg:
        log("  no other beats need visuals"); save_out(); return
    ents = json.loads((job / "entities.json").read_text(encoding="utf-8")) if (job / "entities.json").exists() else []
    phases = coherence.beat_phases([x for x in plan["sections"] if not x.get("cta")])
    pre, step1, slots, prej = {}, {}, [], {}

    def prepare(s):
        n = needs[s["id"]]; items = []; rej = []
        bd = s.get("backdrop") or {"kind": "headline", "kicker": "", "text": s["vo"][:60], "sub": ""}
        if bd.get("kind") == "map": items.append({"type": "graphic", "g": bd, "rung": "map"})
        have = len(pick.get(s["id"], []))
        why1 = f"only {have} coherent stock clip(s)" if have else "no coherent stock"
        if s["id"] not in base_needs: why1 = ""   # stock covers this beat; the other treatments are made for the review menu
        if s.get("subject"):   # step 1 for a subject beat: real licensed photos of it (FILE), only where a photo can show this moment
            inside = s["subject"].get("interior") or re.search(r"\b(cockpit|flight deck|pilots?|captain)\b", " ".join(s["queries"]), re.I)
            bp = phases.get(s["id"], ""); pics = []
            if inside: why1 = "inside the aircraft: no real photo of it"
            elif bp == "air": why1 = "in the air: no real photo shows this moment"
            else:
                try: pics = photos.find(cfg, s["subject"], sd / "photos", log, want=10)
                except Exception as e: log(f"  photo search failed ({str(e)[:100]})")
                rej += photos.rejected(s["subject"], sd / "photos")
                fit = [pc for pc in pics if coherence.phase_ok(bp, pc.get("phase"))]
                rej += [{"id": pc["id"], "title": pc.get("title", "")[:80], "path": pc.get("path", ""),
                         "why": f"shows the subject {pc.get('phase') or 'at another moment'}, the beat is {bp or 'another moment'}"} for pc in pics if pc not in fit]
                why1 = ("no usable photo" if not pics else f"no photo shows it {bp or 'in this situation'}") if not fit else ""
                pics = fit
            used = {i.get("photo") for v in out.values() for i in v if i.get("photo")}
            for pc in pics:
                if len(items) >= n: break
                if pc["id"] in used: continue
                dst = fd / f"{pc['id']}.jpg"
                if not dst.exists(): shutil.copy2(pc["path"], dst)
                items.append({"type": "image", "src": str(dst.relative_to(sd)).replace("\\", "/"), "fit": "frame", "rung": "photo",
                              "photo": pc["id"], "credit": photos.credit(pc), "short_credit": photos.short_credit(pc)}); used.add(pc["id"])
            if len(items) < n and pics: why1 = "not enough matching photos"
        pre[s["id"]] = items; step1[s["id"]] = ("photo" if s.get("subject") else "stock", why1); prej[s["id"]] = rej
        rot = coherence.attitude_rotation(s["vo"], phases.get(s["id"])) if s.get("subject") else None
        for k in range(n - len(items)):
            slots.append({"key": f"{s['id']}_{k}", "beat": s["id"], "vo": s["vo"], "still_prompt": s.get("still_prompt", ""),
                          "motion": s.get("motion", ""), "subject": s.get("subject"), "rotate": rot,
                          "person": cloudgen.has_person(s["vo"], ents)})

    def finalize(s, st):
        items = pre[s["id"]]; bd = s.get("backdrop") or {}
        cap = bd.get("text", "") if bd.get("kind") == "headline" else bd.get("title", "")
        rung1, why1 = step1[s["id"]]
        lines, k5, failed = [], 0, ([rung1] if why1 else [])
        for sl in [x for x in slots if x["beat"] == s["id"]]:
            r = st.get(sl["key"], {}); chain = [rung1]; why = [f"{rung1}: {why1}"] if why1 else []
            cloud = r.get("src") == "cloud"
            if "cloud" in r and not cloud:   # cloud tried (or skipped) and gave nothing usable: WanGP's still is next
                chain.append("cloud"); why.append(f"cloud: {r.get('cloud_why') or 'failed'}"); failed.append("cloud")
            chain.append(f"cloud still ({r.get('cloud_provider')})" if cloud else "still")
            gtag = "GENERATED · CLOUD" if cloud else "GENERATED"
            sw = str(r.get("still_why") or "")
            if sl.get("rotate") is not None and r.get("still") and not cloud and not sw.startswith("garbled"):
                # directional beat: the image model's nose angle is random, so the still is turned by the narration's verb and given
                # parallax; it is rejected only when garbled (the attitude check can't judge it)
                img = sd / r["still"]; deg = sl["rotate"]
                if deg:
                    img = rotate_still(img, deg, r.get("nose", "right"), fd / f"{sl['key']}_rot.jpg"); chain.append(f"rotate {deg:.0f}°")
                chain.append("parallax"); pre_ = fd / f"{sl['key']}_r"
                try: lay = depth.layers(img, pre_, log)
                except Exception as e: log(f"  depth layers failed ({str(e)[:80]}); held with a slow zoom"); lay = depth_free(img, pre_)
                items.append({"type": "layers", "layers": [_rel_sd(p, sd) for p in lay], "tag": "GENERATED · PARALLAX", "rung": "parallax"})
                if not r.get("still_ok"): why.append(f"still check ignored for a directional beat ({sw[:60]})")
                lines.append(" -> ".join(chain) + (f"  ({'; '.join(why)})" if why else "")); continue
            if not r.get("still_ok") and r.get("still") and sw.startswith("shows text"):
                # only marks (lettering/logo) - not a contradiction of the narration: hold the still with a slow zoom
                chain.append("hold"); why.append(f"still: {sw}"); failed.append("still")
                lay = depth_free(sd / r["still"], fd / f"{sl['key']}_hold")
                items.append({"type": "layers", "layers": [_rel_sd(p, sd) for p in lay], "tag": gtag, "rung": "still", "cloud": cloud})
                lines.append(" -> ".join(chain) + f"  ({'; '.join(why)})"); continue
            if r.get("still_ok"):
                if "clip" in r: chain.append("animate")   # animation only exists after an explicit click
                if r.get("clip_ok"):
                    items.append({"type": "video", "src": r["clip"], "secs": round((r.get("clip_secs") or FB_SECS) / 0.85, 2), "tag": "GENERATED", "rung": "animate"})
                    lines.append(" -> ".join(chain) + (f"  ({'; '.join(why)})" if why else "")); continue
                if "clip" in r: why.append(f"animate: {r.get('clip_why') or 'not run'}"); failed.append("animate")
                chain.append("parallax")
                img = sd / r["still"]; pre_ = fd / sl["key"]
                try: lay = depth.layers(img, pre_, log)
                except Exception as e:
                    log(f"  depth layers failed ({str(e)[:80]}); still held with a slow zoom"); lay = depth_free(img, pre_)
                items.append({"type": "layers", "layers": [_rel_sd(p, sd) for p in lay], "tag": "GENERATED · CLOUD" if cloud else "GENERATED · PARALLAX",
                              "rung": "parallax", "cloud": cloud})
            else:
                why.append(f"still: {r.get('still_why') or 'not made'}"); failed.append("still")
                if s.get("subject"):
                    chain.append("reconstruction")
                    items.append({"type": "graphic", "g": coherence.recon(s["subject"], ents, s["vo"], k5, cap if k5 == 0 else "", moment=phases.get(s["id"], "")), "rung": "reconstruction"}); k5 += 1
                else:
                    chain.append("headline")
                    items.append({"type": "graphic", "g": bd if bd.get("kind") == "headline" else {"kind": "headline", "kicker": "", "text": s["vo"][:70], "sub": ""}, "rung": "headline"})
            lines.append(" -> ".join(chain) + (f"  ({'; '.join(why)})" if why else ""))
        # an animation can come out shorter than planned: never let a clip run out, end on something that can stretch
        rem = tm[s["id"]]["dur"] + GAP - sum(_clip_len(sd, c) / 0.85 for c in pick.get(s["id"], []))
        if items and sum(i.get("secs", FB_SECS) for i in items) < rem and items[-1]["type"] == "video":
            still = next((st[x["key"]]["still"] for x in slots if x["beat"] == s["id"] and st.get(x["key"], {}).get("still_ok")), None)
            if still:
                lay = depth_free(sd / still, fd / f"{s['id']}_tail")
                items.append({"type": "layers", "layers": [_rel_sd(p, sd) for p in lay], "tag": "GENERATED · CLOUD" if str(still).startswith("fallback/cloud_") else "GENERATED · PARALLAX", "rung": "parallax (fill)"})
        if not items: items.append({"type": "graphic", "g": {"kind": "headline", "kicker": "", "text": s["vo"][:70], "sub": ""}, "rung": "headline"})
        items = [it for j, it in enumerate(items) if not (j and it["rung"] == "headline" and items[j - 1]["rung"] == "headline")]   # one card stretches
        out[s["id"]] = items
        if not lines: lines = [f"{rung1}" + (f"  ({rung1}: {why1})" if why1 else "")]
        got = ", ".join(i["rung"] for i in items)
        for j, ln in enumerate(lines): log(f"  {s['id']}{'#' + str(j + 1) if len(lines) > 1 else ''}: {ln}")
        log(f"  {s['id']} uses: {got}")
        chs[s["id"]] = {"n": int(s["id"][1:]) + 1, "vo": s["vo"], "stock_found": len(pick.get(s["id"], [])), "chain": lines,
                        "uses": [i["rung"] for i in items] + (["cloud"] if any(i.get("cloud") for i in items) else []),
                        "failed": sorted(set(failed)), "stock_rejected": srej(s["id"]), "photos_rejected": prej.get(s["id"], []),
                        "cloud": [{"slot": x["key"], "provider": st.get(x["key"], {}).get("cloud_provider"), "why": st.get(x["key"], {}).get("cloud_why", ""),
                                   "tries": st.get(x["key"], {}).get("cloud_tries", [])} for x in slots if x["beat"] == s["id"] and "cloud" in st.get(x["key"], {})]}
        save_out()

    pause = (lambda: dbg.manual("short_fallback: AI stills")) if dbg else None
    if dbg and dbg.active():   # debug: one beat at a time, so a breakpoint stops right after the beat it is about
        log("  debug on: beats run one at a time; breakpoints are checked after each beat")
        for s in beats:
            if stop(): raise RuntimeError("cancelled")
            if s["id"] in needs and s["id"] not in out:
                first = len(slots); prepare(s); sl = slots[first:]
                st = ladder.run(cfg, wg, sd, fd, sl, log, stop, bool(sl) and wg.alive(), seed=5100 + first, full=full, pause=pause) if sl else {}
                if sl and not wg.alive(): log("  WanGP isn't reachable: cloud stills only")
                finalize(s, st)
            elif s["id"] not in needs: stock_beat(s)
            save_out(); dbg.point(info(s))
        return
    for s in beats:
        if s["id"] in needs:
            if stop(): raise RuntimeError("cancelled")
            prepare(s)
    run_slots = slots
    gpu = bool(run_slots) and wg.alive()
    if run_slots and not gpu: log("  WanGP isn't reachable: cloud stills only" if cfg.get("cloud_on", True) else "  WanGP isn't reachable: skipping steps 2-4")
    st = ladder.run(cfg, wg, sd, fd, run_slots, log, stop, gpu, full=full, pause=pause) if run_slots else {}
    for s in beats:
        if s["id"] in needs: finalize(s, st)
        elif s["id"] not in out: stock_beat(s)
        if dbg: save_out(); dbg.point(info(s))
    save_out()

def rotate_still(src, deg, nose, dst):
    """Turn a still `deg` degrees nose-down (nose = the side of the picture the aircraft points to) and crop to fill the frame
    (no empty corners; a heavier crop at larger angles)."""
    import math
    from PIL import Image
    im = Image.open(src).convert("RGB"); W, H = im.size; t = math.radians(abs(deg))
    s = max(math.cos(t) + (H / W) * math.sin(t), (W / H) * math.sin(t) + math.cos(t))
    cw = deg if nose != "left" else -deg   # nose to the right: clockwise lowers it
    big = im.resize((int(W * s), int(H * s)), Image.LANCZOS).rotate(-cw, resample=Image.BICUBIC, expand=False)
    x0, y0 = (big.width - W) // 2, (big.height - H) // 2
    big.crop((x0, y0, x0 + W, y0 + H)).save(dst, quality=93)
    return Path(dst)

def _rel_sd(p, sd): return str(Path(p).relative_to(sd)).replace("\\", "/")


# ---------------------------------------------------------------- narration + timings
BATCH_WORDS = 115   # ~48 s of speech per TTS call: each WanGP call costs ~32 s of fixed overhead, so fewer, longer calls

def _batches(sections, limit=BATCH_WORDS):
    out, cur, n = [], [], 0
    for s in sections:
        w = len(s["vo"].split())
        if cur and n + w > limit: out.append(cur); cur, n = [], 0
        cur.append(s); n += w
    if cur: out.append(cur)
    return out

def do_voice(job, plan, cfg, wg, log, stop):
    """Narration in a few long TTS calls (several beats each), then split back into one wav per beat at the pauses
    between beats, using whisper word timings on the batch audio. Writes voice/<beat>.wav and timings.json."""
    import unicodedata
    from . import captions
    sd = job / "short"; vd = sd / "voice"; vd.mkdir(parents=True, exist_ok=True)
    tf = sd / "timings.json"
    t = json.loads(tf.read_text(encoding="utf-8")) if tf.exists() else {}
    todo = [s for s in plan["sections"] if s["id"] not in t]
    groups = _batches(todo)
    if groups: log(f"Narration: {len(todo)} beats in {len(groups)} voice call(s)")
    seed = 9100
    for gi, grp in enumerate(groups):
        if stop(): raise RuntimeError("cancelled")
        text = " ".join(s["vo"] for s in grp)
        ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()   # WanGP mangles non-ASCII
        bw = vd / f"batch_{grp[0]['id']}.wav"
        if not media.ok(bw):
            r = None
            for attempt in range(3):
                seed += 1
                r = wg.gen({"model_type": cfg["tts_model"], "prompt": ascii_text, "audio_prompt_type": "A", "audio_guide": cfg["voice_ref_wav"],
                            "alt_prompt": cfg["voice_ref_text"], "model_mode": "english", "duration_seconds": 60,
                            "temperature": 0.7, "top_k": 50, "seed": seed + attempt * 77}, log, f"voice {grp[0]['id']}-{grp[-1]['id']}", stop=stop)
                if not r["ok"]: raise RuntimeError(f"narration failed: {r['err']}")
                try: wps = len(text.split()) / max(media.dur(r["file"]), 0.1)
                except Exception: wps = 0
                if 1.7 <= wps <= 3.8: break
                log(f"  voice batch {gi + 1}: odd pace ({wps:.1f} words/s), re-rendering")
            media.ff("-i", r["file"], "-ar", 48000, "-ac", 2, bw)
        # split at the middle of the pause between beats
        wt = captions.word_times(bw, text)
        D = media.dur(bw); k = 0; spans = []
        for s in grp:
            n = len(s["vo"].split()); spans.append((k, k + n)); k += n
        cuts = [0.0]
        for i in range(1, len(grp)):
            end_prev = wt[spans[i - 1][1] - 1][2]; start_next = wt[spans[i][0]][1]
            cuts.append(max(cuts[-1] + 0.5, (end_prev + start_next) / 2))
        cuts.append(D)
        for i, s in enumerate(grp):
            a, b = cuts[i], cuts[i + 1]
            out = vd / f"{s['id']}.wav"
            media.ff("-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", bw, "-ar", 48000, "-ac", 2, out)
            words = [[w, round(max(0.0, x - a), 3), round(max(0.0, y - a), 3)] for w, x, y in wt[spans[i][0]:spans[i][1]]]
            t[s["id"]] = {"dur": round(b - a, 3), "words": words}
            log(f"Narration {s['id']}: {b - a:.1f}s")
        tf.write_text(json.dumps(t, indent=1), encoding="utf-8")
    total = sum(v["dur"] + GAP for v in t.values()) + TAIL
    log(f"Short narration: {total:.0f}s in total")

# ---------------------------------------------------------------- build + render
def _norm(w): return re.sub(r"[^a-z0-9]", "", str(w).lower())

_lens = {}
def _clip_len(sd, c):
    p = sd / "stock" / "clips" / f"{c['id']}.mp4"
    if p not in _lens: _lens[p] = media.dur(p) if p.exists() else 0.0
    return _lens[p]

def build(job, plan, cfg, log):
    sd = job / "short"; pub = sd / "public"; (pub / "media" / "stock").mkdir(parents=True, exist_ok=True)
    tm = json.loads((sd / "timings.json").read_text(encoding="utf-8"))
    pick = json.loads((sd / "stock" / "pick.json").read_text(encoding="utf-8"))
    secs = [s for s in plan["sections"] if s["id"] in tm]
    raw_total = sum(tm[s["id"]]["dur"] + GAP for s in secs) - GAP + TAIL
    speed = 1.0
    tgt = plan.get("target_secs")
    if tgt and abs(raw_total - tgt) > 3:   # land within a few seconds of the chosen length: nudge the narration pace, at most 7% either way
        speed = max(0.93, min(1.07, raw_total / tgt))
        log(f"  narration {raw_total:.0f}s vs target {tgt:.0f}s; pace x{speed:.3f} -> {raw_total / speed:.0f}s")
    if raw_total / speed > MAX_SECS:
        speed = raw_total / (MAX_SECS - 1)
        if speed > 1.12: log(f"  WARNING: narration is {raw_total:.0f}s; even sped up it would exceed 3 minutes. Shorten the script."); speed = 1.12
        log(f"  narration {raw_total:.0f}s is over the Shorts limit; speeding it up {speed:.2f}x")
    pool = [c for v in pick.values() for c in v]
    fbf = sd / "fallback.json"; fallback = json.loads(fbf.read_text(encoding="utf-8")) if fbf.exists() else {}
    ef = job / "entities.json"
    story_subjects = any(e.get("kind") != "person" for e in (json.loads(ef.read_text(encoding="utf-8")) if ef.exists() else []))
    (pub / "media" / "fb").mkdir(parents=True, exist_ok=True)
    from . import review
    rv = review.load(job)
    beats, parts, t, used = [], [], 0.0, []
    for i, s in enumerate(secs):
        last = i == len(secs) - 1
        d = (tm[s["id"]]["dur"] + (TAIL if last else GAP)) / speed
        words = [[w, round(a / speed, 3), round(b / speed, 3)] for w, a, b in tm[s["id"]]["words"]]
        clips = list(pick.get(s["id"]) or [])
        # top up from other beats' clips until the footage covers the beat (clips play at 0.85x speed)
        def cap(cs): return sum(_clip_len(sd, c) / 0.85 for c in cs)
        near = {c["id"] for j in (i - 1, i + 1) if 0 <= j < len(secs) for c in pick.get(secs[j]["id"], [])}
        borrow = [c for c in pool if c["id"] not in near] or pool   # never repeat a neighbouring beat's shot
        k = 0
        borrow = []   # no borrowing: another beat's clip illustrates a different sentence; short_fallback fills the gap instead
        while borrow and cap(clips) < d + 0.3 and k < len(borrow):
            c = borrow[(i * 5 + k) % len(borrow)]; k += 1
            if all(c["id"] != x["id"] for x in clips): clips.append(c)
        bgs = []
        clips = [c for c in clips if _clip_len(sd, c) > 0]
        fb = fallback.get(s["id"], []) if cap(clips) < d - 0.5 else []
        items = [("clip", c, _clip_len(sd, c) / 0.85) for c in clips] + [("fb", x, x.get("secs", FB_SECS)) for x in fb]
        dec = review.final_items(rv, s) if rv else None   # the reviewer's choice for this beat (visual review)
        if dec is not None:
            items = [("clip", x["clip"], _clip_len(sd, x["clip"]) / 0.85) if x["type"] == "stock" else ("fb", x, x.get("secs", FB_SECS)) for x in dec]
            items = [it for it in items if it[0] != "clip" or it[2] > 0]
            if items and sum(it[2] for it in items) < d - 0.3 and any(it[0] == "clip" or it[1]["type"] == "video" for it in items):
                base = list(items)   # chosen footage shorter than the beat: play the choice again rather than run out
                while sum(it[2] for it in items) < d - 0.3 and len(items) < 12: items += base
        eb = rv["beats"].get(s["id"], {}).get("edit") if rv else None   # replaced in the post-render editor: same visual, same fit
        if eb and all(c in rv["cands"] for c in eb["cands"]):
            from . import edit
            lay, _, _ = edit.layout(sd, [rv["cands"][c]["item"] for c in eb["cands"]], d, eb["fit"], s["vo"], edit.filler_for(rv, s["id"]))
            bgs = [edit.to_bg(sd, it, p, s0, story_subjects, dest=pub, used=used) for it, p, s0, _ in lay]; items = []
        caps = [it[2] for it in items]; tot = sum(caps) or 1.0; t0 = 0.0
        for k, (kind, c, cp) in enumerate(items):   # screen time in proportion to length, so no clip runs out early
            if kind == "clip":
                src = sd / "stock" / "clips" / f"{c['id']}.mp4"
                dst = pub / "media" / "stock" / f"{c['id']}.mp4"
                if not dst.exists(): shutil.copy2(src, dst)
                used.append(f"stock/clips/{c['id']}.mp4")
                bg = {"src": f"media/stock/{c['id']}.mp4", "type": "video", "from": round(t0, 3)}
                if story_subjects: bg["tag"] = "ILLUSTRATIVE"   # generic footage in a story about a specific event
                if c.get("orient") == "landscape": bg["fit"] = "frame"
            elif c["type"] == "image":
                used.append(c["src"]); dst = pub / "media" / "fb" / Path(c["src"]).name
                if not dst.exists(): shutil.copy2(sd / c["src"], dst)
                bg = {"type": "image", "src": f"media/fb/{Path(c['src']).name}", "fit": "frame", "credit": c.get("short_credit", ""), "tag": c.get("tag", "FILE"), "from": round(t0, 3)}
                if not bg["tag"]: del bg["tag"]
            elif c["type"] == "video":   # WanGP image-to-video (ladder step 3), or your own clip
                used.append(c["src"]); dst = pub / "media" / "fb" / Path(c["src"]).name
                if not dst.exists(): shutil.copy2(sd / c["src"], dst)
                bg = {"type": "video", "src": f"media/fb/{Path(c['src']).name}", "tag": c.get("tag", "GENERATED"), "from": round(t0, 3)}
                if not bg["tag"]: del bg["tag"]
            elif c["type"] == "layers":
                srcs = []
                for lp in c["layers"]:
                    used.append(lp); dst = pub / "media" / "fb" / Path(lp).name
                    if not dst.exists(): shutil.copy2(sd / lp, dst)
                    srcs.append(f"media/fb/{Path(lp).name}")
                bg = {"type": "layers", "layers": srcs, "from": round(t0, 3)}
                if c.get("tag"): bg["tag"] = c["tag"]
            else:
                bg = {"type": "graphic", "g": c["g"], "from": round(t0, 3)}
            t0 += d * cp / tot if tot >= d else min(cp, d - t0)
            bgs.append(bg)
        # graphics: first at the beat start, the second when its word is spoken
        gfx = []
        if s.get("cta"): gfx = [{"at": 0.2, "g": s["cta"]}]
        else:
            for k, v in enumerate(s.get("visuals", [])):
                at = 0.3
                if k > 0:
                    target = _norm(v.get("at") or ""); hits = [w[1] for w in words if target and _norm(w[0]) == target and w[1] > d * 0.25]
                    at = max(0.3, hits[0] - 0.15) if hits else d * 0.5
                    if at < gfx[-1]["at"] + 2.5: at = gfx[-1]["at"] + 2.5
                    if at > d - 1.5: continue
                gfx.append({"at": round(at, 3), "g": v["chart"]})
        beats.append({"id": s["id"], "start": round(t, 3), "dur": round(d, 3), "words": words, "bgs": bgs, "graphics": gfx})
        parts.append((sd / "voice" / f"{s['id']}.wav", d * speed)); t += d
    flt = "".join(f"[{i}:a]apad,atrim=duration={dd:.3f}[a{i}];" for i, (_, dd) in enumerate(parts)) + "".join(f"[a{i}]" for i in range(len(parts))) \
        + f"concat=n={len(parts)}:v=0:a=1" + (f",atempo={speed:.4f}" if abs(speed - 1.0) > 1e-4 else "") + ",loudnorm=I=-14:TP=-1.5[out]"
    args = sum([["-i", p] for p, _ in parts], [])
    media.ff(*args, "-filter_complex", flt, "-map", "[out]", "-ar", 48000, pub / "voice.wav")
    data = {"audio": "voice.wav", "total": round(t, 3), "tag": plan.get("tag", ""), "beats": beats}
    (sd / "used.json").write_text(json.dumps(sorted(set(used)), indent=1), encoding="utf-8")
    (pub / "teaser.json").write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    log(f"Short timeline: {t:.1f}s, {len(beats)} beats, {sum(len(b['bgs']) for b in beats)} clips")
    return t

def _npx():
    for n in ("npx.cmd", "npx"):
        p = shutil.which(n)
        if p: return p
    raise RuntimeError("Node.js (npx) not found. Run Install in Pinokio again.")

def _gl(cfg):
    """WebGL backend for Remotion (3D reconstructions): the GPU via ANGLE on Windows, software elsewhere."""
    return cfg.get("remotion_gl") or ("angle" if os.name == "nt" else "swangle")

def _ensure_remotion(log):
    rdir = config.ROOT / "remotion"
    need = [rdir / "node_modules" / "@remotion" / "cli", rdir / "node_modules" / "@remotion" / "three", rdir / "node_modules" / "d3-geo"]
    if not all(p.exists() for p in need):
        log("Installing the Remotion renderer and its parts (one time)...")
        subprocess.run([shutil.which("npm.cmd") or shutil.which("npm") or "npm", "install", "--no-audit", "--no-fund"], cwd=rdir, check=True, timeout=1800)
    return rdir

BROWSER_FLAKE = "trying to connect to the browser"

def render_recon(g, out, secs, size, cfg, log, stop):
    """Render one 3D reconstruction clip (Recon composition) to out (mp4)."""
    if media.ok(out): return out
    rdir = _ensure_remotion(log); out.parent.mkdir(parents=True, exist_ok=True)
    pf = out.with_suffix(".json"); pf.write_text(json.dumps({"g": g, "secs": secs, "w": size[0], "h": size[1]}), encoding="utf-8")
    tmp = out.with_name(out.stem + "_tmp.mp4")
    cmd = [_npx(), "remotion", "render", "src/Root.tsx", "Recon", str(tmp), f"--props={pf}", f"--gl={_gl(cfg)}",
           f"--concurrency={cfg.get('short_concurrency', '75%')}", "--jpeg-quality=92", "--crf=18", "--log=error"]
    for attempt in range(3):
        p = subprocess.run(cmd, cwd=rdir, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
        if p.returncode == 0 or BROWSER_FLAKE not in (p.stdout + p.stderr) or attempt == 2: break
        time.sleep(10)
    if p.returncode != 0 or not tmp.exists():
        raise RuntimeError(" / ".join((p.stdout + p.stderr).strip().splitlines()[-4:])[:300])
    if out.exists(): out.unlink()
    tmp.rename(out); log(f"  reconstruction {out.stem}: {g.get('scene')} ({g.get('name') or ''})")
    return out

def do_render(job, plan, cfg, meta, log, stop):
    total = build(job, plan, cfg, log)
    rdir = _ensure_remotion(log)
    out_dir = job / "output"; out_dir.mkdir(exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9]+", "_", plan["title"]).strip("_")[:60] or "short"
    out = out_dir / f"{safe}_short.mp4"; tmp = out_dir / "_short_rendering.mp4"
    cmd = [_npx(), "remotion", "render", "src/Root.tsx", "Teaser", str(tmp), f"--public-dir={job / 'short' / 'public'}",
           f"--concurrency={cfg.get('short_concurrency', '75%')}", "--jpeg-quality=95", "--crf=16", "--log=info", f"--gl={_gl(cfg)}"]
    log(f"Rendering the Short with Remotion ({total:.0f}s of video)...")
    for attempt in range(3):
        p = subprocess.Popen(cmd, cwd=rdir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        last, t0, tail, errline = "", time.time(), [], ""
        for line in p.stdout:
            line = line.strip()
            if line:
                last = line; tail = (tail + [line])[-40:]
                if not errline and re.search(r"\b\w*Error\b|error:", line) and "│" not in line and not line.lstrip().startswith("at "): errline = line[:300]
            if time.time() - t0 > 30 and last: log("  " + last[:160]); t0 = time.time()
            if stop(): p.kill(); raise RuntimeError("cancelled")
        if p.wait() == 0: break
        if attempt < 2 and any(BROWSER_FLAKE in l for l in tail):
            # headless Chrome sometimes starts slowly (busy GPU/disk); Remotion gives it 25 s - just start again
            log(f"  Remotion couldn't connect to its browser in time; retrying the render ({attempt + 2} of 3)"); time.sleep(10); continue
        for l in tail[-15:]: log("  | " + l[:200])
        raise RuntimeError("Remotion render failed: " + (re.sub(r"\x1b\[[0-9;]*m", "", errline) or " / ".join(x for x in tail[-6:] if x)[:400]))
    if out.exists(): out.unlink()
    tmp.rename(out)
    try:   # keyframes on beat boundaries, so a beat can be replaced later without re-encoding the whole Short
        from . import edit
        from .pipeline import Job
        Job(job).save(short_output=str(out)); edit.ensure_keyframes(job, log)
    except Exception as e: log(f"  couldn't prepare the Short for editing ({str(e)[:150]}); the first edit will do it")
    # YouTube description: credit the source we summarised; stock libraries need no credit (NASA asks for a courtesy credit)
    pick = json.loads((job / "short" / "stock" / "pick.json").read_text(encoding="utf-8"))
    srcs = {c.get("src", "Pexels") for cs in pick.values() for c in cs}
    src = meta.get("webpage_url") or ""
    desc = [plan["title"], "", plan.get("description", ""), ""]
    if plan.get("mode") == "both": desc += ["Full breakdown: <PASTE LONG VIDEO LINK HERE>", ""]
    desc += ["Summarized from: " + meta.get("title", "") + (f" - {meta.get('channel')}" if meta.get("channel") else "") + (f"\n{src}" if src else ""), ""]
    if "NASA" in srcs: desc += ["Space footage courtesy of NASA.", ""]
    fbf = job / "short" / "fallback.json"
    creds = sorted({i["credit"] for v in (json.loads(fbf.read_text(encoding="utf-8")) if fbf.exists() else {}).values() for i in v if i.get("credit")})
    if creds: desc += creds + [""]
    desc += ["#Shorts"]
    (out_dir / "youtube_short_description.txt").write_text("\n".join(desc), encoding="utf-8")
    log(f"Short finished: {out} ({media.dur(out):.0f}s)")
    return out
