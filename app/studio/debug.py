"""Pipeline debugger: breakpoints, ad-hoc pause, a mid-run debug switch, the panel chat and the decision trace.

Off by default: a job without debug never pauses here and writes no trace (only the ad-hoc "Pause now" button works on any job).

State (job state.json):
  debug: {"on": bool, "bps": ["stock_found == 0", ...], "bps_off": bool, "checked": [bid...], "chat": [...]}
  pause_req: true while a "Pause now" waits for the next safe point
  pause: {"kind": "manual"|"breakpoint", "label", "beat", "n", "where", "bp", "t"} while status == "paused"
  trace: true once the run has a trace (debug was on at some point, or it paused)

Safe points: before every stage; inside the visual ladder between AI stills / checks; after each beat of the ladder (a beat is
finished and saved there, so Resume continues with the next one). Never inside a render or a generation.

Breakpoints (checked once per beat, after the beat's visuals are decided; only while debug is on and breakpoints aren't disabled):
  beat == N                      Beat N (1-based, as on the job page)
  treatment == stock|photo|cloud|still|animate|parallax|illustration|silhouette|3d|card|graphics|simulation|capcut
                                 the beat ended up using that treatment (still = an AI still, shown with parallax; 3d = reconstruction;
                                 card = headline card or map; graphics / simulation / capcut = ladder v2 rungs 5 / 6 / 7)
  stock_found == N               coherent stock clips found for the beat (also <, >, <=, >=)
  escalated_past == stock|photo|cloud|still|animate|graphics|simulation   that step was tried and failed (stock also matches a failed real-photo step)
  narration contains "word"      case-insensitive

Trace: trace.jsonl (one event per line) and trace.md (readable: per-beat decision chains + timeline + chat) in the job folder.
The panel chat and the Claude chat read the same trace.md."""
import json, re, time
from pathlib import Path

TREAT = ("stock", "photo", "cloud", "still", "animate", "parallax", "illustration", "silhouette", "3d", "card", "graphics", "simulation", "capcut")
STEPS = ("stock", "photo", "cloud", "still", "animate", "graphics", "simulation")
WHY_NOTE = "For deeper reasoning, ask in the Claude chat."

class Paused(Exception):
    def __init__(self, info): super().__init__(info.get("label", "paused")); self.info = info

# ---------------------------------------------------------------- breakpoints
def parse(text):
    """-> canonical breakpoint text. Raises ValueError with a readable message."""
    t = (text or "").strip()
    m = re.fullmatch(r"beat\s*==?\s*(\d+)", t, re.I)
    if m: return f"beat == {int(m.group(1))}"
    m = re.fullmatch(r"treatment\s*==?\s*([a-z0-9]+)", t, re.I)
    if m:
        v = m.group(1).lower(); v = {"reconstruction": "3d", "headline": "card", "map": "card", "animation": "animate", "photos": "photo", "sim": "simulation", "physics": "simulation"}.get(v, v)
        if v not in TREAT: raise ValueError(f"treatment must be one of {', '.join(TREAT)}")
        return f"treatment == {v}"
    m = re.fullmatch(r"stock_found\s*(==?|<=|>=|<|>)\s*(\d+)", t, re.I)
    if m: return f"stock_found {'==' if m.group(1) in ('=', '==') else m.group(1)} {int(m.group(2))}"
    m = re.fullmatch(r"escalated_past\s*==?\s*([a-z]+)", t, re.I)
    if m:
        v = m.group(1).lower(); v = {"animation": "animate", "photos": "photo", "sim": "simulation", "physics": "simulation"}.get(v, v)
        if v not in STEPS: raise ValueError(f"escalated_past must be one of {', '.join(STEPS)}")
        return f"escalated_past == {v}"
    m = re.fullmatch(r"narration\s+contains\s+[\"']?(.+?)[\"']?", t, re.I)
    if m and m.group(1).strip(): return f'narration contains "{m.group(1).strip()}"'
    raise ValueError(f'not a breakpoint: "{t[:60]}". Use: beat == N, treatment == {"|".join(TREAT)}, '
                     f'stock_found == N, escalated_past == {"|".join(STEPS)}, narration contains "word"')

def parse_all(text_or_list):
    items = text_or_list if isinstance(text_or_list, list) else re.split(r"[\n;]+", text_or_list or "")
    return [parse(x) for x in items if str(x).strip()]

def _uses(info):
    out = set()
    for r in info.get("uses", []):
        r = r.replace(" (fill)", "")
        if r == "reconstruction": out.add("3d")
        elif r in ("headline", "map"): out.add("card")
        elif r == "parallax": out.update(("parallax", "still"))
        else: out.add(r)
    return out

def matches(bp, info):
    k, rest = bp.split(" ", 1)
    if k == "beat": return info.get("n") == int(rest.split()[-1])
    if k == "treatment": return rest.split()[-1] in _uses(info)
    if k == "stock_found":
        op, n = rest.split(); v = int(info.get("stock_found", 0)); n = int(n)
        return {"==": v == n, "<": v < n, ">": v > n, "<=": v <= n, ">=": v >= n}[op]
    if k == "escalated_past":
        step = rest.split()[-1]; failed = set(info.get("failed", []))
        return step in failed or (step == "stock" and "photo" in failed)
    if k == "narration":
        word = re.search(r'"(.*)"', rest).group(1).lower(); return word in (info.get("vo") or "").lower()
    return False

# ---------------------------------------------------------------- trace
def trace(jdir, ev, force=False):
    """Append an event to trace.jsonl. Only once the run has a trace (debug on at some point, or a pause), unless force."""
    from .pipeline import Job
    j = Job(jdir)
    if not (force or j.state.get("trace")): return
    if force and not j.state.get("trace"): j.save(trace=True)
    ev = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), **ev}
    with open(Path(jdir) / "trace.jsonl", "a", encoding="utf-8") as f: f.write(json.dumps(ev, ensure_ascii=False) + "\n")

def events(jdir):
    f = Path(jdir) / "trace.jsonl"
    if not f.exists(): return []
    out = []
    for ln in f.read_text(encoding="utf-8").splitlines():
        try: out.append(json.loads(ln))
        except Exception: pass
    return out

def chains(jdir):
    f = Path(jdir) / "short" / "fallback" / "chains.json"
    try: return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except Exception: return {}

def render_md(jdir):
    """Readable trace: the per-beat decision chain (what was tried, why it was rejected, what was used, your decisions) + timeline + chat."""
    from .pipeline import Job
    jdir = Path(jdir); j = Job(jdir); s = j.state
    if not s.get("trace"): return None
    lines = [f"# Debug trace: {s.get('title') or jdir.name}", f"Job {jdir.name} · status {s.get('status')} · stage {s.get('stage')}", ""]
    ch = chains(jdir)
    rv = None
    try:
        from . import review
        rv = review.load(jdir)
    except Exception: pass
    if ch:
        lines += ["## Per-beat decision chain", ""]
        for bid in sorted(ch, key=lambda b: int(b[1:]) if b[1:].isdigit() else 999):
            c = ch[bid]
            lines.append(f"### Beat {c.get('n')} ({bid})")
            lines.append(f"> {c.get('vo', '')}")
            lines.append(f"- stock clips found: {c.get('stock_found', 0)}")
            for r in c.get("stock_rejected", [])[:8]: lines.append(f"  - stock rejected: {r.get('id')} — {r.get('why')}")
            for p in c.get("photos_rejected", [])[:8]: lines.append(f"  - photo rejected: {p.get('title', p.get('id'))[:60]} — {p.get('why')}")
            for ln in c.get("chain", []): lines.append(f"- ladder: {ln}")
            lines.append(f"- used: {', '.join(c.get('uses', [])) or 'nothing'}")
            b = (rv or {}).get("beats", {}).get(bid)
            if b and b.get("decision"):
                d = b["decision"]; lines.append(f"- review decision: {d}" + (f" ({', '.join((rv['cands'][x]['rung'] for x in b.get('chosen', []) if x in rv['cands']))})" if d == "chosen" else ""))
            lines.append("")
    ev = events(jdir)
    if ev:
        lines += ["## Timeline", ""]
        for e in ev:
            k = e.get("ev")
            if k == "chat": lines.append(f"- {e['t']} chat [{e.get('backend')}] you: \"{e.get('you')}\" -> {e.get('reply')}" + (f" (action: {e.get('action')})" if e.get("action") not in (None, "none") else ""))
            else: lines.append(f"- {e['t']} {k}: " + ", ".join(f"{a}={v}" for a, v in e.items() if a not in ("t", "ev")))
    (jdir / "trace.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return jdir / "trace.md"

# ---------------------------------------------------------------- the pipeline side
class Debugger:
    def __init__(self, job, log): self.j, self.log = job, log
    def _d(self): return self.j.state.get("debug") or {}
    def active(self):
        d = self._d(); return bool(d.get("on")) and not d.get("bps_off") and bool(d.get("bps"))
    def on(self): return bool(self._d().get("on"))
    def manual(self, where, beat=None, n=None):
        """Raise Paused if 'Pause now' was pressed."""
        if self.j.state.get("pause_req"):
            raise Paused({"kind": "manual", "label": "Paused: manual", "where": where, "beat": beat, "n": n, "t": time.strftime("%H:%M:%S")})
    def point(self, info, where="short_fallback"):
        """After a beat's visuals are decided: record it, then pause for 'Pause now' or a matching breakpoint (once per beat)."""
        d = self._d(); checked = set(d.get("checked", []))
        if info["bid"] in checked: return
        hit = next((bp for bp in d.get("bps", []) if matches(bp, info)), None) if self.active() else None
        d["checked"] = sorted(checked | {info["bid"]}); self.j.save(debug=d)
        if hit:
            raise Paused({"kind": "breakpoint", "label": f"Paused: breakpoint '{hit}'", "bp": hit, "where": where, "beat": info["bid"], "n": info["n"],
                          "t": time.strftime("%H:%M:%S")})
        self.manual(where, info["bid"], info["n"])

# ---------------------------------------------------------------- panel chat (DeepSeek; why-questions get a pointer to the Claude chat)
CHAT = """You are the assistant inside a video pipeline's pause panel. The editor types an instruction or a question about ONE beat of a
vertical news Short. Pick the action that does what they ask, or answer their question from the facts below.

Beat {n} narration: "{vo}"
{ctx}Why the pipeline paused: {label}
What the pipeline tried for this beat (the visual ladder, with reasons):
{chain}
Treatments currently offered for this beat (option number. type, accepted or rejected, reason):
{cands}
Recent pipeline log:
{log}

Earlier in this conversation about this beat (oldest first):
{history}

The editor says: "{text}"

Actions:
- "refine": make a new AI still (and stock searches) with a change; "instruction" = the change in plain words (e.g. "plane diving nose-down").
- "more_stock": search more stock footage; "queries" = 1-3 searches of 3-5 words; "count" = how many clips (1-4).
- "use": use option(s) in this beat; "options" = list of option numbers in play order.
- "thumbnails": generate the thumbnails.
- "skip": use the headline card for this beat.
- "continue": resume the pipeline.
- "simulate": build a data / physics simulation of what physically happened in this beat; "module" = one of the modules below,
  "params" = its parameters, taken from the narration (numbers as plain numbers; leave out what the narration doesn't give).
- "none": no action (a question, or unclear).
Simulation modules:
{modules}
Reply with ONLY JSON: {{"kind": "action" or "why" or "claude", "action": "...", "instruction": "", "queries": [], "count": 2, "options": [],
"module": "", "params": {{}},{extra_keys}
"reply": "one or two short sentences to the editor: what you are doing, or the answer (from the facts above only; say so if they don't tell)"}}
"kind" is "why" when they ask why something happened / was rejected / was chosen, or ask you to diagnose or explain.
"kind" is "claude" (with action "none") when the request needs judgment or taste beyond these actions (rewrite the narration's
argument, design a new kind of visual, weigh editorial trade-offs): say in "reply" that it goes to Claude."""

WHYISH = re.compile(r"^\s*(why|how come|what made|explain|diagnose|what went wrong|reason)\b|\bwhy\b.*\?$", re.I)

def _cands_text(rv, bid):
    from .review import RUNG
    b = (rv or {}).get("beats", {}).get(bid)
    if not b: return "(none collected yet)", []
    out, ids = [], []
    for i, cid in enumerate(b["cands"], 1):
        c = rv["cands"][cid]; ids.append(cid)
        now = cid in (b.get("current") or [])
        out.append(f"{i}. {RUNG.get(c['rung'], c['rung'])}{' ' + c['item'].get('tag', '') if c['item'].get('tag') else ''}: "
                   f"{'accepted' if c['ok'] else 'REJECTED'} - {c['why'][:100]}{' [IN THE VIDEO NOW]' if now else ''}")
    return "\n".join(out) or "(none)", ids

def _ctx_on():
    from .edit import v2
    return v2()

def _context(j, bid, edit):
    """The script around the beat: the previous / next beat (Short), or the section's title and full narration (explainer slot)."""
    try:
        sp = j.short_plan() if not edit or not str(bid).count("_") else None
        if sp:
            secs = sp["sections"]; i = next(k for k, x in enumerate(secs) if x["id"] == bid)
            prev = secs[i - 1]["vo"] if i > 0 else "(start of the video)"; nxt = secs[i + 1]["vo"] if i + 1 < len(secs) else "(end)"
            return f"- title: {sp.get('title', '')}\n- previous beat: {prev[:300]}\n- next beat: {nxt[:300]}"
        plan = j.plan(); sid = str(bid).rsplit("_", 1)[0]
        sec = next(x for x in plan["sections"] if x["id"] == sid)
        return f"- video: {plan.get('title', '')}\n- section: {sec.get('title', '')}\n- the section's narration: {sec['vo'][:900]}"
    except Exception: return "- (not available)"

def chat(studio, jid, bid, text, cfg, edit=False):
    """-> chat entry {t, you, reply, backend, action, kind[, select]}. Executes clear actions through the review machinery.
    edit=True: post-render (timeline editor) - the same chat, run against the editor's workspace for this beat (Shorts: the job;
    long videos: job/longedit), from the saved job state; "apply" re-renders just this beat and splices it into the video."""
    from . import review
    from .llm import LLM
    j = studio.job(jid); jd = j.dir; s = j.state
    c = dict(cfg); c["script_provider"] = "deepseek" if cfg.get("deepseek_api_key") else "local"
    ch = chains(jd).get(bid, {})
    ws = None
    if edit:
        from . import edit as E
        ws = E.workspace(jd); E.open_beat(jd, bid, cfg, j.log)   # makes sure the beat has its review entry + current visual
    wsd = ws or jd
    rv = review.load(wsd)
    ctext, ids = _cands_text(rv, bid)
    p = s.get("pause") or {}
    label = "Editing the finished video (post-render): changes are rendered for this beat only and spliced in" if edit else \
        p.get("label") or ("Paused: uncertain about this beat" if s.get("status") == "awaiting_visuals" else s.get("status", ""))
    logtail = "\n".join((jd / "log.txt").read_text(encoding="utf-8").splitlines()[-30:]) if (jd / "log.txt").exists() else ""
    chain = "\n".join(f"- {x}" for x in ch.get("chain", [])) or "- (no ladder record for this beat)"
    if ch.get("stock_rejected"): chain += "\n" + "\n".join(f"- stock clip rejected: {r.get('why')}" for r in ch["stock_rejected"][:6])
    if ch.get("photos_rejected"): chain += "\n" + "\n".join(f"- real photo rejected: {r.get('why')}" for r in ch["photos_rejected"][:6])
    chain += f"\n- stock clips found: {ch.get('stock_found', 0)}; used: {', '.join(ch.get('uses', [])) or '?'}"
    from . import physics
    past = [e for e in (s.get("debug") or {}).get("chat", []) if e.get("beat") == bid][-6:]   # multi-turn: this beat's conversation
    history = "\n".join(f"- editor: {e['you']}\n  you: {e['reply'][:300]} (action: {e.get('action')})" for e in past) or "- (none)"
    vo = (ch.get("vo") or (rv or {}).get("beats", {}).get(bid, {}).get("vo", ""))
    prompt = CHAT.format(n=int(bid[1:]) + 1 if bid[1:].isdigit() else bid, vo=vo[:400],
                         label=label, chain=chain, cands=ctext, log=logtail[-3000:], text=text.replace('"', "'"), history=history,
                         modules=physics.describe(), ctx=("Script around this beat:\n" + _context(j, bid, edit) + "\n") if _ctx_on() else "",
                         extra_keys=' "src": "", "tag": "", "text": "", "kicker": "",' if edit and _ctx_on() else "")
    from .edit import v2 as _v2
    if edit:   # the finished video: no "continue"; "apply" renders the chosen treatment into the video
        prompt = prompt.replace('- "continue": resume the pipeline.', '- "apply": put the selected / named option(s) into the finished video now (re-render this beat only and splice it in); "options" = option numbers, or [] for the current selection. Only when the editor approves or asks to apply / use it in the video.' + ('\n'
            '- "supply": use the editor\'s own picture or video; "src" = the file path on this PC or the URL they gave, "tag" = "" or FILE / ILLUSTRATIVE / GENERATED.\n'
            '- "card": a headline card with the editor\'s own words on screen ("rewrite the text", "say X on screen"); "text" = the card text (max ~12 words), "kicker" = optional small label.\n'
            'Rewriting the NARRATION itself is not possible here (it changes the timing of everything after it; that needs a new render): say so and offer a card instead.' if _v2() else ''))
        prompt = prompt.replace('vertical news Short.', 'finished video (a vertical news Short or a 16:9 explainer).')
    def chk(x):
        if x.get("action") not in ("refine", "more_stock", "use", "thumbnails", "skip", "continue", "simulate", "apply", "none") + (("supply", "card") if edit and _v2() else ()): raise ValueError("unknown action")
    backend = "none"
    try:
        with LLM(c, j.log, lambda: False) as llm:
            backend = llm.name
            try: x = llm.chat_json("You are a precise assistant for a video editor. Reply with JSON only.", prompt, max_tokens=800, check=chk)
            except RuntimeError: x = {"kind": "why", "action": "none", "reply": "I couldn't work out what to do; try rephrasing."}
    except Exception as e:   # no chat model reachable (no DeepSeek key and Ollama not running): say so in the chat
        x = {"kind": "claude", "action": "none", "reply": f"The chat model isn't available ({str(e)[:120]})."}
    why = x.get("kind") == "why" or bool(WHYISH.search(text))
    to_claude = x.get("kind") == "claude"
    reply = str(x.get("reply") or "").strip()[:500]
    act, err = x.get("action", "none"), ""
    if why or to_claude: act = "none"; reply = (reply + ("\n" if reply else "") + WHY_NOTE)
    handoff = ""
    if why or to_claude:   # ready-to-paste context for the Claude chat (no API key needed: you paste it)
        handoff = (f"Video Studio job {jid}, beat {bid} (paused: {label}).\nNarration: \"{vo[:600]}\"\nVisual ladder for this beat:\n{chain}\n"
                   f"Treatments offered:\n{ctext}\nEarlier in the pause chat:\n{history}\nMy request: {text}")
    select = None
    try:
        if act == "refine":
            err = review.start(studio, jid, bid, "refine", {"text": x.get("instruction") or text}, ws=ws)
        elif act == "more_stock":
            err = review.start(studio, jid, bid, "more_stock", {"queries": x.get("queries") or [], "count": x.get("count") or 2}, ws=ws)
        elif act == "use":
            cids = [ids[int(k) - 1] for k in (x.get("options") or []) if str(k).isdigit() and 0 < int(k) <= len(ids)]
            if not cids: err = "no matching option number"
            else: review.decide(wsd, bid, "choose", cids, cfg, j.log); select = cids
        elif act == "skip":
            if edit:   # post-render "skip" = the beat's headline card, when it has one
                rv2 = review.load(wsd) or {}
                hd = next((c for c in rv2.get("beats", {}).get(bid, {}).get("cands", []) if rv2["cands"][c].get("rung") == "headline"), None)
                if hd: review.decide(wsd, bid, "choose", [hd], cfg, j.log); select = [hd]
                else: err = "no headline card for this beat"
            else: review.decide(wsd, bid, "skip")
        elif act == "thumbnails": review.thumbs(wsd, cfg, j.log, [i for i in ids])
        elif act == "simulate":
            g = physics.run(str(x.get("module") or ""), x.get("params") or {})
            if not g: err = f"no simulation for '{x.get('module')}' (not built yet, or the narration gave no usable numbers)"
            else:
                rv2 = review.load(wsd); cid = review._add(rv2, bid, {"type": "graphic", "g": g, "tag": "SIMULATION"}, "simulation", True,
                                                           f"{g['module']}: {g.get('label') or g.get('title')}")
                review.save(wsd, rv2); review.decide(wsd, bid, "choose", [cid], cfg, j.log); select = [cid]
                if edit: review.thumbs(wsd, cfg, j.log, [cid])
                reply += f"\n(Simulation added and selected for this beat: {g.get('label') or g['title']}." + (" Say 'apply it' or press Apply to video.)" if edit else ")")
        elif act == "apply":
            if not edit: err = "apply is for the finished video (timeline editor)"
            else:
                from . import edit as E
                bb = (review.load(wsd) or {}).get("beats", {}).get(bid, {})
                cids = [ids[int(k) - 1] for k in (x.get("options") or []) if str(k).isdigit() and 0 < int(k) <= len(ids)] \
                    or (bb.get("chosen") if bb.get("decision") == "chosen" else []) or []
                if not cids: err = "nothing selected to apply - pick an option first"
                else:
                    err = E.start_apply(jd, bid, cids, "auto", cfg, j.log)
                    if not err: reply += "\n(Rendering this beat and splicing it into the video...)"; select = cids
        elif act == "supply":
            if not edit: err = "supply your own file from the review panel's Supply box"
            elif not str(x.get("src") or "").strip(): err = "give the file path on this PC or a URL"
            else:
                cid = review.supply(wsd, bid, str(x["src"]), str(x.get("tag") or ""), cfg, j.log); select = [cid]   # added + selected
                reply += "\n(Your file is added and selected. Say 'apply it' or press Apply to video.)"
        elif act == "card":
            t = str(x.get("text") or "").strip()[:90]
            if not t: err = "no card text"
            else:
                rv2 = review.load(wsd); sk = dict(rv2["beats"][bid].get("skip_item") or {"type": "graphic", "g": {"kind": "headline"}})
                g = dict(sk.get("g") or {"kind": "headline"}); g.update(kind="headline", text=t, kicker=str(x.get("kicker") or g.get("kicker") or "")[:30], sub="")
                cid = review._add(rv2, bid, {"type": "graphic", "g": g}, "headline", True, f"your card: {t[:60]}")
                review.save(wsd, rv2); review.decide(wsd, bid, "choose", [cid], cfg, j.log); review.thumbs(wsd, cfg, j.log, [cid]); select = [cid]
                reply += "\n(Card added and selected." + (" Say 'apply it' or press Apply to video.)" if edit else ")")
        elif act == "continue":
            if edit: err = "the video is finished - say 'apply it' to put the change in"
            elif s.get("status") == "paused": studio.resume(jid)
            else: err = "use Continue to render on the review panel"
    except Exception as e: err = str(e)[:200]
    if err: reply += f"\n(Couldn't do it: {err})"
    ent = {"t": time.strftime("%H:%M:%S"), "beat": bid, "you": text[:500], "reply": reply, "backend": "Claude (paste)" if to_claude else backend,
           "action": act, "kind": "claude" if to_claude else "why" if why else "action", "handoff": handoff, "mode": "edit" if edit else "pause"}
    if select: ent["select"] = select
    d = j.state.get("debug") or {}; d.setdefault("chat", []).append(ent); j.save(debug=d)
    trace(jd, {"ev": "chat", **{k: ent[k] for k in ("beat", "you", "reply", "backend", "action")}}, force=True)
    render_md(jd)
    j.log(f"Panel chat ({backend}) on {bid}: {text[:80]} -> {act}")
    return ent
