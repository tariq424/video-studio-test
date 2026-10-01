"""Turn a long transcript into an explainer script + shot plan, in chunks:
  1. NOTES    - each ~3.5-7k-word slice of the transcript is boiled down to its substantive points (fluff dropped)
  2. OUTLINE  - the merged notes become a section outline with a word budget per section
  3. SECTIONS - each section's narration + visuals is written separately (small, reliable JSON)
Works with Claude, z.ai GLM, or the local Qwen3-8B (see llm.py)."""
import json, math, re
from .llm import LLM

SYSTEM = """You are a senior documentary writer and editor. You condense long talks and podcasts into tight,
accurate, engaging explainer videos narrated by one voice. You cut all fluff: greetings, banter, sponsor reads,
self-promotion, repetition, tangents and filler. You keep the substance: the key claims, arguments, numbers,
predictions and examples, and you attribute them to whoever said them."""

NOTES = """Below is part {i} of {n} of the transcript of "{title}" by {channel}.
People in this episode (use these spellings; captions often mishear names): {people}
Extract ONLY the substantive content as compact bullet notes:
- key claims, arguments, predictions, numbers, dates, names, concrete examples and memorable analogies
- say who said it only when it is clear (host or guest name); questions from listeners are questions, not claims
- mark jokes, hypotheticals and steelman arguments as such
- skip greetings, banter, jokes, ads/sponsors, self-promotion, calls to subscribe, repetition and filler
- auto-captions may mishear names and numbers: skip anything garbled or uncertain
At most {max_words} words. Plain bullets starting with "- ". No introduction, no conclusion.

TRANSCRIPT PART {i}/{n}:
{chunk}"""

OUTLINE = """You are planning a {minutes}-minute explainer video (about {words} words of narration) that condenses
"{title}" by {channel}. Below are notes on the whole episode, in order.

Build the outline:
- section 1 is a hook (15-25 seconds, about {hook_words} words) that makes the viewer want to keep watching
- then {nsec_lo}-{nsec_hi} content sections, each making ONE clear point, ordered for a clear story (not necessarily transcript order);
  merge points that repeat, drop weak ones
- last section: closing with the key takeaways (about {close_words} words)
- section titles are short (2-6 words)
- "points": 2-6 bullet facts from the notes that the section must cover (keep numbers and who said them)
- "words": narration word budget for the section; all budgets must add up to about {words}

Reply with ONLY JSON:
{{"title":"video title, max 70 chars","subtitle":"one-line hook for the title card",
 "youtube_description":"2-4 sentences for YouTube; credit {channel} and the original episode",
 "sections":[{{"title":"...","points":["..."],"words":120}}]}}

NOTES:
{notes}"""

SECTION = """Write section {k} of {n} of an explainer video that condenses "{title}" by {channel}.
Video outline (for context and flow): {outline}
THIS SECTION: "{stitle}"{role}
Must cover these points (use only these facts; never invent numbers, quotes or names):
{points}

NARRATION: {words} words (count them; stay within +/-10%). Longer sections should add detail, examples and context from the points, never padding. Calm, clear documentary voice-over. Short sentences, plain words.
Attribute opinions and predictions to the speaker ("Diamandis argues...", "his guest predicts..."); present predictions
as predictions. Write numbers as spoken ("four point seven percent", "twenty thirty", "ten billion dollars").
No markdown, stage directions or speaker labels. Flow naturally from the previous section; don't repeat its content.
Don't greet the viewer or say "in this section".

VISUALS: exactly {nvis} visuals in order, matching what the narration says at that moment.
- "chart" for concrete numbers, comparisons, rankings, timelines or lists of key points (about 1 in 5 visuals).
- "motion": {motion_rule}
- "still" for everything else. The first visual is a still or chart.
Image/video prompt rules: photorealistic, cinematic; describe subject, setting, lighting and camera in 20-45 words; self-contained.
No text, captions, logos, brand names or readable screens; avoid anything that would carry writing (documents, certificates, labels, signs, dashboards, code on screens), because the image model turns it into gibberish. No real, identifiable people (describe generic people).
Prefer simple compositions (landscapes, objects, machines, buildings, one to three people). Avoid close-ups of hands
and groups or pairs of humanoid robots (a single robot is fine; prefer industrial arms and machines). Motion prompts describe one simple continuous camera move or action.
Chart specs (object in "chart"), one of:
 {{"kind":"stat","big":"$10B","caption":"what it is"}}
 {{"kind":"bar","title":"...","subtitle":"...","labels":["A","B"],"values":[1,2],"unit":"%","note":"source/assumption"}}
 {{"kind":"line","title":"...","subtitle":"...","x":[2020,2025],"y":[1,5],"xlabel":"","ylabel":"","note":""}}
 {{"kind":"compare","title":"...","left":{{"head":"...","body":"..."}},"right":{{"head":"...","body":"..."}}}}
 {{"kind":"cards","title":"...","items":[{{"head":"...","body":"..."}}]}}  (2-4 items)
 {{"kind":"timeline","title":"...","events":[{{"label":"...","when":"2027"}}]}}  (2-6 events)
 {{"kind":"quote","text":"short paraphrased key claim","who":"speaker name"}}
Chart numbers must come from the points; if a chart shows an illustrative shape, put "Illustrative" in its note. Keep chart text short.

Reply with ONLY JSON:
{{"vo":"the narration","visuals":[{{"type":"still","prompt":"..."}},{{"type":"chart","chart":{{...}}}},{{"type":"motion","prompt":"..."}}]}}"""


FACTCHECK = """You are the fact-checker and copy editor for an explainer video that condenses "{title}" by {channel}.
Official episode description (use it for the correct spelling of people's names):
{desc}

Below is one section of narration, followed by the transcript passages it is based on (auto-captions: names and
numbers may be misheard; trust the description for spellings).

Check the narration against the transcript and fix it:
- wrong or misspelled names (e.g. captions often mangle names; use the description), wrong speaker attributions
  (only attribute a claim to a person if the transcript makes it clear; otherwise say "one of the hosts" or "a listener")
- claims that the transcript doesn't support, exaggerations, or jokes presented as serious claims: correct or remove them
- statements that misrepresent what was meant (e.g. a joke, a steelman, a question from a listener)
- grammar and awkward phrasing; keep the calm documentary voice and numbers written as spoken words
Keep roughly the same length ({words} words). Do not add new facts.
If something is important but you cannot resolve it from the transcript, keep the safest wording and list it in "questions"
as a short plain-English question for the producer.

SECTION TITLE: {stitle}
NARRATION:
{vo}

CHART TEXTS IN THIS SECTION (fix names/claims in these too; return them in the same order):
{charts}

TRANSCRIPT PASSAGES:
{passages}

Reply with ONLY JSON: {{"vo":"corrected narration","charts":[...same chart objects, corrected...],"changes":["short note per change"],"questions":["..."]}}"""

_STOP = set("the a an and or but of to in on for with at by from is are was were be been it this that these those as not no so if then than too very just about into over under more most less least can could would should will may might do does did have has had you your we our they their he his she her i me my them what which who whom how why when where there here all any some such only own same other".split())

def _passages(transcript_words, text, n=2, size=900):
    kw = {w.lower().strip(".,!?\"'():;") for w in text.split()}
    kw = {w for w in kw if len(w) > 3 and w not in _STOP}
    best = []
    step = size // 2
    for i in range(0, max(1, len(transcript_words) - size + 1), step):
        win = transcript_words[i:i + size]
        sc = sum(1 for w in win if w.lower().strip(".,!?\"'():;") in kw)
        best.append((sc, i))
    best.sort(reverse=True)
    picked = []
    for sc, i in best:
        if all(abs(i - j) >= size for j in picked): picked.append(i)
        if len(picked) == n: break
    return "\n...\n".join(" ".join(transcript_words[i:i + size]) for i in sorted(picked))

def fact_check(llm, plan, meta, transcript, log, stop=None):
    words = transcript.split()
    desc = (meta.get("description") or "")[:2500]
    title, channel = meta.get("title") or "", meta.get("channel") or meta.get("uploader") or ""
    questions = []
    for k, s in enumerate(plan["sections"], 1):
        if stop and stop(): raise RuntimeError("stopped")
        charts = [v for v in s["visuals"] if v["type"] == "chart"]
        log(f"  checking section {k}/{len(plan['sections'])} against the transcript")
        def chk(j):
            if not isinstance(j.get("vo"), str) or len(j["vo"].split()) < 0.6 * len(s["vo"].split()): raise ValueError("narration missing or cut too much")
        try:
            j = llm.chat_json(SYSTEM, FACTCHECK.format(title=title, channel=channel, desc=desc, stitle=s["title"],
                    words=len(s["vo"].split()), vo=s["vo"], charts=json.dumps([c["chart"] for c in charts], ensure_ascii=False),
                    passages=_passages(words, s["vo"] + " " + s["title"])), max_tokens=6000, check=chk)
        except Exception as e:
            log(f"  (check skipped for this section: {str(e)[:80]})"); continue
        s["vo"] = j["vo"]
        newc = j.get("charts") or []
        if isinstance(newc, list) and len(newc) == len(charts):
            for c, nc in zip(charts, newc):
                if isinstance(nc, dict) and nc.get("kind") == c["chart"].get("kind"): c["chart"] = nc
        for ch in (j.get("changes") or [])[:6]: log(f"    fixed: {str(ch)[:140]}")
        for q in j.get("questions") or []:
            if isinstance(q, str) and q.strip(): questions.append(f"Section {k} ({s['title']}): {q.strip()}")
    plan["questions"] = questions; plan["checked"] = True
    return plan

def _nw(s): return len(s.split())

def _split(text, n):
    w = text.split()
    k = max(1, math.ceil(len(w) / n)); size = math.ceil(len(w) / k)
    return [" ".join(w[max(0, i * size - 100):(i + 1) * size]) for i in range(k)]

def make_notes(llm, meta, transcript, words, log, stop=None, workdir=None):
    """Boil the source down to substantive bullet notes (cached in workdir/notes.txt so long + short share them)."""
    cache = workdir / "notes.txt" if workdir else None
    if cache and cache.exists() and len(cache.read_text(encoding="utf-8").split()) > 100:
        log("  using notes already made for this source"); return cache.read_text(encoding="utf-8")
    title, channel = meta.get("title") or "the episode", meta.get("channel") or meta.get("uploader") or "the host"
    chunks = _split(transcript, llm.chunk_words)
    note_budget = max(150, min(600, int(words * 1.6 / len(chunks))))
    notes = []
    for i, ch in enumerate(chunks, 1):
        if stop and stop(): raise RuntimeError("stopped")
        log(f"  notes {i}/{len(chunks)}")
        notes.append(llm.chat(SYSTEM, NOTES.format(i=i, n=len(chunks), title=title, channel=channel, people=(meta.get("description") or "")[:1200],
                                                  max_words=note_budget, chunk=ch), max_tokens=4000).strip())
    if sum(len(n.split()) for n in notes) < 60 * len(notes):
        raise RuntimeError("The AI returned (nearly) empty notes; stopping so the script isn't invented. Check the model/key.")
    notes_txt = "\n\n".join(f"[Part {i}]\n{n}" for i, n in enumerate(notes, 1))
    if workdir: (workdir / "notes.txt").write_text(notes_txt, encoding="utf-8")
    return notes_txt

def write_plan(cfg, meta, transcript, minutes, log, stop=None, workdir=None):
    words = int(minutes * cfg["wpm"])
    spv = cfg["seconds_per_visual"]
    title, channel = meta.get("title") or "the episode", meta.get("channel") or meta.get("uploader") or "the host"
    with LLM(cfg, log, stop) as llm:
        log(f"Writing script with {llm.name} (target {words} words)...")
        # 1. notes
        notes_txt = make_notes(llm, meta, transcript, words, log, stop, workdir)
        # 2. outline
        nsec = max(4, round(minutes * 0.6))
        def chk(o):
            if not o.get("sections") or len(o["sections"]) < 3: raise ValueError("too few sections")
            for s in o["sections"]:
                if not s.get("title") or not s.get("points"): raise ValueError("section missing title/points")
        log("  outline")
        o = llm.chat_json(SYSTEM, OUTLINE.format(minutes=minutes, words=words, title=title, channel=channel,
                hook_words=int(cfg["wpm"] / 3), close_words=int(cfg["wpm"] / 2.5), nsec_lo=max(3, nsec - 2),
                nsec_hi=nsec + 2, notes=notes_txt), max_tokens=6000, check=chk)
        secs = o["sections"]
        tot = sum(int(s.get("words") or 0) for s in secs) or 1
        for s in secs: s["words"] = max(30, int((int(s.get("words") or tot / len(secs))) * words / tot))
        outline_str = " | ".join(f"{i+1}. {s['title']}" for i, s in enumerate(secs))
        # 3. sections
        total_vis = sum(max(2, round(s["words"] / cfg["wpm"] * 60 / spv)) for s in secs)
        motion_left = max(3, int(total_vis * cfg["motion_share"]))
        plan = {"title": o.get("title") or title, "subtitle": o.get("subtitle", ""),
                "youtube_description": o.get("youtube_description", ""), "sections": []}
        for k, s in enumerate(secs, 1):
            if stop and stop(): raise RuntimeError("stopped")
            nvis = max(2, round(s["words"] / cfg["wpm"] * 60 / spv))
            big = k == 1 or k == len(secs) or k == len(secs) // 2
            mrule = ("include ONE motion clip (not first) for the most dynamic moment" if big and motion_left > 0
                     else "none in this section")
            role = " (the opening hook)" if k == 1 else " (the closing: key takeaways)" if k == len(secs) else ""
            def chk2(j):
                if not isinstance(j.get("vo"), str): raise ValueError("narration missing")
                n = _nw(j["vo"])
                if n < s["words"] * 0.85: raise ValueError(f"narration is {n} words but must be about {s['words']} words; expand it with more of the section's points, examples and context")
                if not j.get("visuals"): raise ValueError("no visuals")
            log(f"  section {k}/{len(secs)}: {s['title']}")
            sec_prompt = SECTION.format(k=k, n=len(secs), title=title, channel=channel, outline=outline_str,
                    stitle=s["title"], role=role, points="\n".join("- " + p for p in s["points"]), words=int(s["words"] * 1.25),
                    nvis=nvis, motion_rule=mrule)
            try: j = llm.chat_json(SYSTEM, sec_prompt, max_tokens=4000, check=chk2)
            except RuntimeError:
                log("  length still short after 3 tries; keeping the best version")
                j = llm.chat_json(SYSTEM, sec_prompt, max_tokens=4000, check=lambda x: None if isinstance(x.get("vo"), str) and x.get("visuals") else (_ for _ in ()).throw(ValueError("bad section")))
            vis = [v for v in j["visuals"] if isinstance(v, dict)]
            want = max(2, round(_nw(j["vo"]) / cfg["wpm"] * 60 / spv))
            vis = vis[:want]   # keep visuals in step with the narration actually written
            if not big or motion_left <= 0:
                for v in vis:
                    if v.get("type") == "motion": v["type"] = "still"
            motion_left -= sum(1 for v in vis if v.get("type") == "motion")
            plan["sections"].append({"title": s["title"], "vo": j["vo"], "visuals": vis})
        plan = normalize(plan)
        log("Checking the script against the transcript (names, attributions, claims)...")
        plan = fact_check(llm, plan, meta, transcript, log, stop)
        plan = normalize(plan)
        w = sum(_nw(s["vo"]) for s in plan["sections"])
        tk = f" Tokens in/out: {llm.tokens_in}/{llm.tokens_out}" if llm.tokens_in else ""
        log(f"Script ready: {len(plan['sections'])} sections, {w} words (~{w / cfg['wpm']:.1f} min), "
            f"{sum(len(s['visuals']) for s in plan['sections'])} visuals.{tk}")
        return plan

def normalize(plan):
    """Give every section/visual a stable id and fix common issues."""
    for si, s in enumerate(plan["sections"]):
        s["id"] = f"s{si}"
        s["vo"] = re.sub(r"\s+", " ", s["vo"]).strip()
        vis = [v for v in s.get("visuals", []) if v.get("type") in ("still", "motion", "chart")]
        vis = [v for v in vis if (v["type"] == "chart" and isinstance(v.get("chart"), dict)) or (v["type"] != "chart" and v.get("prompt"))]
        if not vis: vis = [{"type": "still", "prompt": f"Cinematic establishing shot illustrating: {s['title']}"}]
        if vis[0]["type"] == "motion": vis[0]["type"] = "still"
        for vi, v in enumerate(vis): v["id"] = f"{s['id']}_{vi}"
        s["visuals"] = vis
    return plan
