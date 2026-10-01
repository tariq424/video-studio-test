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

NOTES ON THE SOURCE (use only these facts):
{notes}

Write {nb} beats that tell one story. Each beat is 28-50 words (about 10-18 seconds spoken).
- Beat 1 is the hook: within the first sentence, a surprising claim, number or sharp question from the notes. No greetings, no "in this video".
- Middle beats: the strongest points, one idea per beat, concrete (numbers, names, examples). Attribute opinions and predictions to who said them.
- Last beat: the payoff / biggest takeaway, ending on a strong line.
Narration: spoken, punchy, short sentences, plain words, numbers written as spoken words ("ten billion dollars", "twenty thirty").
No markdown, no stage directions. Never invent numbers, quotes or names.

For each beat also give:
- "graphics": 1 or 2 on-screen graphics. The first appears as the beat starts ("at": null). An optional second one appears when
  the word in "at" is spoken ("at" must be ONE word that appears in that beat's narration, from its second half). Kinds:
   {{"kind":"hook","lines":["2-4 short lines"],"accent":1}}   (accent = index of the line to highlight; use for beat 1 and big questions)
   {{"kind":"quote","text":"max 16 words","who":"speaker name"}}
   {{"kind":"stat","value":5,"decimals":0,"prefix":"","suffix":"x","label":"2-4 words","sub":"optional short line"}}
   {{"kind":"compare","badge":"vs","note":"short source line","left":{{"icon":"one emoji","head":"1-3 words","body":"2-5 words"}},"right":{{"icon":"one emoji","head":"1-3 words","body":"2-5 words"}}}}
   {{"kind":"icons","title":"short title","items":[{{"icon":"one emoji","label":"1-2 words"}}]}}   (3-4 items)
   {{"kind":"timeline","title":"short title","steps":[{{"when":"short","label":"2-4 words"}}]}}   (3 steps)
  Vary the kinds across beats. Keep all graphic text short. Stat values are plain numbers taken from the notes.
- "queries": 2 stock-video search phrases (2-4 words each) for what to SHOW while this beat plays: concrete and filmable,
  e.g. "server room lights", "doctor reading scan", "city traffic night aerial", "students library". No abstract words
  ("AI", "future", "concept", "technology"), no brand names, no famous people, nothing that is mostly text or a screen.

Also give "title" (max 60 chars, YouTube title), "tag" (max 28 chars, small label shown at the top, e.g. "MOONSHOTS #293 · CONDENSED"),
and "description" (2-3 sentences for YouTube that credit {channel} and the original).

Reply with ONLY JSON:
{{"title":"...","tag":"...","description":"...","beats":[{{"vo":"...","graphics":[{{"at":null,"g":{{...}}}},{{"at":"word","g":{{...}}}}],"queries":["...","..."]}}]}}"""

VET = """You are vetting a stock video clip for a vertical YouTube Short. The image shows 4 frames from the clip (in order).
While this clip plays, the narration says: "{vo}"
The clip was found by searching: "{query}"
Score how well it works as a background for that moment (0-10): 10 = clearly fits the topic and mood, good quality;
5 = generic but acceptable; 0 = unrelated, nonsensical, ugly or confusing.
Also report problems: readable text, captions, logos or watermarks covering the frame; a jarring cut to an unrelated scene
between frames; distorted or low-quality footage; anything inappropriate.
Reply with JSON only: {{"score": 0-10, "text": true|false, "problem": "short reason or empty"}}"""

def _log_none(m): pass

# ---------------------------------------------------------------- script
def write_short(cfg, meta, transcript, secs, mode, long_title, log, stop, srcdir):
    words = int((secs - 7 - GAP * 11) * cfg["wpm"] / 60)
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
            if n < words * 0.85: raise ValueError(f"narration is {n} words in total but must be about {words}; add detail from the notes")
        prompt = SHORT.format(secs=int(secs), words=int(words * 1.1), title=title, channel=channel, notes=notes[:24000], nb=nb)
        try: j = llm.chat_json(SYSTEM, prompt, max_tokens=8000, check=chk)
        except RuntimeError:
            log("  length still short after 3 tries; keeping the best version")
            j = llm.chat_json(SYSTEM, prompt, max_tokens=8000, check=lambda x: None if x.get("beats") else (_ for _ in ()).throw(ValueError("no beats")))
        plan = {"title": (j.get("title") or title)[:90], "tag": (j.get("tag") or "CONDENSED")[:32].upper(),
                "description": j.get("description", ""), "mode": mode, "sections": []}
        for i, b in enumerate(j["beats"]):
            gs = [g for g in (b.get("graphics") or []) if isinstance(g, dict) and isinstance(g.get("g"), dict) and g["g"].get("kind") in KINDS][:2]
            plan["sections"].append({"id": f"b{i}", "title": f"Beat {i + 1}", "vo": re.sub(r"\s+", " ", b["vo"]).strip(),
                                     "queries": [q for q in b.get("queries", []) if isinstance(q, str)][:3] or ["city skyline aerial"],
                                     "visuals": [{"type": "chart", "chart": g["g"], "at": g.get("at")} for g in gs]})
        log("Checking the Short against the source (names, attributions, numbers)...")
        plan = fact_check(llm, plan, meta, transcript, log, stop)
    # closing call-to-action beat
    if mode == "both":
        cta_vo = "Want the full story? The complete breakdown is linked below."
        cta = {"kind": "cta", "badge": "FULL BREAKDOWN", "title": long_title or plan["title"], "line": "Watch it, linked below"}
    else:
        cta_vo = "Follow for more breakdowns like this. The original is credited below."
        cta = {"kind": "cta", "badge": "SOURCE", "title": title[:80], "line": "Credits below"}
    plan["sections"].append({"id": f"b{len(plan['sections'])}", "title": "Call to action", "vo": cta_vo, "queries": [], "cta": cta, "visuals": []})
    w = sum(len(s["vo"].split()) for s in plan["sections"])
    log(f"Short script ready: {len(plan['sections'])} beats, {w} words (~{w / cfg['wpm'] * 60 + GAP * len(plan['sections']) + TAIL:.0f}s)")
    return plan

# ---------------------------------------------------------------- stock footage
def _pexels_key():
    env = config.ROOT / ".env"
    if env.exists():
        for l in env.read_text(encoding="utf-8").splitlines():
            if l.startswith("PEXELS_API_KEY="): return l.split("=", 1)[1].strip().strip("\"'")
    return ""

def _search(key, q, log):
    for attempt in range(3):
        r = requests.get("https://api.pexels.com/videos/search", headers={"Authorization": key},
                         params={"query": q, "orientation": "portrait", "per_page": 10, "size": "medium"}, timeout=30)
        if r.status_code == 429: log("  Pexels rate limit; waiting 60s"); time.sleep(60); continue
        if r.status_code != 200: log(f"  Pexels search '{q}' failed: HTTP {r.status_code}"); return []
        out = []
        for v in r.json().get("videos", []):
            files = [f for f in v.get("video_files", []) if f.get("width") and f.get("height") and f["height"] > f["width"] and f["height"] >= 1280]
            pics = [p["picture"] for p in sorted(v.get("video_pictures", []), key=lambda p: p.get("nr", 0))]
            if not files or v.get("duration", 0) < 6 or len(pics) < 4: continue
            f = sorted(files, key=lambda f: abs(f["height"] - 1920))[0]
            out.append({"id": str(v["id"]), "query": q, "dur": v["duration"], "file": f["link"], "page": v["url"],
                        "author": v["user"]["name"], "author_url": v["user"].get("url", ""), "pics": pics})
        return out
    return []

def _sheet(pics, out):
    from PIL import Image
    idx = [round(i * (len(pics) - 1) / 3) for i in range(4)]
    ims = []
    for i in idx:
        r = requests.get(pics[i], timeout=30); r.raise_for_status()
        im = Image.open(io.BytesIO(r.content)).convert("RGB"); im.thumbnail((360, 640)); ims.append(im)
    w = sum(i.width for i in ims) + 12 * 3; h = max(i.height for i in ims)
    sheet = Image.new("RGB", (w, h), (0, 0, 0)); x = 0
    for im in ims: sheet.paste(im, (x, 0)); x += im.width + 12
    sheet.save(out, "JPEG", quality=85)

def _vision(cfg, image, prompt):
    prov = cfg.get("vet_provider", "local")
    if prov == "local":
        url = cfg.get("ollama_url", "http://127.0.0.1:11434").rstrip("/"); model = cfg.get("vet_model", "qwen2.5vl:7b")
        b64 = base64.b64encode(Path(image).read_bytes()).decode()
        r = requests.post(url + "/api/chat", timeout=300, json={"model": model, "stream": False, "keep_alive": "5m",
            "messages": [{"role": "user", "content": prompt, "images": [b64]}], "options": {"temperature": 0.1, "num_predict": 200}})
        if r.status_code != 200: raise RuntimeError(f"Ollama vision error {r.status_code}: {r.text[:200]}")
        return r.json()["message"]["content"]
    from .llm import vision
    c = dict(cfg); c["qa_provider"] = prov
    return vision(c, image, prompt)

def _ensure_vet_model(cfg, log):
    if cfg.get("vet_provider", "local") != "local": return
    url = cfg.get("ollama_url", "http://127.0.0.1:11434").rstrip("/"); model = cfg.get("vet_model", "qwen2.5vl:7b")
    try: tags = requests.get(url + "/api/tags", timeout=5).json()
    except Exception: raise RuntimeError("Clip vetting uses Ollama on this PC, but Ollama isn't running. Start Ollama, then press Resume (or pick another vetting AI in Settings).")
    if not any(m.get("name", "").split(":")[0] == model.split(":")[0] and m.get("name", "").endswith(model.split(":")[-1]) for m in tags.get("models", [])):
        log(f"  downloading the clip-vetting model {model} into Ollama (one time, ~6 GB)...")
        r = requests.post(url + "/api/pull", json={"model": model, "stream": False}, timeout=7200)
        if r.status_code != 200: raise RuntimeError(f"Ollama pull failed: {r.text[:300]}")

def _unload_vet(cfg):
    if cfg.get("vet_provider", "local") != "local": return
    try: requests.post(cfg.get("ollama_url", "http://127.0.0.1:11434").rstrip("/") + "/api/generate",
                       json={"model": cfg.get("vet_model", "qwen2.5vl:7b"), "keep_alive": 0}, timeout=30)
    except Exception: pass

def _score(cfg, cand, vo, sheet, log):
    if cfg.get("vet_provider", "local") == "off": return 6, ""
    try: t = _vision(cfg, sheet, VET.format(vo=vo[:400], query=cand["query"]))
    except Exception as e: log(f"  vetting error ({str(e)[:100]})"); return 5, "unchecked"
    try: j = parse_json(t)
    except Exception: return 5, "unparsed"
    sc = float(j.get("score") or 0)
    if j.get("text") is True or str(j.get("text")).lower() == "true": sc = min(sc, 2)
    return sc, str(j.get("problem") or "")

def do_stock(job, plan, cfg, log, stop):
    d = job / "short" / "stock"; (d / "sheets").mkdir(parents=True, exist_ok=True); (d / "clips").mkdir(exist_ok=True)
    pickf = d / "pick.json"
    pick = json.loads(pickf.read_text(encoding="utf-8")) if pickf.exists() else {}
    key = _pexels_key()
    if not key: raise RuntimeError("No PEXELS_API_KEY in the project .env file (free key from pexels.com/api).")
    _ensure_vet_model(cfg, log)
    used = {c["id"] for v in pick.values() for c in v}
    beats = [s for s in plan["sections"] if not s.get("cta")]
    spare = []
    try:
        for s in beats:
            if s["id"] in pick: continue
            if stop(): raise RuntimeError("cancelled")
            secs = len(s["vo"].split()) / cfg["wpm"] * 60 + GAP
            need = max(2, min(3, math.ceil(secs / 6.0)))
            cands, seen = [], set()
            lists = [_search(key, q, log) for q in s["queries"]]
            for i in range(max(map(len, lists), default=0)):   # interleave queries, best Pexels matches first
                for l in lists:
                    if i < len(l) and l[i]["id"] not in seen and l[i]["id"] not in used: seen.add(l[i]["id"]); cands.append(l[i])
            good, scored = [], []
            for c in cands[:12]:
                if len(good) >= need: break
                sh = d / "sheets" / f"{c['id']}.jpg"
                try:
                    if not sh.exists(): _sheet(c["pics"], sh)
                except Exception as e: log(f"  preview for {c['id']} failed ({e})"); continue
                sc, prob = _score(cfg, c, s["vo"], sh, log); c["score"] = sc; scored.append(c)
                if sc >= 6: good.append(c)
                else: log(f"  {s['id']}: rejected '{c['query']}' clip {c['id']} (score {sc:.0f}{', ' + prob if prob else ''})")
            if len(good) < need:
                extra = [c for c in sorted(scored, key=lambda c: -c["score"]) if c not in good and c["score"] >= 4]
                good += extra[:need - len(good)]
            spare += [c for c in sorted(scored, key=lambda c: -c["score"]) if c not in good and c["score"] >= 6]
            for c in good: used.add(c["id"])
            pick[s["id"]] = [{k: c[k] for k in ("id", "query", "dur", "file", "page", "author", "author_url", "score")} for c in good]
            log(f"  {s['id']}: {len(good)} clip(s) kept out of {len(scored)} checked ({', '.join(s['queries'])})")
            pickf.write_text(json.dumps(pick, indent=1), encoding="utf-8")
    finally:
        _unload_vet(cfg)
    cta = next((s for s in plan["sections"] if s.get("cta")), None)
    if cta and cta["id"] not in pick:
        alt = [c for c in spare if c["id"] not in used][:1]
        pick[cta["id"]] = [{k: c[k] for k in ("id", "query", "dur", "file", "page", "author", "author_url", "score")} for c in alt] or pick[beats[0]["id"]][:1]
    pickf.write_text(json.dumps(pick, indent=1), encoding="utf-8")
    # download + normalise to 1080x1920, 30 fps, no audio, max 10 s
    for b, cs in pick.items():
        for c in cs:
            raw = d / "clips" / f"{c['id']}_raw.mp4"; out = d / "clips" / f"{c['id']}.mp4"
            if media.ok(out): continue
            if not (raw.exists() and raw.stat().st_size > 100000):
                r = requests.get(c["file"], timeout=180, headers={"User-Agent": "Mozilla/5.0"}); r.raise_for_status(); raw.write_bytes(r.content)
            media.ff("-ss", "0.2", "-i", raw, "-t", f"{min(10.0, c['dur'] - 0.4):.2f}", "-an",
                     "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,format=yuv420p",
                     "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", out)
            raw.unlink(missing_ok=True)
    n = sum(len(v) for v in pick.values()); empty = [b for b, v in pick.items() if not v]
    log(f"Stock footage: {n} clips ready" + (f"; no usable clip for {', '.join(empty)} (will reuse others)" if empty else ""))

# ---------------------------------------------------------------- narration + timings
def do_voice(job, plan, cfg, wg, log, stop):
    from . import render, captions
    sd = job / "short"
    render.do_voice(sd, plan, cfg, wg, log, stop)
    tf = sd / "timings.json"
    t = json.loads(tf.read_text(encoding="utf-8")) if tf.exists() else {}
    for s in plan["sections"]:
        if s["id"] in t: continue
        wav = sd / "voice" / f"{s['id']}.wav"
        wt = captions.word_times(wav, s["vo"])
        t[s["id"]] = {"dur": media.dur(wav), "words": [[w, round(a, 3), round(b, 3)] for w, a, b in wt]}
        tf.write_text(json.dumps(t, indent=1), encoding="utf-8")
    total = sum(v["dur"] + GAP for v in t.values()) + TAIL
    log(f"Short narration: {total:.0f}s in total")

# ---------------------------------------------------------------- build + render
def _norm(w): return re.sub(r"[^a-z0-9]", "", str(w).lower())

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
        clips = pick.get(s["id"]) or [pool[(i * 3) % len(pool)]] if pool else []
        bgs = []
        for k, c in enumerate(clips):
            src = sd / "stock" / "clips" / f"{c['id']}.mp4"
            if not src.exists(): continue
            dst = pub / "media" / "stock" / f"{c['id']}.mp4"
            if not dst.exists(): shutil.copy2(src, dst)
            bgs.append({"src": f"media/stock/{c['id']}.mp4", "type": "video", "from": round(k * d / len(clips), 3)})
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
           f"--concurrency={cfg.get('short_concurrency', '75%')}", "--log=info"]
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
    # YouTube description with credits
    pick = json.loads((job / "short" / "stock" / "pick.json").read_text(encoding="utf-8"))
    seen, credits = set(), []
    for cs in pick.values():
        for c in cs:
            if c["id"] in seen: continue
            seen.add(c["id"]); credits.append(f"- {c['author']} ({c['page']})")
    src = meta.get("webpage_url") or ""
    desc = [plan["title"], "", plan.get("description", ""), ""]
    if plan.get("mode") == "both": desc += ["Full breakdown: <PASTE LONG VIDEO LINK HERE>", ""]
    desc += [f"Original: {meta.get('title', '')}" + (f" - {meta.get('channel')}" if meta.get("channel") else "") + (f"\n{src}" if src else ""), "",
             "Stock footage from Pexels (free to use):", *credits, "", "#Shorts"]
    (out_dir / "youtube_short_description.txt").write_text("\n".join(desc), encoding="utf-8")
    log(f"Short finished: {out} ({media.dur(out):.0f}s)")
    return out
