"""Vertical YouTube Short (2-3 min): script -> stock footage (Pexels, auto-vetted) -> narration -> Remotion render.
Almost no GPU: only the narration (WanGP TTS) and the clip vetting (small vision model) touch the GPU."""
import base64, io, json, math, os, re, shutil, subprocess, time
from pathlib import Path
import requests
from . import config, media, tts
from .llm import LLM, parse_json
from .writer import SYSTEM, make_notes, fact_check, audience_line, audience_key, log_audience, jargon_check, editorial_review, COVER_FLOOR

GAP, TAIL, MAX_SECS = 0.35, 2.2, 179.0   # YouTube Shorts allow up to 180 s (the hard maximum; a second of margin)
SHORT_MAX = 180.0   # length policy (2026-10-14): target the requested length, accept anything up to 3:00, trim only beyond it
SMOKE_WORDS = 40   # smoke-test Short: 2 beats of narration; with the ~8-word smoke closing line about 48-50 words (~30 s at this voice's pace)
KINDS = {"hook", "quote", "stat", "compare", "icons", "timeline"}

SHORT = """You are writing a vertical YouTube Short of about {secs} seconds (about {words} words of narration in total)
that condenses "{title}" by {channel}. The goal: a viewer who watches only this Short understands the main ideas and the
most striking facts, and wants more.

People in the source (use these full names and spellings; captions often mishear names): {people}

NOTES ON THE SOURCE (use only these facts):
{notes}

Write {nb} beats that tell one story. Each beat is 30-48 words (about 11-17 seconds spoken). Aim for about {words} words in total.
That is a target, not a cap: going over is fine when the audience needs a term explained - never cut an explanation to hit it.
Hard limit: {wmax} words (YouTube Shorts are cut off at 3 minutes). If the notes run out sooner, stop sooner; never pad.
- Beat 1 is the hook: one short line framing what this is (who is talking, about what), then the most surprising claim or number,
  in plain words (no jargon in the first sentence). No greetings, no "in this video".
- Tell events in the order they happened. Once the story has moved on (e.g. the plane has landed), don't go back to an earlier
  moment (what happened in the air) in a later beat; put background and reactions after the events, clearly as such.
- Middle beats: the strongest points, ONE idea per beat (never two unrelated topics in one beat), concrete (numbers, names, examples).
  Attribute opinions and predictions to who said them (first name is fine in narration).
- Last beat: the payoff / biggest takeaway, ending on a strong line.
Narration: spoken, punchy, short sentences, plain words, numbers written as spoken words ("ten billion dollars", "twenty thirty").
VOICE: conversational, like a sharp friend, not a narrator. Say what happened plainly and clearly first. Where it fits, add
one short opinion of ours ("honestly,", "our take:"). Do NOT write jokes: a dry closing joke is added to each beat separately.{cta_rule}
AUDIENCE: {audience}
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
COVERAGE: if the notes run out of substantive points before {words} words, stop there and set "covered": true (a shorter Short
beats padding); otherwise write the full length and set "covered": false.
Also give "title" (max 60 chars, YouTube title), "tag" (max 28 chars, small label shown at the top, e.g. "MOONSHOTS #293 · CONDENSED"),
"description" (2-3 sentences for YouTube that credit {channel} and the original), and "source_spoken": how a narrator would
name the source in a sentence, e.g. "the Moonshots podcast, episode two ninety-three" or "a NotebookLM briefing on battery recycling".

Reply with ONLY JSON:
{{"title":"...","tag":"...","description":"...","source_spoken":"...","covered":false,"beats":[{{"vo":"...","take":"optional: our opinion, copied from vo","graphics":[{{"at":null,"g":{{...}}}},{{"at":"word","g":{{...}}}}],"queries":["...","..."],"subject":null,"backdrop":{{...}},"still_prompt":"...","motion":"..."}}]}}"""

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
def _vnorm(t):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(t or "").lower().replace("\u2019", "").replace("'", "")).split())


def _quoted(phrase, vo):
    """True when the phrase's words appear in vo in the same order (punctuation, dashes, quotes and small edits
    such as an inserted comma clause don't matter); at least 80% of its words must line up."""
    p, v = _vnorm(phrase).split(), _vnorm(vo).split()
    if len(p) < 3: return False
    if " ".join(p) in " ".join(v): return True
    i = hit = 0
    for w in v:
        if i < len(p) and w == p[i]: i += 1; hit += 1
    return hit >= 0.8 * len(p)


SMOKE_FACT_WORDS = 18   # per beat, before its punch-up joke (~12 words): two beats + the closing line land at ~30 s


def trim_smoke(plan, log, limit=SMOKE_FACT_WORDS):
    """In-code length control for the 30-second test (the model ignores word budgets): keep each beat's main fact sentence
    (the first) and our opinion sentence when there is one; drop the rest. Never cuts inside a sentence."""
    for x in plan["sections"]:
        if x.get("cta"): continue
        sents = [t.strip() for t in re.split(r"(?<=[.!?])\s+", x["vo"].strip()) if t.strip()]
        if not sents: continue
        num = re.compile(r"\d|\b(one|two|three|four|five|six|seven|eight|nine|ten|twenty|thirty|forty|fifty|hundred|thousand|million|billion|percent|times)\b", re.I)
        main = sents[0] if num.search(sents[0]) or len(sents) == 1 else next((t for t in sents if num.search(t)), sents[0])   # the fact with a number, not a framing line
        first = sents[0]
        keep = [first, main] if main != first and len((first + " " + main).split()) <= limit else [main]   # keep who/what the fact is about
        sents = [t for t in sents if t not in keep]
        sents = keep + sents
        keep = [" ".join(keep)]
        take = x.get("take") or ""
        op = next((t for t in sents[1:] if (take and _quoted(take, t)) or re.match(r"(honestly|our take|which tells you)", t, re.I)), None)
        if op and len((" ".join(keep + [op])).split()) <= limit + 4: keep.append(op)
        elif len(keep[0].split()) < limit * 0.6 and len(sents) > 1 and len((keep[0] + " " + sents[1]).split()) <= limit: keep.append(sents[1])
        new = " ".join(keep)
        if new != x["vo"].strip():
            log(f"  {x['id']}: trimmed {len(x['vo'].split())} -> {len(new.split())} words for the 30-second test")
            x["vo"] = new


def protected_of(section):
    from .writer import protected
    return protected(section)


def write_short(cfg, meta, transcript, secs, mode, long_title, log, stop, srcdir, smoke=False):
    wpm = tts.wpm(cfg)
    # target = narration + a pause after each beat + the end tail + the closing line (~16 words); size the story to fill the rest
    words = int((secs - TAIL - GAP * 9 - 16 / wpm * 60) * wpm / 60)
    wmax = int((SHORT_MAX - TAIL - GAP * 9 - 16 / wpm * 60) * wpm / 60)   # what still fits in 3:00
    nb = max(7, min(12, round(words / 38)))
    minb, lo, hi = 6, 0.95, 1.05
    if smoke: words, nb, minb, lo, hi = SMOKE_WORDS, 2, 2, 0.8, 1.1   # smoke test: ~48 words in all with the closing line (~30 s spoken)
    title, channel = meta.get("title") or "the source", meta.get("channel") or meta.get("uploader") or "the creator"
    with LLM(cfg, log, stop) as llm:
        llm.trace_dir = Path(srcdir).parent / "prompts"
        log(f"Writing the Short with {llm.name} (~{secs:.0f}s, {words} words, {nb} beats)...")
        log_audience(cfg, log)
        notes = make_notes(llm, meta, transcript, max(words, 1500), log, stop, srcdir)
        tries = []   # every parsed attempt, so a near miss can be kept instead of an unchecked re-ask
        def chk(j):
            b = j.get("beats")
            if not isinstance(b, list) or len(b) < minb: raise ValueError(f"need at least {minb} beats")
            for x in b:
                if not isinstance(x.get("vo"), str) or not x.get("queries"): raise ValueError("beat missing vo or queries")
            n = sum(len(x["vo"].split()) for x in b)
            tries.append((abs(n - words), j))
            if smoke:   # the 30-second test is trimmed in code afterwards (trim_smoke); only a runaway length is re-asked
                if n > words * 3: raise ValueError(f"narration is {n} words in total; keep it near {words}")
            elif n > wmax: raise ValueError(f"narration is {n} words in total; the hard limit is {wmax} (YouTube's 3:00): cut the weakest point, keep the explanations of terms")
            # shorter than the target, or longer but within 3:00: accepted as written (no padding, no trimming)
        prompt = SHORT.format(secs=int(secs), words=words, wmax=wmax if not smoke else int(words * hi), title=title, channel=channel, notes=notes[:24000], nb=nb, audience=audience_line(cfg),
                              people=(meta.get("description") or "")[:1200] or "(see notes)",
                              cta_rule=("\nThis Short has NO longer companion video: never mention, promise or point to a longer / full video, "
                                        "a full breakdown, a link below or 'part two'." if mode != "both" else
                                        "\nA full-length explainer goes out with this Short; the closing line pointing to it is added "
                                        "separately, so don't write your own link or 'watch the full video' line."))
        from . import source_visuals
        prompt += source_visuals.prompt(srcdir)
        if audience_key(cfg) == 'beginner':
            prompt += '\nBEGINNER PRIORITY: depth over breadth. Explain one core technical idea per beat instead of listing many features. Keep the technical names of the chosen idea, and explain what they mean immediately. Omit secondary features that would introduce more terms than you have room to explain.'
            if smoke:
                prompt += f'\nFor this 30-second test, use the TWO beats to explain ONE technical idea from the title/notes, in {int(words * lo)}-{int(words * hi)} words TOTAL. Do not introduce API keys, radar, lightning density or other secondary jargon unless that is the chosen topic. Keep source_spoken to 2-4 words so the closing line stays short. Plain and clear; no jokes (they are added separately).'
        try: j = llm.trace("short script").chat_json(SYSTEM, prompt, max_tokens=8000, check=chk)
        except RuntimeError:
            if tries:
                j = min(tries, key=lambda x: x[0])[1]
                log(f"  length still off after 3 tries; keeping the closest ({sum(len(x['vo'].split()) for x in j['beats'])} words, target {words})")
            else:
                log("  no usable script after 3 tries; asking once more without the length check")
                j = llm.chat_json(SYSTEM, prompt, max_tokens=8000, check=lambda x: None if x.get("beats") else (_ for _ in ()).throw(ValueError("no beats")))
        nw0 = sum(len(x["vo"].split()) for x in j["beats"])
        if j.get("covered") is True and nw0 < words * lo: log(f"  the AI says the source is fully covered at {nw0} of {words} words; kept short (no padding)")
        if not smoke: log(f"  script: {nw0} words (target {words}; 3:00 = {wmax} words){'; over the target, accepted' if nw0 > words * 1.05 else ''}")
        if smoke: j["beats"] = j["beats"][:2]   # a smoke test stays ~30 s even if the length check gave up
        elif cfg.get("short_fit_3min", False):   # off by default (owner 2026-10-23): a long Short just isn't classed as a Short
            while len(j["beats"]) > minb and sum(len(x["vo"].split()) for x in j["beats"]) > wmax:
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
                                     "source_visual": b.get("source_visual"), "take": str(b.get("take") or ""), "joke": str(b.get("joke") or ""),
                                     "protect": [str(b.get("take") or "")] if _quoted(b.get("take"), b["vo"]) else [],
                                     "still_prompt": str(b.get("still_prompt") or "")[:500], "motion": str(b.get("motion") or "")[:160],
                                     "visuals": [{"type": "chart", "chart": g["g"], "at": g.get("at")} for g in gs]})
        log("Checking the Short against the source (names, attributions, numbers)...")
        if smoke: plan['smoke'] = True
        plan = fact_check(llm, plan, meta, transcript, log, stop, cfg)   # an opinion of ours (take) is protected from here on
        from .writer import punch_up
        if smoke:   # 30-second test: plain summary -> trimmed in code to its main fact (+ opinion) -> one punch-up joke per beat
            trim_smoke(plan, log)
        else:
            editorial_review(llm, plan, meta, transcript, cfg, log, stop)
            if plan.get("editorial_warnings"):
                jargon_check(llm, plan, cfg, log, source_notes=notes)   # the review gave up: explanations still go in (protected)
        punch_up(cfg, plan, log, force=smoke, budget=wmax if (not smoke and cfg.get("short_fit_3min", False)) else None)   # smoke: every beat gets its joke here; otherwise only beats still without one
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
    if not smoke and cfg.get("short_fit_3min", False):   # the fact-check can lengthen the script: cut again (only when fitting 3:00 is on)
        while len(plan["sections"]) > minb and sum(len(x["vo"].split()) for x in plan["sections"]) > wmax:   # only past 3:00
            cut = plan["sections"].pop(-2); log(f"  script grew past the 3:00 limit in the fact-check; dropped a middle beat ({len(cut['vo'].split())} words)")
        for i, x in enumerate(plan["sections"]): x["id"], x["title"] = f"b{i}", f"Beat {i + 1}"
    n = sum(len(x["vo"].split()) for x in plan["sections"])
    if not smoke and n > wmax: log(f"  NOTE: script is {n} words (target {words}); past 3:00" + ("; it will be sped up to fit" if cfg.get("short_fit_3min", False) else "; kept as is (YouTube will treat it as a regular video, not a Short)"))
    if mode != "both":   # no companion explainer: a promise of one must not survive (the model sometimes adds it anyway)
        promise = re.compile(r"[^.!?]*\b(full (breakdown|video|episode|explainer)|longer video|link(ed)? below|part two|watch the full)\b[^.!?]*[.!?]?\s*", re.I)
        for x in plan["sections"]:
            cut = promise.sub("", x["vo"]).strip()
            if cut != x["vo"].strip() and len(cut.split()) >= 6:
                log(f"  {x.get('id', 'beat')}: removed a line promising a longer video (this job makes no long video)"); x["vo"] = cut
        d = promise.sub("", plan.get("description") or "").strip()
        if d != (plan.get("description") or "").strip():
            log("  description: removed a line promising a longer video"); plan["description"] = d
    # closing call-to-action beat
    src_name = plan.get("source_spoken") or title
    if mode == "both":
        cta_vo = f"That was a short summary of {src_name}. Big picture, fewer rabbit holes. The full breakdown is linked below."
        cta = {"kind": "cta", "badge": "FULL BREAKDOWN", "title": long_title or plan["title"], "line": "Watch it, linked below"}
    else:
        cta_vo = f"That was a short summary of {src_name}. Big picture, fewer rabbit holes. Follow for more."
        if smoke: cta_vo = f"That was {src_name}, condensed. Follow for more."   # the 30-second test keeps its closing line short
        cta = {"kind": "cta", "badge": "SUMMARIZED FROM", "title": title[:80], "line": "Follow for more", "play": False, "arrow": False}
    plan["sections"].append({"id": f"b{len(plan['sections'])}", "title": "Call to action", "vo": cta_vo, "queries": [], "cta": cta, "visuals": []})
    w = sum(len(s["vo"].split()) for s in plan["sections"])
    for x in plan["sections"]:   # did the fact-check / jargon passes keep the voice?
        if x.get("cta"): continue
        lost = [f for f in ("take", "joke") if x.get(f) and not _quoted(x[f], x["vo"]) and not x.get("punchline")]
        if lost: log(f"  voice check {x['id']}: the later passes reworded the {' and the '.join(lost)}")
    log(f"Short script ready: {len(plan['sections'])} beats, {w} words (~{w / cfg['wpm'] * 60 + GAP * len(plan['sections']) + TAIL:.0f}s)")
    return plan

# ---------------------------------------------------------------- stock footage
def do_stock(job, plan, cfg, log, stop):
    """Pexels + Pixabay (+ NASA for space beats): ranked by meaning, checked by the vision model, cut at high quality."""
    from . import footage
    d = job / "short" / "stock"
    slots, need = [], {}
    own = {}
    from . import clips
    if clips.enabled(cfg):
        own = clips.for_short(job, plan, cfg, log, stop)   # your footage first: covered beats aren't searched
    for s in plan["sections"]:
        if s["id"] in own: continue
        if s.get("cta"):
            # neutral: no city or landmark (a London skyline closed a Cyprus story); the clip check rejects any recognisable place
            slots.append({"id": s["id"], "text": "calm, neutral background for the closing end card", "queries": ["night sky stars timelapse", "soft clouds sky timelapse", "abstract bokeh lights"], "cta": True})
            need[s["id"]] = 1
        elif s.get("subject"):
            continue   # locked to a specific subject: stock libraries don't have it; real photos / reconstruction come in short_fallback
        else:
            secs = len(s["vo"].split()) / tts.wpm(cfg) * 60 + GAP
            slots.append({"id": s["id"], "text": s["vo"], "queries": s["queries"], "subject": s.get("subject"), "avoid": s.get("avoid") or []})
            need[s["id"]] = max(2, min(3, math.ceil(secs / 6.0)))
    picked = footage.fill(cfg, slots, "portrait", need, d, log, stop, want_long_side=2560, max_secs=10.0, state_file=d / "footage.json", fallback=True)
    for s in plan["sections"]:
        if s.get("subject") and not s.get("cta"): picked.setdefault(s["id"], [])
    picked = dict(picked); picked.update(own)
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
    from . import flow as _flow, imagegen as _imagegen; _flow.reset(); _imagegen.reset()   # job-wide skips start clear for every run
    from . import depth, coherence, photos, ladder, cloudgen, illustrate, physics
    v2 = bool(cfg.get("ladder_v2"))   # visual ladder v2 (graphics / physics / CapCut); off = the ladder below, unchanged
    sd = job / "short"; fd = sd / "fallback"; fd.mkdir(parents=True, exist_ok=True)
    tm = json.loads((sd / "timings.json").read_text(encoding="utf-8"))
    pick = json.loads((sd / "stock" / "pick.json").read_text(encoding="utf-8"))
    for bid, cs in list(pick.items()):   # a clip whose file is missing or broken (failed download) is not footage
        ok = [c for c in cs if media.ok(sd / "stock" / "clips" / f"{c['id']}.mp4", 0.3)]
        if len(ok) != len(cs):
            log(f"  {bid}: {len(cs) - len(ok)} stock clip(s) missing or unreadable; not used")
            for c in cs:
                if c not in ok: (sd / "stock" / "clips" / f"{c['id']}.mp4").unlink(missing_ok=True)
            pick[bid] = ok
    (sd / "stock" / "pick.json").write_text(json.dumps(pick, indent=1), encoding="utf-8")
    fsf = sd / "stock" / "footage.json"; fst = json.loads(fsf.read_text(encoding="utf-8")) if fsf.exists() else {}
    ff = sd / "fallback.json"; out = json.loads(ff.read_text(encoding="utf-8")) if ff.exists() else {}
    cf = fd / "chains.json"; chs = json.loads(cf.read_text(encoding="utf-8")) if cf.exists() else {}
    def save_out(): ff.write_text(json.dumps(out, indent=1), encoding="utf-8"); cf.write_text(json.dumps(chs, indent=1), encoding="utf-8")
    demoted = {}   # beat -> the stock set aside for its source clip (given back if the clip fails)
    if v2 and cfg.get("source_clips_auto", True) and cfg.get("source_visuals", True) and cfg.get("source_over_stock", True):
        # A beat about a specific story moment the source itself shows: its own footage beats a generic stock clip
        # (a laptop for a model launch, test tubes for an enzyme). The strongest caption matches (within the source-clip
        # budget) set their generic stock aside, so the Source Clip rung (2) runs for them.
        from . import source_visuals
        cand = []
        for x in plan["sections"]:
            if x.get("cta") or x["id"] not in tm or any(c.get("own") for c in pick.get(x["id"], [])): continue
            r = source_visuals.auto_request(job, x, min_overlap=int(cfg.get("source_over_stock_min", 4)))
            if r: cand.append((r["match"], x["id"], r["start"]))
        cap = max(0, min(2, int(cfg.get("source_visual_max_uses", 2))))
        for score, bid, start in sorted(cand, reverse=True)[:cap]:
            if pick.get(bid):
                log(f"  {bid}: generic stock set aside: the source itself covers this beat (caption cue at {start:.1f}s, {score} shared words)")
                demoted[bid] = pick[bid]; pick[bid] = []
        if demoted: (sd / "stock" / "pick.json").write_text(json.dumps(pick, indent=1), encoding="utf-8")
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
        mine = any(c.get("own") for c in pick.get(bid, []))
        chs[bid] = {"n": int(bid[1:]) + 1, "vo": sec["vo"], "stock_found": k, "chain": ["your footage" if mine else f"stock ({k} clip(s), coherent)"], "uses": ["yours" if mine else "stock"],
                    "failed": [], "stock_rejected": srej(bid), "photos_rejected": []}
    def info(sec):
        c = chs.get(sec["id"], {})
        return {"bid": sec["id"], "n": int(sec["id"][1:]) + 1, "vo": sec["vo"], "stock_found": c.get("stock_found", len(pick.get(sec["id"], []))),
                "uses": c.get("uses", []), "failed": c.get("failed", [])}
    if v2: log("Visual ladder v2 per beat (1 stock -> 2 source clip -> 3 image generator (Gemini: describe the source screenshot, "
               "write a prompt, generate a new image) -> 4 source parallax (rembg + Remotion) -> 5 Google Flow (paid, last) -> "
               "6 WanGP (on demand) -> 7 physics -> 8 Remotion graphics -> 9 headline card):")
    else: log("Visual ladder per beat (1 stock/photo -> 2 cloud still -> 3 WanGP still -> 4 parallax -> 5 illustration / silhouette -> 6 reconstruction / headline; animate on click):")
    for s in beats:   # beats step 1 covered on its own
        if s["id"] in base_needs: continue
        log(f"  {s['id']}: " + ("your footage" if any(c.get("own") for c in pick.get(s["id"], [])) else f"stock ({len(pick.get(s['id'], []))} clip(s), coherent)")); _safe(log, f"{s['id']} stock", lambda: stock_beat(s))
    if not needs and not dbg:
        log("  no other beats need visuals"); save_out(); return
    ents = json.loads((job / "entities.json").read_text(encoding="utf-8")) if (job / "entities.json").exists() else []
    phases = coherence.beat_phases([x for x in plan["sections"] if not x.get("cta")])
    pre, step1, slots, prej = {}, {}, [], {}

    def prepare(s):
        n = needs[s["id"]]; items = []; rej = []
        from . import source_visuals
        raw_source = _safe(log, f"{s['id']} source clip", lambda: source_visuals.make(cfg, job, sd, s, log))
        source = None
        if raw_source:
            source = dict(raw_source); source["src"] = _rel_sd(source.pop("path"), sd)
            items.append(source)
        elif s["id"] in demoted:   # the source clip failed: the beat gets back the stock set aside for it
            pick[s["id"]] = demoted.pop(s["id"])
            (sd / "stock" / "pick.json").write_text(json.dumps(pick, indent=1), encoding="utf-8")
            log(f"  {s['id']}: source clip failed; the stock set aside for it is back ({len(pick[s['id']])} clip(s))")
            needs.pop(s["id"], None)
            _safe(log, f"{s['id']} stock", lambda: stock_beat(s))
            return
        snap = None
        if v2 and len(items) < n and cfg.get("imagegen_on", True):   # rung 3: free image generators (describe the source screenshot -> new image)
            from . import imagegen
            snap = _safe(log, f"{s['id']} source screenshot", lambda: source_visuals.snapshot(cfg, job, sd, s, log, source_item=raw_source))
            want = n - len(items)   # a beat that needs several visuals gets a second Gemini image (another angle / close-up), not Flow
            imgs = _safe(log, "image generators", lambda: imagegen.generate_many(cfg, sd, s, s["id"], log, aspect="9:16",
                                                                                image=(snap or {}).get("path"), count=want), []) or []
            for k, (img, _p) in enumerate(imgs):   # rung 4: source parallax (rembg cut-out + Remotion 2.5D)
                lay = _safe(log, f"{s['id']} parallax", lambda: depth.cutout_layers(img, sd / "imagegen" / f"{s['id']}_px{k or ''}", log))
                if lay:
                    items.append({"type": "layers", "layers": [_rel_sd(p_, sd) for p_ in lay], "tag": imagegen.tag(),
                                  "rung": "imagegen", "site": imagegen.last_site(), "described": bool(snap), "variant": k})
                else:
                    items.append({"type": "image", "src": _rel_sd(img, sd), "tag": imagegen.tag(), "rung": "imagegen", "site": imagegen.last_site(), "variant": k})
        if v2 and cfg.get("flow_on", True) and not items:   # rung 5: Google Flow (paid, Google account): only a beat nothing else could fill
            from . import flow
            clip = _safe(log, "flow", lambda: flow.generate(cfg, sd, s, f"{s['id']}_flow", log, aspect="9:16"))
            if clip:
                items.append({"type": "video", "src": _rel_sd(clip, sd), "secs": round(media.dur(clip), 2), "rate": 1.0, "freeze": True,
                              "tag": "GENERATED · FLOW", "rung": "flow"})
        bd = s.get("backdrop") or {"kind": "headline", "kicker": "", "text": s["vo"][:60], "sub": ""}
        if bd.get("kind") == "map" and len(items) < n: items.append({"type": "graphic", "g": bd, "rung": "map"})
        have = len(pick.get(s["id"], []))
        why1 = f"only {have} coherent stock clip(s)" if have else "no coherent stock"
        if s["id"] not in base_needs: why1 = ""   # stock covers this beat; the other treatments are made for the review menu
        act = physics.action(s)[0] if v2 else ""   # v2: a beat describing an action is animated (physics / graphics / illustration), never a still
        if s.get("subject") and act: why1 = f"action beat ({act}): a still photo can't show it"
        elif s.get("subject") and len(items) < n and not source and not v2:   # (v2 has no real-photo rung) a beat with its source clip needs no photo search
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
        # ladder order: illustrations / silhouettes come before WanGP. WanGP only draws atmospheric filler that no illustration
        # covers, and never aircraft, vehicles, specific buildings or real people (it hallucinates their anatomy)
        locked = illustrate.wangp_lock(s, ents, phases.get(s["id"]))
        opts = illustrate.options(s, ents, phases.get(s["id"]))
        wan_why = locked or ("an illustration fits" if opts and not v2 else "") or (f"action beat ({act}): animation first" if act else "")   # v2: illustrations are rung 9, WanGP draws atmospheric beats
        for k in range(n - len(items)):
            slots.append({"key": f"{s['id']}_{k}", "beat": s["id"], "vo": s["vo"], "still_prompt": s.get("still_prompt", ""),
                          "motion": s.get("motion", ""), "subject": s.get("subject"), "rotate": rot,
                          "person": cloudgen.has_person(s["vo"], ents), "wan": not wan_why, "wan_why": wan_why})

    def finalize(s, st):
        items = pre[s["id"]]; bd = s.get("backdrop") or {}
        cap = bd.get("text", "") if bd.get("kind") == "headline" else bd.get("title", "")
        rung1, why1 = step1[s["id"]]
        lines, k5, kill, failed = [], 0, 0, ([rung1] if why1 else [])
        for item in items:
            if item.get("rung") == "source":
                lines.append(f"source clip, full frame ({item['type']} at {float(item.get('timestamp') or 0):.2f}s of the source, {item.get('tag', '')})")
            elif item.get("rung") == "imagegen":
                lines.append(f"new image from {item.get('site')}" + (f" (variant {item['variant'] + 1})" if item.get("variant") else "")
                             + (" (described from the source screenshot)" if item.get("described") else "")
                             + (", rembg parallax" if item["type"] == "layers" else ""))
            elif item.get("rung") == "flow":
                lines.append("Google Flow clip")
        vb = {"g": False, "hard": False, "p": False, "pok": False, "capcut": "", "f": False}   # v2, once per beat: graphics tried / hard-failed, physics tried / fitted
        if v2:
            from . import capcut
            capcut.mark(sd, s["id"], None)   # re-deciding this beat: a CapCut mark from an earlier run no longer applies
        for sl in [x for x in slots if x["beat"] == s["id"]]:
            r = st.get(sl["key"], {}); chain = [rung1]; why = [f"{rung1}: {why1}"] if why1 else []
            cloud = r.get("src") == "cloud"
            if "cloud" in r and not cloud:   # cloud tried (or skipped) and gave nothing usable: WanGP's still is next
                chain.append("cloud"); why.append(f"cloud: {r.get('cloud_why') or 'failed'}"); failed.append("cloud")
            nowan = sl.get("wan") is False and not cloud   # illustrations come before WanGP: WanGP never ran for this slot
            if nowan: why.append(f"WanGP skipped: {sl.get('wan_why')}")
            else: chain.append(f"cloud still ({r.get('cloud_provider')})" if cloud else "still")
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
            elif v2:
                if not nowan: why.append(f"still: {r.get('still_why') or 'not made'}"); failed.append("still")
                it = _v2_rungs(cfg, sd, s, sl, r, ents, phases, bd, vb, chain, why, failed, kill, log, pos=(len(items), needs[s["id"]]))
                if it.get("rung") in ("illustration", "silhouette"): kill += 1
                items.append(it)
            else:
                if not nowan: why.append(f"still: {r.get('still_why') or 'not made'}"); failed.append("still")
                ill = illustrate.pick(s, ents, phases.get(s["id"], ""), k5 + kill, pos=(len(items), needs[s["id"]]))
                if ill:   # a flat illustration / silhouette looks like a design choice; claymation only when nothing fits
                    chain.append(ill["rung"]); items.append(ill); kill += 1
                elif s.get("subject"):
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
                        "uses": [i["rung"] for i in items] + (["cloud"] if any(i.get("cloud") for i in items) else []) + (["capcut"] if vb["capcut"] == "pending" else []),
                        "failed": sorted(set(failed)), "stock_rejected": srej(s["id"]), "photos_rejected": prej.get(s["id"], []),
                        **({"ladder": "v2", "capcut": vb["capcut"]} if v2 else {}),
                        "cloud": [{"slot": x["key"], "provider": st.get(x["key"], {}).get("cloud_provider"), "why": st.get(x["key"], {}).get("cloud_why", ""),
                                   "tries": st.get(x["key"], {}).get("cloud_tries", [])} for x in slots if x["beat"] == s["id"] and "cloud" in st.get(x["key"], {})]}
        save_out()

    pause = (lambda: dbg.manual("short_fallback: AI stills")) if dbg else None

    def finalize_safe(s, st):   # one beat failing to finalize must never stop the job: it gets a headline card and the log says why
        if s["id"] not in needs: return   # given back to stock in prepare (its source clip failed)
        if _safe(log, f"{s['id']} visual ladder", lambda: finalize(s, st) or True) is None:
            out[s["id"]] = [{"type": "graphic", "g": {"kind": "headline", "kicker": "", "text": s["vo"][:70], "sub": ""}, "rung": "headline"}]
            chs[s["id"]] = {"n": int(s["id"][1:]) + 1, "vo": s["vo"], "chain": ["ladder failed -> headline"], "uses": ["headline"], "failed": ["ladder"]}
            save_out()
    if dbg and dbg.active():   # debug: one beat at a time, so a breakpoint stops right after the beat it is about
        log("  debug on: beats run one at a time; breakpoints are checked after each beat")
        for s in beats:
            if stop(): raise RuntimeError("cancelled")
            if s["id"] in needs and s["id"] not in out:
                first = len(slots); prepare(s); sl = slots[first:]
                st = _ladder_safe(ladder, cfg, wg, sd, fd, sl, log, stop, bool(sl) and _safe(log, "WanGP check", wg.alive, False), seed=5100 + first, full=full, pause=pause) if sl else {}
                if sl and not _safe(log, "WanGP check", wg.alive, False): log("  WanGP isn't reachable: cloud stills only")
                finalize_safe(s, st)
            elif s["id"] not in needs: _safe(log, f"{s['id']} stock", lambda: stock_beat(s))
            save_out(); dbg.point(info(s))
        return
    for s in beats:
        if s["id"] in needs:
            if stop(): raise RuntimeError("cancelled")
            prepare(s)
    run_slots = slots
    gpu = bool(run_slots) and bool(_safe(log, "WanGP check", wg.alive, False))
    if run_slots and not gpu: log("  WanGP isn't reachable: cloud stills only" if cfg.get("cloud_on", True) else "  WanGP isn't reachable: skipping steps 2-4")
    st = _ladder_safe(ladder, cfg, wg, sd, fd, run_slots, log, stop, gpu, full=full, pause=pause) if run_slots else {}
    for s in beats:
        if s["id"] in needs: finalize_safe(s, st)
        elif s["id"] not in out: _safe(log, f"{s['id']} stock", lambda: stock_beat(s))
        if dbg: save_out(); dbg.point(info(s))
    _safe(log, "hold previous shot", lambda: hold_previous(beats, out, chs, tm, cfg, log))
    save_out()


def hold_previous(beats, out, chs, tm, cfg, log):
    """Last rung before a text card (owner, 2026-10-23): a short beat that only got a headline card keeps the previous beat's
    picture on screen (its still / parallax carries on) instead of flashing a card. Longer beats keep the card."""
    lim = float(cfg.get("hold_previous_max_secs", 3.5) or 0)
    if lim <= 0: return
    prev = None
    for s in beats:
        items = out.get(s["id"]) or []
        if items and all(i.get("rung") == "headline" for i in items) and prev and float((tm.get(s["id"]) or {}).get("dur", 99)) <= lim:
            keep = dict(prev, rung="hold previous", held_from=prev.get("held_from") or prev_id)
            out[s["id"]] = [keep]
            if s["id"] in chs: chs[s["id"]]["uses"] = ["hold previous"]; chs[s["id"]].setdefault("chain", []).append("hold previous shot")
            log(f"  {s['id']}: nothing fit; the previous beat's picture stays on screen ({float(tm[s['id']]['dur']):.1f}s) instead of a text card")
        last = (out.get(s["id"]) or [None])[-1]
        if last and last.get("type") in ("image", "layers"): prev, prev_id = last, s["id"]
        else: prev = None   # stock / video / card: nothing to hold

def _ladder_safe(ladder, cfg, wg, sd, fd, slots, log, stop, gpu, **kw):
    """Rungs 2-4 (cloud still, WanGP still, checks). If they fail, log it and use whatever they had saved in ladder.json, so every
    slot still goes down rungs 5-10."""
    out = _safe(log, "AI stills (cloud / WanGP)", lambda: ladder.run(cfg, wg, sd, fd, slots, log, stop, gpu, **kw))
    if out is not None: return out
    f = fd / "ladder.json"
    try: return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except Exception: return {}

def _safe(log, rung, fn, default=None):
    """Run one rung; any failure is logged and the ladder moves on (a rung must never stop the job or the server).
    Pause (debugger) and cancel still propagate."""
    from .debug import Paused
    try:
        return fn()
    except Paused:
        raise
    except RuntimeError as e:
        if str(e) == "cancelled": raise
        log(f"  {rung} failed ({str(e)[:160]}); next rung"); return default
    except Exception as e:
        log(f"  {rung} failed ({type(e).__name__}: {str(e)[:160]}); next rung"); return default

def _v2_rungs(cfg, sd, s, sl, r, ents, phases, bd, vb, chain, why, failed, kill, log, pos=None):
    """Visual ladder v2, rungs 5-10 for one slot whose cloud / WanGP still didn't pass. -> the bg item. Appends to chain / why /
    failed. vb carries per-beat state: physics and graphics run once per beat (a second slot of the same beat goes on down).
    5. physics = DATA PROVIDER: when the slot describes physical motion it returns a payload (real data, the narration's numbers,
       the script's map coordinates, or a labelled synthetic path), saved to short/physics/<slot>.json
    6. Remotion graphics: draws that payload as a motion-graphics clip; without a payload, a template / Claude composition
    7. CapCut (hard failures)   8. parallax   9. headline card
    Every rung is isolated (_safe): a failure is logged and the next rung runs."""
    from . import graphics, physics, capcut
    payload = None
    if cfg.get("physics_auto", True) and not vb["p"]:   # 5. physics -> data
        vb["p"] = True
        from . import liveries
        story = _safe(log, "physics", lambda: liveries.story_text(ents), "")
        payload = _safe(log, "physics", lambda: physics.provide(cfg, s, bd, log, pos=pos, story=story))
        if payload:
            pdir = sd / "physics"; pdir.mkdir(exist_ok=True)
            _safe(log, "physics", lambda: (pdir / f"{sl['key']}.json").write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8"))
            chain.append(f"physics data ({payload['module']}, {payload['source']})")
        else:
            why.append("physics: no physical motion to model"); failed.append("simulation")
    if payload:   # 6. Remotion draws the physics payload
        tag = "SYNTHETIC" if payload["source"] == "synthetic" else "SIMULATION"
        clip = _safe(log, "graphics (physics payload)", lambda: graphics.render_payload(cfg, sd, payload, sl["key"], log))
        vb["pok"] = True
        if clip:
            chain.append("graphics (physics payload)")
            return {"type": "video", "src": _rel_sd(clip, sd), "secs": round(media.dur(clip), 2), "rate": 1.0, "freeze": True,
                    "textbg": True, "tag": tag, "rung": "simulation"}
        chain.append("graphics (physics payload, drawn live)")   # pre-render failed: the final render draws the same spec
        return {"type": "graphic", "g": payload["spec"], "tag": tag, "rung": "simulation"}
    if not vb["g"]:   # 6. Remotion graphics (template, else Claude-generated)
        vb["g"] = True
        g5 = _safe(log, "graphics", lambda: graphics.make(cfg, sd, s, sl["key"], log)) or {"ok": False, "why": "crashed (see log)", "hard": True, "how": "?"}
        if g5["ok"]:
            secs = round(media.dur(g5["path"]), 2)
            chain.append(f"graphics ({g5['how']})")
            return {"type": "video", "src": _rel_sd(g5["path"], sd), "secs": secs, "rate": 1.0, "freeze": True, "textbg": True,
                    "tag": "GRAPHICS", "rung": "graphics"}
        chain.append("graphics"); why.append(f"graphics: {g5['why']}"); failed.append("graphics"); vb["hard"] = bool(g5.get("hard"))
    if vb["hard"] and not vb["pok"] and not vb["capcut"]:   # 7. CapCut: graphics HARD-failed and no physics payload
        if capcut.enabled(cfg):
            if _safe(log, "capcut", lambda: capcut.mark(sd, s["id"], why[-1] if why else "graphics failed") or True):
                vb["capcut"] = "pending"; chain.append("capcut (pending: one CapCut session after the render)")
        else: vb["capcut"] = "off"
    # 8-10: the beat's visual for the render (provisional when CapCut is pending)
    sw = str(r.get("still_why") or "")
    if r.get("still") and "unavailable" in sw:   # 8. parallax: a still the check couldn't judge (never one rejected for its content)
        lay = _safe(log, "parallax", lambda: depth_free(sd / r["still"], sd / "fallback" / f"{sl['key']}_p8"))
        if lay:
            chain.append("parallax")
            return {"type": "layers", "layers": [_rel_sd(p, sd) for p in lay], "tag": "GENERATED · PARALLAX", "rung": "parallax"}
    chain.append("headline")   # 9. headline card (the illustration rung was removed 2026-10-21)
    return {"type": "graphic", "g": bd if bd.get("kind") == "headline" else {"kind": "headline", "kicker": "", "text": s["vo"][:70], "sub": ""}, "rung": "headline"}

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
    """WanGP (when needed at all) is started on demand and stopped as soon as this batch is done (wangp.py)."""
    with wg.hold():
        return _do_voice_inner(job, plan, cfg, wg, log, stop)


def _do_voice_inner(job, plan, cfg, wg, log, stop):
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
    from .pipeline import progress
    if groups and tts.engine(cfg) == "kokoro":   # every batch in one Kokoro run (seconds); the split / timings below are unchanged
        if not tts.try_kokoro(cfg, [(" ".join(s["vo"] for s in grp), vd / f"batch_{grp[0]['id']}.wav") for grp in groups], log, "Short narration", stop):
            if not wg.alive(): raise RuntimeError("Kokoro narration failed and WanGP (the fallback) is not running. Start Wan2GP in Pinokio, then press Resume.")
    for gi, grp in enumerate(groups):
        progress(job, sum(len(g) for g in groups[:gi]) + len(grp), len(todo))
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

TEXT_BG = ("headline", "sim", "simmap", "motion", "tpl")   # backgrounds that carry their own text in the middle of the frame (+ a map with a title)

def _resolve_overlaps(bid, bgs, gfx, d, log):
    """One text layer per screen zone at a time. A background that carries its own text (headline card, simulation, titled map)
    owns the middle of the frame while it is on screen: a graphic card (stat / hook / quote ...) that would play over it is dropped
    (and logged), and emoji keep out of that time too. Narration captions sit in their own zone at the bottom and always stay.
    -> (gfx kept, [(t0, t1)] text-background windows)."""
    wins = []
    for i, bg in enumerate(bgs):
        g = bg.get("g") or {}
        if (bg.get("type") == "graphic" and (g.get("kind") in TEXT_BG or (g.get("kind") == "map" and g.get("title")))) or bg.get("textbg"):
            t1 = bgs[i + 1]["from"] if i + 1 < len(bgs) else d
            wins.append((bg["from"], t1))
    if not wins: return gfx, []
    keep = []
    for i, g in enumerate(gfx):
        if g["g"].get("kind") == "cta": keep.append(g); continue
        nxt = gfx[i + 1]["at"] if i + 1 < len(gfx) else d
        a, b = g["at"], g["at"] + min(nxt - g["at"], 4.6)
        hit = next((w for w in wins if w[0] < b and a < w[1]), None)
        if hit:
            log(f"  {bid}: dropped the {g['g'].get('kind')} card at {a:.1f}s - it would cover text already on the background ({hit[0]:.1f}-{hit[1]:.1f}s)")
        else: keep.append(g)
    return keep, wins

def _icons(cfg, sd, bid, words, gfx, d, log, extra_busy=()):
    """Emoji above the caption, one per caption sentence where it fits (same picker as the explainer), only while no graphic
    card is on screen. Cached in short/icons_<beat>.json."""
    from . import captions as C
    f = sd / f"icons_{bid}.json"
    if f.exists(): groups = json.loads(f.read_text(encoding="utf-8"))
    else:
        groups = C.groups([tuple(w) for w in words]) if words else []
        try: groups = C.pick_emojis(cfg, groups, log) if groups else []
        except Exception as e: log(f"  emoji pick failed for {bid} ({str(e)[:80]})")
        f.write_text(json.dumps(groups, ensure_ascii=False), encoding="utf-8")
    busy = list(extra_busy)
    for i, g in enumerate(gfx):
        nxt = gfx[i + 1]["at"] if i + 1 < len(gfx) else d
        busy.append((g["at"], g["at"] + min(nxt - g["at"], 4.6)))
    out = []
    for g in groups:
        if not g.get("emoji"): continue
        free = [(g["start"], max(g["start"] + 0.8, g["end"]))]   # the caption's time minus the graphic cards' time
        for x, y in busy:
            free = [seg for a, b in free for seg in ((a, min(b, x)), (max(a, y), b)) if seg[1] - seg[0] > 0.05]
        best = max(free, key=lambda ab: ab[1] - ab[0], default=None)
        if best and best[1] - best[0] >= 0.8: out.append({"at": round(best[0], 3), "dur": round(best[1] - best[0], 3), "e": g["emoji"]})
    return out

def build(job, plan, cfg, log):
    sd = job / "short"; pub = sd / "public"; (pub / "media" / "stock").mkdir(parents=True, exist_ok=True)
    tm = json.loads((sd / "timings.json").read_text(encoding="utf-8"))
    pick = json.loads((sd / "stock" / "pick.json").read_text(encoding="utf-8"))
    secs = [s for s in plan["sections"] if s["id"] in tm]
    raw_total = sum(tm[s["id"]]["dur"] + GAP for s in secs) - GAP + TAIL
    speed = 1.0
    tgt = plan.get("target_secs")
    if tgt and abs(raw_total - tgt) > 3:   # length policy (2026-10-14): the narration keeps its natural pace; only past 3:00 is it sped up
        log(f"  narration {raw_total:.0f}s vs target {tgt:.0f}s; natural pace kept")
    if raw_total / speed > MAX_SECS and cfg.get("short_fit_3min", False):
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
    music = cfg.get("music_on", True) and (not plan.get("smoke") or cfg.get("music_in_smoke", False))
    for i, s in enumerate(secs):
        last = i == len(secs) - 1
        d = (tm[s["id"]]["dur"] + (TAIL if last else GAP)) / speed
        if music and not last and cfg.get("breathers", True) and not s.get("cta"):
            # a breather: the narrator pauses and the music comes up (after the hook, then after every Nth beat)
            every = int(cfg.get("breather_every", 2) or 0)
            b = float(cfg.get("breather_hook_secs", 2.0)) if i == 0 else (float(cfg.get("breather_secs", 1.5)) if every and i % every == 0 else 0.0)
            if b: d += b; log(f"  {s['id']}: {b:.1f}s musical pause after this beat")
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
                if story_subjects and not c.get("own"): bg["tag"] = "ILLUSTRATIVE"   # generic footage in a story about a specific event (not your own)
                if c.get("own"): bg["tag"] = "YOUR FOOTAGE"
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
                if c.get("rate"): bg["rate"] = c["rate"]   # v2 GRAPHICS clips play at real speed and hold their last frame
                if c.get("freeze"): bg["freezeAt"] = max(0.1, round(c.get("secs", FB_SECS) - 0.1, 2))
                if c.get("textbg"): bg["textbg"] = True
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
                if c.get("tag"): bg["tag"] = c["tag"]   # ILLUSTRATION / SILHOUETTE
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
        gfx, text_bg = _resolve_overlaps(s["id"], bgs, gfx, d, log)
        icons = [] if s.get("cta") else _icons(cfg, sd, s["id"], words, gfx, d, log, extra_busy=text_bg)
        beats.append({"id": s["id"], "start": round(t, 3), "dur": round(d, 3), "words": words, "bgs": bgs, "graphics": gfx, "icons": icons})
        parts.append((sd / "voice" / f"{s['id']}.wav", d * speed)); t += d
    flt = "".join(f"[{i}:a]apad,atrim=duration={dd:.3f}[a{i}];" for i, (_, dd) in enumerate(parts)) + "".join(f"[a{i}]" for i in range(len(parts))) \
        + f"concat=n={len(parts)}:v=0:a=1" + (f",atempo={speed:.4f}" if abs(speed - 1.0) > 1e-4 else "") + ",loudnorm=I=-14:TP=-1.5[out]"
    args = sum([["-i", p] for p, _ in parts], [])
    media.ff(*args, "-filter_complex", flt, "-map", "[out]", "-ar", 48000, pub / "voice.wav")
    data = {"audio": "voice.wav", "total": round(t, 3), "tag": plan.get("tag", ""), "beats": beats}
    (sd / "used.json").write_text(json.dumps(sorted(set(used)), indent=1), encoding="utf-8")
    from .render_media import sanitize_timeline
    sanitize_timeline(data, pub, log)
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
           f"--concurrency={render_concurrency(cfg)}", "--jpeg-quality=92", "--crf=18", "--log=error"]
    for attempt in range(3):
        p = subprocess.run(cmd, cwd=rdir, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
        if p.returncode == 0 or BROWSER_FLAKE not in (p.stdout + p.stderr) or attempt == 2: break
        time.sleep(10)
    if p.returncode != 0 or not tmp.exists():
        raise RuntimeError(" / ".join((p.stdout + p.stderr).strip().splitlines()[-4:])[:300])
    if out.exists(): out.unlink()
    tmp.rename(out); log(f"  reconstruction {out.stem}: {g.get('scene')} ({g.get('name') or ''})")
    return out

def render_browser_args(cfg):
    """Match the installed Chrome used by local smoke tests; allow an explicit override."""
    explicit = cfg.get("remotion_browser_executable")
    candidates = [Path(explicit)] if explicit else [
        Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe"] if os.name == "nt" else []
    for path in candidates:
        if path.is_file(): return [f"--browser-executable={path}"]
    if explicit: raise RuntimeError(f"Configured Remotion browser not found: {explicit}")
    return []


def render_concurrency(cfg):
    # Percentage-based fan-out exhausts RAM with concurrent 1080x1920 decoders.
    # Bound automatic settings; explicit numeric settings remain an override.
    value = cfg.get("short_concurrency", "75%")
    return 2 if str(value).endswith("%") else value


def do_render(job, plan, cfg, meta, log, stop):
    total = build(job, plan, cfg, log)
    rdir = _ensure_remotion(log)
    out_dir = job / "output"; out_dir.mkdir(exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9]+", "_", plan["title"]).strip("_")[:60] or "short"
    out = out_dir / f"{safe}_short.mp4"; tmp = out_dir / "_short_rendering.mp4"
    cmd = [_npx(), "remotion", "render", "src/Root.tsx", "Teaser", str(tmp), f"--public-dir={job / 'short' / 'public'}",
           f"--concurrency={cfg.get('short_concurrency', '75%')}", "--jpeg-quality=95", "--crf=16", "--log=info", f"--gl={_gl(cfg)}"]
    browser_args = render_browser_args(cfg)
    cmd.extend(browser_args)
    log(f"  Render browser: {browser_args[0].split('=', 1)[1] if browser_args else 'Remotion default'}")
    log(f"Rendering the Short with Remotion ({total:.0f}s of video; concurrency {render_concurrency(cfg)})...")
    # If the native compositor rejects a valid video, try browser decoding first.
    # Card recovery is per asset and retries are bounded, including browser startup.
    from .render_media import fallback_failed_video
    timeline = job / "short" / "public" / "teaser.json"
    data = json.loads(timeline.read_text(encoding="utf-8"))
    videos = {b.get("src") for beat in data["beats"] for b in beat.get("bgs", []) if b.get("type") == "video"}
    browser_retries = 0
    for attempt in range(2 * len(videos) + 3):
        p = subprocess.Popen(cmd, cwd=rdir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        last, t0, tail, errline = "", time.time(), [], ""
        for line in p.stdout:
            line = line.strip()
            if line:
                last = line; tail = (tail + [line])[-40:]
                if "VS-MEDIA-ERROR" in line: log("  Remotion media error: " + line[line.index("VS-MEDIA-ERROR") + 15:][:300])
                if not errline and re.search(r"\b\w*Error\b|error:", line) and "│" not in line and not line.lstrip().startswith("at "): errline = line[:300]
            if time.time() - t0 > 30 and last: log("  " + last[:160]); t0 = time.time()
            if stop(): p.kill(); raise RuntimeError("cancelled")
        if p.wait() == 0: break
        if browser_retries < 2 and any(BROWSER_FLAKE in l for l in tail):
            # headless Chrome sometimes starts slowly (busy GPU/disk); Remotion gives it 25 s - just start again
            browser_retries += 1
            log(f"  Remotion couldn't connect to its browser in time; retrying the render ({browser_retries + 1} of 3)"); time.sleep(10); continue
        if fallback_failed_video(timeline, job / "short" / "public", errline + "\n" + "\n".join(tail), log):
            continue
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
    if "Internet Archive" in srcs: desc += ["Archival footage: Internet Archive (public domain).", ""]
    fbf = job / "short" / "fallback.json"
    creds = sorted({i["credit"] for v in (json.loads(fbf.read_text(encoding="utf-8")) if fbf.exists() else {}).values() for i in v if i.get("credit")})
    if creds: desc += creds + [""]
    desc += ["#Shorts"]
    (out_dir / "youtube_short_description.txt").write_text("\n".join(desc), encoding="utf-8")
    log(f"Short finished: {out} ({media.dur(out):.0f}s)")
    return out
