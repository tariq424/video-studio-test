"""Free stock footage for Shorts and long videos: Pexels + Pixabay (+ NASA for space topics).

Flow per slot (a Short beat or a long-video visual):
  1. search  - each source returns candidates with a text description (Pexels page slug, Pixabay tags, NASA title)
  2. rank    - the script AI ranks candidates from those descriptions against what the narration says (cheap, no GPU)
  3. verify  - the local vision model checks only the top-ranked clips for overlaid text/logos, scene cuts,
               darkness/blur and whether it shows what was asked; first clips that pass are used
  4. fetch   - only the needed seconds are cut from the source at high quality and normalised
Keys come from the project .env (PEXELS_API_KEY, PIXABAY_API_KEY); NASA needs none. Keys are never logged."""
import base64, io, json, math, re, time
from pathlib import Path
import requests
from . import config, media
from .llm import LLM, parse_json

SPACE = re.compile(r"\b(space|rocket|nasa|orbit|planet|moon|mars|astronaut|galax|satellite|telescope|spacecraft|spacex|"
                   r"cosmos|universe|nebula|solar system|lunar|iss|starship)", re.I)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) VideoStudio/1.0"}

def _keys():
    out = {}
    env = config.ROOT / ".env"
    if env.exists():
        for l in env.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "=" in l and not l.strip().startswith("#"):
                k, v = l.split("=", 1); out[k.strip()] = v.strip().strip("\"'")
    return out

def _get(url, log, params=None, headers=None, tries=3):
    for attempt in range(tries):
        try:
            r = requests.get(url, params=params, headers={**UA, **(headers or {})}, timeout=40)
        except Exception as e:
            log(f"  search error ({str(e)[:80]})"); time.sleep(3); continue
        if r.status_code == 429:
            wait = int(r.headers.get("Retry-After") or 0) or (60 if attempt == 0 else 300)
            log(f"  rate limit at {url.split('/')[2]}; waiting {wait}s"); time.sleep(wait); continue
        return r
    return None

def _slug_words(u):
    m = re.search(r"/video/([a-z0-9-]+?)-?\d*/?$", u or "")
    return m.group(1).replace("-", " ") if m else ""

# ------------------------------------------------------------------ sources
def pexels(q, orient, log, want_long_side):
    key = _keys().get("PEXELS_API_KEY")
    if not key: return []
    r = _get("https://api.pexels.com/videos/search", log, {"query": q, "orientation": orient, "per_page": 12, "size": "medium"}, {"Authorization": key})
    if not r or r.status_code != 200: log(f"  Pexels '{q}': {'no answer' if not r else 'HTTP ' + str(r.status_code)}"); return []
    out = []
    for v in r.json().get("videos", []):
        fs = [f for f in v.get("video_files", []) if f.get("width") and f.get("height") and f.get("link")]
        fs = [f for f in fs if (f["height"] > f["width"]) == (orient == "portrait") and min(f["width"], f["height"]) >= 1080]
        if not fs or v.get("duration", 0) < 5: continue
        # sharpest file that isn't absurdly large: closest to the wanted long side, preferring bigger
        f = sorted(fs, key=lambda f: (abs(max(f["width"], f["height"]) - want_long_side), -max(f["width"], f["height"])))[0]
        pics = [p["picture"] for p in sorted(v.get("video_pictures", []), key=lambda p: p.get("nr", 0))]
        out.append({"id": f"px{v['id']}", "src": "Pexels", "orient": orient, "query": q, "dur": v["duration"], "w": f["width"], "h": f["height"],
                    "file": f["link"], "page": v.get("url", ""), "author": v.get("user", {}).get("name", ""),
                    "desc": _slug_words(v.get("url", "")) or q, "pics": pics})
    return out

def pixabay(q, orient, log, want_long_side):
    key = _keys().get("PIXABAY_API_KEY")
    if not key: return []
    r = _get("https://pixabay.com/api/videos/", log, {"key": key, "q": q[:100], "per_page": 15, "safesearch": "true", "video_type": "film"})
    if not r or r.status_code != 200: log(f"  Pixabay '{q}': {'no answer' if not r else 'HTTP ' + str(r.status_code)}"); return []
    out = []
    for h in r.json().get("hits", []):
        vs = h.get("videos", {})
        fs = [dict(vs[k], k=k) for k in ("large", "medium", "small") if vs.get(k, {}).get("url") and vs[k].get("width")]
        if orient == "portrait":   # vertical files, or 4K landscape that can be centre-cropped to vertical without upscaling
            fs = [f for f in fs if (f["height"] > f["width"] and f["width"] >= 1080) or (f["width"] > f["height"] and f["height"] >= 1920)]
            fs.sort(key=lambda f: -f["height"])
        else:
            fs = [f for f in fs if f["width"] > f["height"] and f["height"] >= 1080]
            fs.sort(key=lambda f: (abs(f["width"] - want_long_side), -f["width"]))
        if not fs or h.get("duration", 0) < 5: continue
        f = fs[0]
        prev = (vs.get("tiny") or vs.get("small") or {}).get("url") or f["url"]
        out.append({"id": f"pb{h['id']}", "src": "Pixabay", "orient": orient, "query": q, "dur": h["duration"], "w": f["width"], "h": f["height"],
                    "file": f["url"], "page": h.get("pageURL", ""), "author": h.get("user", ""),
                    "desc": h.get("tags", "") or q, "preview": prev})
    return out

def nasa(q, log, limit=6):
    r = _get("https://images-api.nasa.gov/search", log, {"q": q, "media_type": "video", "page_size": 20})
    if not r or r.status_code != 200: return []
    out = []
    for it in r.json().get("collection", {}).get("items", [])[:limit]:
        d = (it.get("data") or [{}])[0]; nid = d.get("nasa_id")
        if not nid: continue
        a = _get(f"https://images-api.nasa.gov/asset/{requests.utils.quote(nid)}", log)
        if not a or a.status_code != 200: continue
        hrefs = [x.get("href", "") for x in a.json().get("collection", {}).get("items", [])]
        mp4 = lambda tag: next((h for h in hrefs if h.lower().endswith(f"~{tag}.mp4")), None)
        f = mp4("large") or mp4("orig") or mp4("medium"); prev = mp4("mobile") or mp4("small") or mp4("preview") or f
        if not f: continue
        out.append({"id": "na" + re.sub(r"[^A-Za-z0-9]", "", nid)[:40], "src": "NASA", "orient": "landscape", "query": q, "dur": 0, "w": 1920, "h": 1080,
                    "file": f.replace("http://", "https://"), "page": f"https://images.nasa.gov/details/{nid}", "author": "NASA",
                    "desc": (d.get("title", "") + ". " + (d.get("description") or "")[:140]).strip(), "preview": prev.replace("http://", "https://")})
    return out

def search_slot(queries, orient, text, log, want_long_side, cache):
    """All candidates for one slot, interleaved across sources and queries. cache: dict persisted by the caller."""
    lists = []
    space = bool(SPACE.search(" ".join(queries) + " " + text))
    for i, q in enumerate(queries):
        for name, fn in (("pexels", lambda q: pexels(q, orient, log, want_long_side)), ("pixabay", lambda q: pixabay(q, orient, log, want_long_side))):
            if name == "pexels" and i > 0 and orient == "landscape": continue   # Pexels allows 200 searches/hour: 1 per long-video visual
            k = f"{name}|{orient}|{q}"
            if k not in cache: cache[k] = fn(q)
            lists.append(cache[k])
        if space and i == 0:
            k = f"nasa|{q}"
            if k not in cache: cache[k] = nasa(q, log)
            lists.append(cache[k])
    out, seen = [], set()
    for i in range(max(map(len, lists), default=0)):
        for l in lists:
            if i < len(l) and l[i]["id"] not in seen: seen.add(l[i]["id"]); out.append(l[i])
    return out

# ------------------------------------------------------------------ ranking (text only, script AI)
RANK = """You are a video editor choosing stock footage. For each slot you get what the narration says (and what the shot should
show), plus candidate clips described by their library title or tags. Rank the candidates that would best support that moment:
literal matches first, then fitting mood or metaphor. Skip clips that would confuse a viewer (unrelated products, people posing
for the camera, tutorials, title cards). Prefer real footage of people, places and things over abstract animation.
Give up to {k} ids per slot, best first; give fewer, or none, if nothing fits.
Reply with ONLY JSON: {{"slot_id": ["id", "id"], ...}}

{slots}"""

def rank(cfg, slots, k, log, stop):
    """slots: [{"id", "text", "cands": [...]}] -> {slot_id: [cand ids best first]}. Batches to keep prompts small."""
    out = {}
    with LLM(cfg, log, stop) as llm:
        for i in range(0, len(slots), 12):
            batch = slots[i:i + 12]
            txt = "\n\n".join(f"SLOT {s['id']}: {s['text'][:500]}\n" + "\n".join(f"  {c['id']}: {c['desc'][:120]}" for c in s["cands"][:24]) for s in batch)
            try: j = llm.chat_json("You are a precise video editor.", RANK.format(k=k, slots=txt), max_tokens=3000)
            except Exception as e: log(f"  ranking failed ({str(e)[:100]}); using library order"); j = {}
            for s in batch:
                ids = {c["id"] for c in s["cands"]}
                r = [x for x in (j.get(s["id"]) or []) if isinstance(x, str) and x in ids]
                out[s["id"]] = r if isinstance(j.get(s["id"]), list) else [c["id"] for c in s["cands"][:k]]
    return out

# ------------------------------------------------------------------ verify (local vision model)
VET = """These are 4 frames, in order, from one short stock video clip.
Answer each question about what you actually see:
1. "shows": does the clip show "{query}"? Answer "yes", "partly" (related scene or similar subject) or "no".
2. "overlay_text": is there large readable text, a caption, title, logo or watermark overlaid on the video, or a clearly
   visible brand name/logo on a product (like an advert)? (Small incidental text in the background does not count.) true or false.
3. "same_scene": do all 4 frames come from the same continuous scene (no hard cut to something unrelated)? true or false.
4. "looks_ok": is it clear, real footage (not blurry, glitchy, distorted or disturbing)? true or false.
Reply with JSON only: {{"shows": "yes|partly|no", "overlay_text": false, "same_scene": true, "looks_ok": true, "seen": "10-20 words: what the clip shows"}}"""

def _frames_from_video(url, out_dir, tag):
    """4 frames from a (small) preview video; returns image paths and duration."""
    p = out_dir / f"{tag}_prev.mp4"
    if not (p.exists() and p.stat().st_size > 10000):
        r = requests.get(url, headers=UA, timeout=120); r.raise_for_status(); p.write_bytes(r.content)
    d = media.dur(p); ims = []
    for i, f in enumerate((0.15, 0.4, 0.65, 0.9)):
        o = out_dir / f"{tag}_{i}.jpg"; media.ff("-ss", f"{d * f:.2f}", "-i", p, "-frames:v", 1, "-vf", "scale=-2:640", o); ims.append(o)
    return ims, d

def sheet(c, out_dir):
    """4-frame contact sheet for a candidate (Pexels: preview pictures; others: frames of the small preview video)."""
    from PIL import Image
    out = out_dir / f"{c['id']}.jpg"
    if out.exists(): return out
    ims = []
    if c.get("pics"):
        idx = [round(i * (len(c["pics"]) - 1) / 3) for i in range(4)]
        for i in idx:
            r = requests.get(c["pics"][i], headers=UA, timeout=30); r.raise_for_status(); ims.append(Image.open(io.BytesIO(r.content)).convert("RGB"))
    else:
        paths, d = _frames_from_video(c["preview"], out_dir, c["id"])
        if not c.get("dur"): c["dur"] = round(d, 1)
        ims = [Image.open(p).convert("RGB") for p in paths]
    for im in ims: im.thumbnail((640, 640))
    w = sum(i.width for i in ims) + 12 * 3; h = max(i.height for i in ims)
    s = Image.new("RGB", (w, h)); x = 0
    for im in ims: s.paste(im, (x, 0)); x += im.width + 12
    s.save(out, "JPEG", quality=88)
    return out

def sharpness(path):
    from PIL import Image, ImageFilter, ImageStat
    im = Image.open(path).convert("L")
    return ImageStat.Stat(im.filter(ImageFilter.FIND_EDGES)).mean[0]

def _vision(cfg, image, prompt):
    prov = cfg.get("vet_provider", "local")
    if prov == "local":
        url = cfg.get("ollama_url", "http://127.0.0.1:11434").rstrip("/")
        b64 = base64.b64encode(Path(image).read_bytes()).decode()
        r = requests.post(url + "/api/chat", timeout=300, json={"model": cfg.get("vet_model", "qwen2.5vl:7b"), "stream": False, "keep_alive": "5m",
            "messages": [{"role": "user", "content": prompt, "images": [b64]}], "options": {"temperature": 0.1, "num_predict": 200}})
        if r.status_code != 200: raise RuntimeError(f"Ollama vision error {r.status_code}: {r.text[:200]}")
        return r.json()["message"]["content"]
    from .llm import vision
    c = dict(cfg); c["qa_provider"] = prov
    return vision(c, image, prompt)

def ensure_vet_model(cfg, log):
    if cfg.get("vet_provider", "local") != "local": return
    url = cfg.get("ollama_url", "http://127.0.0.1:11434").rstrip("/"); model = cfg.get("vet_model", "qwen2.5vl:7b")
    try: tags = requests.get(url + "/api/tags", timeout=5).json()
    except Exception: raise RuntimeError("Clip checking uses Ollama on this PC, but Ollama isn't running. Start Ollama, then press Resume (or pick another vetting AI in Settings).")
    if not any(m.get("name", "") in (model, model + ":latest") for m in tags.get("models", [])):
        log(f"  downloading the clip-checking model {model} into Ollama (one time, ~6 GB)...")
        r = requests.post(url + "/api/pull", json={"model": model, "stream": False}, timeout=7200)
        if r.status_code != 200: raise RuntimeError(f"Ollama pull failed: {r.text[:300]}")

def unload_vet_model(cfg):
    if cfg.get("vet_provider", "local") != "local": return
    try: requests.post(cfg.get("ollama_url", "http://127.0.0.1:11434").rstrip("/") + "/api/generate",
                       json={"model": cfg.get("vet_model", "qwen2.5vl:7b"), "keep_alive": 0}, timeout=30)
    except Exception: pass

def verify(cfg, c, sheet_path, log):
    """-> (ok, reason, seen). Hard checks only; relevance was already judged by the ranking step."""
    from PIL import Image, ImageStat
    if sum(ImageStat.Stat(Image.open(sheet_path).convert("L")).mean) < 28: return False, "too dark", ""
    if sharpness(sheet_path) < 6: return False, "soft/blurry", ""
    if cfg.get("vet_provider", "local") == "off": return True, "", c["desc"]
    try: j = parse_json(_vision(cfg, sheet_path, VET.format(query=c["query"])))
    except Exception as e: log(f"  vision check unavailable ({str(e)[:80]}); accepting {c['id']}"); return True, "", c["desc"]
    yes = lambda k, d: str(j.get(k, d)).strip().lower() in ("true", "yes", "1")
    seen = str(j.get("seen") or c["desc"])[:160]
    if yes("overlay_text", False): return False, "text/logo overlay", seen
    if not yes("same_scene", True): return False, "scene cut", seen
    if not yes("looks_ok", True): return False, "poor footage", seen
    # relevance is judged by the ranking step (which sees the narration); the vision model's literal "shows the search
    # phrase?" answer was too strict in tests (rejected soldiers for "soldiers watching radar"), so it is only recorded
    c["shows"] = str(j.get("shows", "")).strip().lower()
    return True, "", seen

# ------------------------------------------------------------------ fetch
def fetch(c, out, max_secs):
    """Cut up to max_secs straight from the source URL (no full download) and normalise:
    portrait -> 1080x1920 (cropped), landscape -> 1920x1080 (cropped). Near-lossless so the final render is the only real compression."""
    if media.ok(out): return out
    dur = float(c.get("dur") or 0)
    start = 0.3 if dur < 20 else min(dur * 0.15, 20.0)
    length = max(3.0, min(max_secs, (dur - start - 0.3) if dur else max_secs))
    W, H = (1080, 1920) if c.get("orient", "portrait") == "portrait" else (1920, 1080)
    for attempt in range(2):
        try:
            media.ff("-user_agent", UA["User-Agent"], "-ss", f"{start:.2f}", "-i", c["file"], "-t", f"{length:.2f}", "-an",
                     "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},fps=30,format=yuv420p",
                     "-c:v", "libx264", "-preset", "veryfast", "-crf", "12", out, timeout=600)   # light on CPU so it can run beside narration
            if media.ok(out): return out
        except Exception as e:
            if attempt: raise RuntimeError(f"download of {c['id']} failed: {str(e)[:200]}")
    raise RuntimeError(f"download of {c['id']} produced no video")

# ------------------------------------------------------------------ one call for a list of slots
def fill(cfg, slots, orient, need, out_dir, log, stop, want_long_side, max_secs, state_file, fallback=False):
    """slots: [{"id","text","queries"}]; need: {slot_id: n}. Returns {slot_id: [chosen candidate dicts]} (may be short).
    Progress is saved to state_file so a resumed job doesn't redo work."""
    out_dir.mkdir(parents=True, exist_ok=True); (out_dir / "sheets").mkdir(exist_ok=True)
    st = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {"cache": {}, "ranked": {}, "picked": {}}
    save = lambda: state_file.write_text(json.dumps(st, indent=1), encoding="utf-8")
    todo = [s for s in slots if s["id"] not in st["picked"]]
    if not todo: return st["picked"]
    log(f"Stock footage: searching for {len(todo)} slot(s) ({'Pexels, Pixabay' + (', NASA' if any(SPACE.search(s['text']) for s in todo) else '')})...")
    cands = {}
    for s in todo:
        if stop(): raise RuntimeError("cancelled")
        cands[s["id"]] = search_slot(s["queries"], orient, s["text"], log, want_long_side, st["cache"])
    save()
    unranked = [s for s in todo if s["id"] not in st["ranked"]]
    if unranked:
        log(f"  ranking candidates by meaning...")
        st["ranked"].update(rank(cfg, [{"id": s["id"], "text": s["text"], "cands": cands[s["id"]]} for s in unranked], 5, log, stop)); save()
    used = {c["id"] for v in st["picked"].values() for c in v}
    ensure_vet_model(cfg, log)
    try:
        for s in todo:
            if stop(): raise RuntimeError("cancelled")
            byid = {c["id"]: c for c in cands[s["id"]]}; got = []
            order = list(st["ranked"].get(s["id"], []))
            if fallback: order += [c["id"] for c in cands[s["id"]][:6] if c["id"] not in order]   # Shorts: never leave a beat empty
            for cid in order:
                if len(got) >= need[s["id"]]: break
                c = byid.get(cid)
                if not c or cid in used: continue
                try: sh = sheet(c, out_dir / "sheets")
                except Exception as e: log(f"  preview of {cid} failed ({str(e)[:60]})"); continue
                ok, why, seen = verify(cfg, c, sh, log)
                if not ok: log(f"  {s['id']}: skipped {c['src']} clip {cid} ({why})"); continue
                c["seen"] = seen; got.append({k: c.get(k) for k in ("id", "src", "orient", "query", "dur", "w", "h", "file", "page", "author", "desc", "seen")}); used.add(cid)
            st["picked"][s["id"]] = got; save()
            log(f"  {s['id']}: {len(got)}/{need[s['id']]} clip(s): " + "; ".join(f"{g['src']}: {g['seen'][:45]}" for g in got) if got else f"  {s['id']}: nothing suitable")
    finally:
        unload_vet_model(cfg)
    # download (only the seconds we need)
    (out_dir / "clips").mkdir(exist_ok=True)
    for v in st["picked"].values():
        for c in v:
            if stop(): raise RuntimeError("cancelled")
            fetch(c, out_dir / "clips" / f"{c['id']}.mp4", max_secs)
    return st["picked"]

# ------------------------------------------------------------------ long videos: stock B-roll instead of GPU stills/motion
QUERIES = """For each shot below (an image prompt written for an AI generator, plus the narration it illustrates), write 2 stock-video
search phrases (3-5 words each) that would find REAL footage showing the same thing: subject + action + setting, people doing
things where possible. No abstract words ("AI", "future", "concept", "technology"), no brand names, no famous people.
Reply with ONLY JSON: {{"shot_id": ["phrase", "phrase"], ...}}

{shots}"""

def long_broll(job, plan, cfg, log, stop):
    """Give every AI still/motion visual a stock clip where a good one exists (v['stock'] = clip path); the rest stay AI-rendered."""
    vis = [(s, v) for s in plan["sections"] for v in s["visuals"] if v["type"] in ("still", "motion") and not v.get("stock") and not v.get("no_stock")]
    if not vis: log("B-roll: nothing to do"); return
    d = job / "broll"; d.mkdir(exist_ok=True)
    qf = d / "queries.json"; qs = json.loads(qf.read_text(encoding="utf-8")) if qf.exists() else {}
    todo = [(s, v) for s, v in vis if v["id"] not in qs]
    if todo:
        with LLM(cfg, log, stop) as llm:
            for i in range(0, len(todo), 15):
                batch = todo[i:i + 15]
                txt = "\n".join(f"SHOT {v['id']}: image prompt: {v['prompt'][:300]} | narration: {s['vo'][:300]}" for s, v in batch)
                try: j = llm.chat_json("You are a precise video researcher.", QUERIES.format(shots=txt), max_tokens=2500)
                except Exception as e: log(f"  search phrases failed ({str(e)[:80]})"); j = {}
                for s, v in batch:
                    q = [x for x in (j.get(v["id"]) or []) if isinstance(x, str)][:2]
                    qs[v["id"]] = q or [" ".join(v["prompt"].split()[:5])]
        qf.write_text(json.dumps(qs, indent=1), encoding="utf-8")
    slots = [{"id": v["id"], "text": f"Shot: {v['prompt'][:300]} Narration: {s['vo'][:250]}", "queries": qs[v["id"]]} for s, v in vis]
    picked = fill(cfg, slots, "landscape", {v["id"]: 1 for _, v in vis}, d, log, stop, want_long_side=1920, max_secs=12.0, state_file=d / "footage.json")
    n = 0
    for s, v in vis:
        c = (picked.get(v["id"]) or [None])[0]
        if c and media.ok(d / "clips" / f"{c['id']}.mp4"):
            v["stock"] = str((d / "clips" / f"{c['id']}.mp4").relative_to(job)).replace("\\", "/"); v["stock_src"] = c["src"]; n += 1
    log(f"B-roll: {n} of {len(vis)} AI visuals replaced with real footage; {len(vis) - n} will be AI-rendered")
