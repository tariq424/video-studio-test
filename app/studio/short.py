"""Vertical YouTube Short (2-3 min): script -> stock footage (Pexels, auto-vetted) -> narration -> Remotion render.
Almost no GPU: only the narration (WanGP TTS) and the clip vetting (small vision model) touch the GPU."""
import base64, io, json, math, os, re, shutil, subprocess, time
from pathlib import Path
import requests
from . import config, media
from .llm import LLM, parse_json
from .writer import SYSTEM, make_notes, fact_check

GAP, TAIL, MAX_SECS = 0.35, 2.2, 176.0   # YouTube Shorts allow up to 180 s; keep a margin
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
  "technology", "innovation"), no brand names, no famous people, nothing that is mostly text.

Also give "title" (max 60 chars, YouTube title), "tag" (max 28 chars, small label shown at the top, e.g. "MOONSHOTS #293 · CONDENSED"),
"description" (2-3 sentences for YouTube that credit {channel} and the original), and "source_spoken": how a narrator would
name the source in a sentence, e.g. "the Moonshots podcast, episode two ninety-three" or "a NotebookLM briefing on battery recycling".

Reply with ONLY JSON:
{{"title":"...","tag":"...","description":"...","source_spoken":"...","beats":[{{"vo":"...","graphics":[{{"at":null,"g":{{...}}}},{{"at":"word","g":{{...}}}}],"queries":["...","..."]}}]}}"""

def _log_none(m): pass

# ---------------------------------------------------------------- script
def write_short(cfg, meta, transcript, secs, mode, long_title, log, stop, srcdir):
    words = int((secs - 7 - GAP * 11) * cfg.get("voice_wpm", 142) / 60)   # measured pace of the cloned narrator incl. pauses
    nb = max(7, min(12, round(words / 38)))
    title, channel = meta.get("title") or "the source", meta.get("channel") or meta.get("uploader") or "the creator"
    with LLM(cfg, log, stop) as llm:
        log(f"Writing the Short with {llm.name} (~{secs:.0f}s, {words} words, {nb} beats)...")
        notes = make_notes(llm, meta, transcript, max(words, 1500), log, stop, srcdir)
        def chk(j):
            b = j.get("beats")
            if not isinstance(b, list) or len(b) < 6: raise ValueError("need at least 6 beats")
            for x in b:
                if not isinstance(x.get("vo"), str) or not x.get("queries"): raise ValueError("beat missing vo or queries")
            n = sum(len(x["vo"].split()) for x in b)
            if n < words * 0.88: raise ValueError(f"narration is {n} words in total but must be about {words}; add detail from the notes")
            if n > words * 1.1: raise ValueError(f"narration is {n} words in total but must be at most {int(words * 1.05)}; cut weaker points")
        prompt = SHORT.format(secs=int(secs), words=words, title=title, channel=channel, notes=notes[:24000], nb=nb,
                              people=(meta.get("description") or "")[:1200] or "(see notes)")
        try: j = llm.chat_json(SYSTEM, prompt, max_tokens=8000, check=chk)
        except RuntimeError:
            log("  length still short after 3 tries; keeping the best version")
            j = llm.chat_json(SYSTEM, prompt, max_tokens=8000, check=lambda x: None if x.get("beats") else (_ for _ in ()).throw(ValueError("no beats")))
        plan = {"title": (j.get("title") or title)[:90], "tag": (j.get("tag") or "CONDENSED")[:32].upper(),
                "source_spoken": (j.get("source_spoken") or title)[:120],
                "description": j.get("description", ""), "mode": mode, "sections": []}
        for i, b in enumerate(j["beats"]):
            gs = [g for g in (b.get("graphics") or []) if isinstance(g, dict) and isinstance(g.get("g"), dict) and g["g"].get("kind") in KINDS][:2]
            for g in gs:   # a counting-up number can't carry a range like "$5-10B"
                if g["g"]["kind"] == "stat" and re.search(r"\d", str(g["g"].get("prefix", "")) + str(g["g"].get("suffix", ""))):
                    g["g"]["kind"] = "hook"; g["g"]["lines"] = [f"{g['g'].get('prefix', '')}{g['g'].get('value', '')}{g['g'].get('suffix', '')}", str(g["g"].get("label", "")).upper()]; g["g"]["accent"] = 0
            plan["sections"].append({"id": f"b{i}", "title": f"Beat {i + 1}", "vo": re.sub(r"\s+", " ", b["vo"]).strip(),
                                     "queries": [q for q in b.get("queries", []) if isinstance(q, str)][:3] or ["city skyline aerial"],
                                     "visuals": [{"type": "chart", "chart": g["g"], "at": g.get("at")} for g in gs]})
        log("Checking the Short against the source (names, attributions, numbers)...")
        plan = fact_check(llm, plan, meta, transcript, log, stop)
    n = sum(len(x["vo"].split()) for x in plan["sections"])
    if n > words * 1.12: log(f"  NOTE: script is {n} words (target {words}); trim it in review or it will be sped up to fit 3:00")
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
        else:
            secs = len(s["vo"].split()) / cfg.get("voice_wpm", 142) * 60 + GAP
            slots.append({"id": s["id"], "text": s["vo"], "queries": s["queries"]})
            need[s["id"]] = max(2, min(3, math.ceil(secs / 6.0)))
    picked = footage.fill(cfg, slots, "portrait", need, d, log, stop, want_long_side=2560, max_secs=10.0, state_file=d / "footage.json", fallback=True)
    (d / "pick.json").write_text(json.dumps(picked, indent=1), encoding="utf-8")
    n = sum(len(v) for v in picked.values()); short_ = [k for k, v in picked.items() if len(v) < need[k]]
    log(f"Stock footage: {n} clips ready" + (f"; fewer than wanted for {', '.join(short_)} (others will be reused)" if short_ else ""))

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
    if raw_total > MAX_SECS:
        speed = raw_total / (MAX_SECS - 1)
        if speed > 1.12: log(f"  WARNING: narration is {raw_total:.0f}s; even sped up it would exceed 3 minutes. Shorten the script."); speed = 1.12
        log(f"  narration {raw_total:.0f}s is over the Shorts limit; speeding it up {speed:.2f}x")
    pool = [c for v in pick.values() for c in v]
    beats, parts, t = [], [], 0.0
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
        while borrow and cap(clips) < d + 0.3 and k < len(borrow):
            c = borrow[(i * 5 + k) % len(borrow)]; k += 1
            if all(c["id"] != x["id"] for x in clips): clips.append(c)
        bgs = []
        clips = [c for c in clips if _clip_len(sd, c) > 0]
        caps = [_clip_len(sd, c) / 0.85 for c in clips]; tot = sum(caps) or 1.0; t0 = 0.0
        for k, c in enumerate(clips):   # each clip gets screen time in proportion to its length, so none runs out early
            src = sd / "stock" / "clips" / f"{c['id']}.mp4"
            dst = pub / "media" / "stock" / f"{c['id']}.mp4"
            if not dst.exists(): shutil.copy2(src, dst)
            bg = {"src": f"media/stock/{c['id']}.mp4", "type": "video", "from": round(t0, 3)}
            t0 += d * caps[k] / tot if tot >= d else min(caps[k], d - t0)
            if c.get("orient") == "landscape": bg["fit"] = "frame"
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
        + f"concat=n={len(parts)}:v=0:a=1" + (f",atempo={speed:.4f}" if speed > 1.0 else "") + ",loudnorm=I=-14:TP=-1.5[out]"
    args = sum([["-i", p] for p, _ in parts], [])
    media.ff(*args, "-filter_complex", flt, "-map", "[out]", "-ar", 48000, pub / "voice.wav")
    data = {"audio": "voice.wav", "total": round(t, 3), "tag": plan.get("tag", ""), "beats": beats}
    (pub / "teaser.json").write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    log(f"Short timeline: {t:.1f}s, {len(beats)} beats, {sum(len(b['bgs']) for b in beats)} clips")
    return t

def _npx():
    for n in ("npx.cmd", "npx"):
        p = shutil.which(n)
        if p: return p
    raise RuntimeError("Node.js (npx) not found. Run Install in Pinokio again.")

def do_render(job, plan, cfg, meta, log, stop):
    total = build(job, plan, cfg, log)
    rdir = config.ROOT / "remotion"
    if not (rdir / "node_modules" / "@remotion" / "cli").exists():
        log("Installing the Remotion renderer (one time)...")
        subprocess.run([shutil.which("npm.cmd") or shutil.which("npm") or "npm", "install", "--no-audit", "--no-fund"], cwd=rdir, check=True, timeout=1800)
    out_dir = job / "output"; out_dir.mkdir(exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9]+", "_", plan["title"]).strip("_")[:60] or "short"
    out = out_dir / f"{safe}_short.mp4"; tmp = out_dir / "_short_rendering.mp4"
    cmd = [_npx(), "remotion", "render", "src/Root.tsx", "Teaser", str(tmp), f"--public-dir={job / 'short' / 'public'}",
           f"--concurrency={cfg.get('short_concurrency', '75%')}", "--jpeg-quality=95", "--crf=16", "--log=info"]
    log(f"Rendering the Short with Remotion ({total:.0f}s of video)...")
    p = subprocess.Popen(cmd, cwd=rdir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    last, t0 = "", time.time()
    for line in p.stdout:
        line = line.strip()
        if line: last = line
        if time.time() - t0 > 30 and last: log("  " + last[:160]); t0 = time.time()
        if stop(): p.kill(); raise RuntimeError("cancelled")
    if p.wait() != 0: raise RuntimeError("Remotion render failed: " + last[:300])
    if out.exists(): out.unlink()
    tmp.rename(out)
    # YouTube description: credit the source we summarised; stock libraries need no credit (NASA asks for a courtesy credit)
    pick = json.loads((job / "short" / "stock" / "pick.json").read_text(encoding="utf-8"))
    srcs = {c.get("src", "Pexels") for cs in pick.values() for c in cs}
    src = meta.get("webpage_url") or ""
    desc = [plan["title"], "", plan.get("description", ""), ""]
    if plan.get("mode") == "both": desc += ["Full breakdown: <PASTE LONG VIDEO LINK HERE>", ""]
    desc += ["Summarized from: " + meta.get("title", "") + (f" - {meta.get('channel')}" if meta.get("channel") else "") + (f"\n{src}" if src else ""), ""]
    if "NASA" in srcs: desc += ["Space footage courtesy of NASA.", ""]
    desc += ["#Shorts"]
    (out_dir / "youtube_short_description.txt").write_text("\n".join(desc), encoding="utf-8")
    log(f"Short finished: {out} ({media.dur(out):.0f}s)")
    return out
