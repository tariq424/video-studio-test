"""Free stock footage for Shorts and long videos: Pexels + Pixabay (+ NASA for space topics).

Flow per slot (a Short beat or a long-video visual):
  1. search  - each source returns candidates with a text description (Pexels page slug, Pixabay tags, NASA title)
  2. rank    - the script AI ranks candidates from those descriptions against what the narration says (cheap, no GPU)
  3. verify  - the local vision model checks only the top-ranked clips for overlaid text/logos, scene cuts,
               darkness/blur and whether it shows what was asked; first clips that pass are used
  4. fetch   - only the needed seconds are cut from the source at high quality and normalised
Keys come from the project .env (PEXELS_API_KEY, PIXABAY_API_KEY); NASA needs none. Keys are never logged."""
import base64, io, json, math, re, time, subprocess
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
        if i == 0 and orient != "portrait":   # Internet Archive: public-domain films (Prelinger first), one query per slot; long videos only
                                              # (archive films are SD: a 9:16 crop of one is too soft for a Short)
            k = f"archive|{orient}|{q}"
            if k not in cache:
                from . import archive
                cache[k] = archive.videos(q, orient, log, want_long_side)
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
Coherence rules:
- Never pick a clip whose description names a specific brand, airline, car make, company or product that is not the slot's subject
  (e.g. a "turkish airlines plane" for a story about flydubai).
- If a slot has SUBJECT: <name>, rank clips whose description names that subject first, then clips that could plausibly show it
  (they will be checked visually against a reference photo); never clips that clearly show something else of the same kind
  (another airline, another car model).
- When the narration names a specific person, avoid close-ups of one person (viewers would think it is them); crowds, places,
  hands and objects are fine.
Give up to {k} ids per slot, best first; give fewer, or none, if nothing fits.
Reply with ONLY JSON: {{"slot_id": ["id", "id"], ...}}

{slots}"""

def rank(cfg, slots, k, log, stop):
    """slots: [{"id", "text", "cands": [...]}] -> {slot_id: [cand ids best first]}. Batches to keep prompts small."""
    out = {}
    with LLM(cfg, log, stop) as llm:
        for i in range(0, len(slots), 12):
            batch = slots[i:i + 12]
            txt = "\n\n".join(f"SLOT {s['id']}: {s['text'][:500]}" + (f"\nSUBJECT: {s['subject']['name']}" if s.get("subject") else "") + "\n" + "\n".join(f"  {c['id']}: {c['desc'][:120]}" for c in s["cands"][:24]) for s in batch)
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
5. "brands": every brand you can read or clearly recognise in the frames: airline names or tail logos (also on seats, headrests
   or uniforms), car makes or badges, clothing logos (e.g. Adidas), company or product logos. Empty list if none.
6. "fits": the narration playing over this clip is: "{narration}"
   Would a viewer find the clip a sensible illustration of that narration? Answer "no" if it shows a recognisable place,
   building or landmark that is not the one the narration is about (e.g. a famous parliament of another country), an unrelated
   event, or a mood that contradicts it (calm, routine, happy scenes while the narration describes an emergency, violence, fear
   or a crisis). Also answer "no" if the clip's main subject is one person who would be taken to BE someone the narration names
   (a particular country's officials, agents, spokesperson, pilot or politician): a stranger must not stand in for a real
   person or a real agency's staff. Places, documents, maps, screens and crowds are fine. "yes" or "partly" otherwise.
7. "platform": is any frame a screen capture of other media - a YouTube or social-media page or player, a video thumbnail,
   a TV broadcast with a channel logo or news ticker, a streaming-app interface, a film/TV still, or another channel's
   watermark? (A generic computer screen in the background does not count.) true or false.
Reply with JSON only: {{"shows": "yes|partly|no", "overlay_text": false, "same_scene": true, "looks_ok": true, "brands": [], "fits": "yes|partly|no", "platform": false, "seen": "10-20 words: what the clip shows"}}"""

STRICT = """The LEFT image is a reference photo of: {subject}.
The RIGHT image shows 4 frames from a stock video clip.
Answer about the RIGHT frames only:
1. "brands": every brand you can read or clearly recognise: airline names or tail logos, car makes or badges, company or product
   logos. Empty list if none.
2. "same_subject": does the clip show {subject} itself - the same airline livery / the same make and model / the same product as
   the reference (not just something of the same kind)? "yes", "no" or "unclear".
3. "overlay_text": large text, captions or watermarks overlaid on the video? true or false.
4. "same_scene": all 4 frames from one continuous scene? true or false.
5. "looks_ok": clear, real footage (not blurry, glitchy or distorted)? true or false.
6. "platform": a screen capture of other media (YouTube / social page or player, video thumbnail, TV broadcast with a channel logo
   or ticker, streaming-app interface, film/TV still, another channel's watermark)? true or false.
Reply with JSON only: {{"brands": [], "same_subject": "yes|no|unclear", "overlay_text": false, "same_scene": true, "looks_ok": true, "platform": false, "seen": "10-20 words: what the clip shows"}}"""

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
    for k, im in enumerate(ims): im.thumbnail((640, 640)); im.save(out_dir / f"{c['id']}_f{k}.jpg", "JPEG", quality=90)   # make check
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

def _norm_brand(x): return re.sub(r"[^a-z0-9]", "", str(x).lower())

def _brands(j):
    b = j.get("brands") or []
    if isinstance(b, str): b = [b]
    return [str(x).strip() for x in b if str(x).strip() and _norm_brand(x) not in ("none", "no", "unknown", "na", "")]

AVOID = """
6. "forbidden": does any frame show {avoid}? Even partly, even small or in the background. true or false.
Add "forbidden" to the JSON."""

# ------------------------------------------------------------------ story subject guard (owner's rule, 2026-10-23)
# A story about Tesla must not show a Honda steering wheel, a BMW, a Kia or a classic Triumph: every clip in which a vehicle /
# aircraft / product is a main subject must be that story's make, recognised from a closer look at two full frames. Unknown
# makes are dropped too (a stock clip is never shoehorned in). Interiors must drive on the side the story's country does.
MAKE = """Look closely at this picture (two frames from one video clip side by side).
First describe in one sentence what is in it, naming any car, vehicle, aircraft or product you see and any badge or logo on it.
Then answer:
- object: is {what} clearly visible as a main subject (not tiny in the far background)? Answer true or false.
- make: the {who} of it, read from a badge or logo (steering-wheel hub, grille, bonnet, boot, wheels, tail) or recognised from an
  unmistakable design. Write "unknown" if you cannot tell for sure, "none" if object is false.
- drive_side: if a car's interior with its steering wheel is shown, is the wheel on the "left" or the "right" side? Otherwise "none".
Reply with one JSON object with the keys seen, object, make, drive_side, filled in from what you actually see."""
KIND_WORDS = {"vehicle": ("a car, truck, motorbike or other road vehicle, or a car's interior (steering wheel, dashboard, seats)", "make (brand)"),
              "aircraft": ("an aircraft, or an aircraft's cabin, wing or tail", "airline or maker"),
              "train": ("a train", "operator or maker"), "ship": ("a ship or boat", "operator or maker"),
              "product": ("a phone, computer, gadget or similar product", "brand")}
RHD = ("united kingdom", "britain", "british", "england", "scotland", "wales", "ireland", "japan", "india", "australia", "new zealand",
       "south africa", "singapore", "malaysia", "indonesia", "thailand", "hong kong", "pakistan", "bangladesh", "sri lanka", "kenya", "uk")
LHD = ("china", "chinese", "united states", "america", "american", "u.s.", "usa", "canada", "mexico", "germany", "german", "france",
       "french", "italy", "spain", "korea", "brazil", "russia", "europe", "european", "taiwan", "vietnam", "turkey", "saudi", "uae", "dubai")


def story_guard(job_dir, text):
    """-> {"kinds": {kind: [brands]}, "side": "left"|"right"|""} from the job's story subjects (entities.json) and its text."""
    ents = []
    for d in [Path(job_dir)] + list(Path(job_dir).parents)[:3]:
        f = d / "entities.json"
        if f.exists():
            try: ents = json.loads(f.read_text(encoding="utf-8")); break
            except Exception: pass
    kinds = {}
    for e in ents:
        if e.get("kind") in KIND_WORDS and (e.get("brand") or "").strip():
            kinds.setdefault(e["kind"], []).append(e["brand"].strip())
    return {"kinds": kinds, "side": drive_side(text)}


def drive_side(text):
    t = " " + re.sub(r"[^a-z. ]+", " ", (text or "").lower()) + " "
    r = any(f" {w} " in t for w in RHD); l = any(f" {w} " in t for w in LHD)
    return "right" if r and not l else "left" if l and not r else ""


def make_check(cfg, c, sheet_path, guard, narration, log):
    """-> (ok, reason). Only when the story has a branded vehicle/aircraft/product subject (or a known driving side)."""
    if not guard or not (guard.get("kinds") or guard.get("side")) or not cfg.get("story_subject_guard", True): return True, ""
    from PIL import Image
    fr = [sheet_path.with_name(f"{c['id']}_f{k}.jpg") for k in (1, 2)]
    if not all(f.exists() for f in fr): return True, ""
    ims = [Image.open(f).convert("RGB") for f in fr]
    pair = Image.new("RGB", (sum(i.width for i in ims) + 12, max(i.height for i in ims))); x = 0
    for im in ims: pair.paste(im, (x, 0)); x += im.width + 12
    pp = sheet_path.with_name(f"{c['id']}_pair.jpg"); pair.save(pp, "JPEG", quality=90)
    side = drive_side(narration) or guard.get("side", "")
    if cfg.get("vet_provider", "local") in ("off", "", None): cfg = dict(cfg, vet_provider="local")   # the guard always looks (local model)
    for kind, brands in (guard.get("kinds") or {"vehicle": []}).items():
        what, who = KIND_WORDS[kind]
        try: j = parse_json(_vision(cfg, pp, MAKE.format(what=what, who=who)))
        except Exception as e: return False, f"make check unavailable ({str(e)[:50]}); not risking a wrong {kind}"
        obj = str(j.get("object", "false")).strip().lower()   # the model answers true/false, or names the object ("car")
        make = str(j.get("make") or "unknown").strip()
        if obj in ("false", "no", "none", "0", "") and make.lower() in ("none", "", "unknown"): continue
        if brands:
            hit = any(_norm_brand(b) and (_norm_brand(b) in _norm_brand(make) or _norm_brand(make) in _norm_brand(b)) for b in brands) and _norm_brand(make)
            if not hit:
                return False, (f"shows a {make} {kind}; the story is about {', '.join(brands)}" if make.lower() not in ("unknown", "none", "")
                               else f"shows a {kind} that can't be confirmed as {', '.join(brands)}")
        ds = str(j.get("drive_side") or "none").lower()
        if kind == "vehicle" and side and ds in ("left", "right") and ds != side:
            return False, f"{'right' if ds == 'right' else 'left'}-hand-drive interior; the story's country drives with the wheel on the {side}"
    return True, ""


# ------------------------------------------------------------------ clip check v2 (owner, 2026-10-23): "does it contradict?"
# The old question ("would a viewer find it a sensible illustration?") threw out good clips and let wrong ones through.
# Now: describe what is actually there, then reject only for a contradiction:
#  - the beat's main subject must be visible (a "beachfront property" beat needs buildings, not empty cliffs);
#  - a general subject must be the same KIND (no pickup truck for "a car", no dog for "a cat", no ballpoint for "a fountain pen");
#  - a specific subject must be the same LOOK (make/model/livery: the reference-photo check + the make check);
#  - a recognisable place must be the story's place (no London skyline in a Cyprus story; the closing card shows no place at all);
#  - mood, stand-in people, overlays, screen captures and cuts as before.
MAINS = """For each numbered narration line of a news video, name the physical thing a stock video clip for it must SHOW.
"main": a filmable, physical thing the line is literally about, 2-6 words, no brand names ("beachfront apartment buildings",
        "a fountain pen", "an electric car", "a cat", "a container ship"). Write "" when the line is about something stock
        footage can't film: a company, a brand, an app, a chatbot, a logo, a chart, a report, money, a deal, a policy, numbers,
        an opinion or a summary.
"kind": the general kind of that thing in 1-3 words ("buildings", "car", "pen", "cat", "ship"), "" when main is "".
"place": the country / city / region the line is set in, if the story says so ("Cyprus", "Shanghai"), else "".
Story so far: {story}
Lines:
{lines}
Reply with JSON only: {{"<line id>": {{"main": "...", "kind": "...", "place": "..."}}, ...}}"""

CONTRA = """These are 4 frames, in order, from one short stock video clip.
First write "seen": one sentence describing what is actually in the frames (things, people, setting, any city, skyline or landmark).
Then answer from what you see:
- "main_visible": the narration is about {main}. Is a {kind} itself clearly in the shot? Details such as the exact location, the view
  or the colour don't matter (a modern apartment block counts for "beachfront property"); only its surroundings without the thing
  (empty sea, cliffs, sky) do not count. "yes", "no" or "unclear".
- "kind_shown": the kind of {kind} the clip shows, in 1-3 words (e.g. "pickup truck", "sedan", "dog", "ballpoint pen"); "none" if no {kind} is shown.
- "place_seen": a recognisable city, skyline, landmark or country you can identify (e.g. "London skyline", "Eiffel Tower"); "none" if you can't name one.
- "mood_clash": true if the scene's mood plainly contradicts this narration (calm or happy scenes over a disaster, crime or crisis): "{narration}"
- "unrelated": true if the clip has nothing to do with the narration's topic at all (a washing machine, a spinning coin or wax
  seals for a story about an AI company). Loosely related scenes (offices, screens, money, a city for a business story) are false.
- "stand_in": true if the main subject is one person who would be taken to BE someone the narration names (an official, pilot, politician).
- "overlay_text": large readable text, caption, title, logo or watermark overlaid on the video, or an advert-style brand logo? true/false.
- "same_scene": all 4 frames from one continuous scene? true/false.
- "looks_ok": clear, real footage (not blurry, glitchy, distorted or disturbing)? true/false.
- "platform": a screen capture of other media (YouTube/social page or player, thumbnail, TV broadcast with channel logo or ticker,
  streaming-app interface, film/TV still, another channel's watermark)? true/false.
- "brands": every brand you can read or clearly recognise (car badges, airline logos, product logos); [] if none.
Reply with one JSON object with the keys seen, main_visible, kind_shown, place_seen, mood_clash, unrelated, stand_in, overlay_text, same_scene,
looks_ok, platform, brands, filled in from what you actually see."""

_PLACE_CACHE = {}


def beat_mains(cfg, slots, log, cache_file=None):
    """-> {slot_id: {"main", "kind", "place"}} for the slots (DeepSeek, one call per 20 lines; cached in cache_file)."""
    have = {}
    if cache_file and Path(cache_file).exists():
        try: have = json.loads(Path(cache_file).read_text(encoding="utf-8"))
        except Exception: have = {}
    todo = [s for s in slots if s["id"] not in have and not s.get("cta")]
    if todo:
        story = " ".join(str(s.get("narration") or s.get("text") or "") for s in slots)[:1500].replace('"', "'")
        try:
            with LLM(cfg, log, lambda: False) as llm:
                for i in range(0, len(todo), 20):
                    b = todo[i:i + 20]
                    lines = "\n".join(f"{s['id']}: {str(s.get('narration') or s.get('text') or '')[:300]}" for s in b)
                    j = llm.chat_json("You are a precise video editor. Reply with JSON only.", MAINS.format(story=story, lines=lines), max_tokens=2000)
                    for s in b:
                        v = j.get(s["id"]) if isinstance(j.get(s["id"]), dict) else {}
                        have[s["id"]] = {k: str(v.get(k) or "").strip()[:60] for k in ("main", "kind", "place")}
        except Exception as e:
            log(f"  clip check: couldn't name the beats' main subjects ({str(e)[:100]}); checking contradictions only")
        if cache_file:
            try: Path(cache_file).write_text(json.dumps(have, indent=1), encoding="utf-8")
            except Exception: pass
    return have


def _none(x): return str(x or "").strip().lower() in ("", "none", "no", "n/a", "na", "unknown", "null", "false", "nothing")


def place_ok(cfg, seen, story_place, log=print):
    """Is the recognised place `seen` consistent with the story's place? (no place in the story -> any real place is fine,
    except on the closing card). Cached; asks the script AI only when the names don't already match."""
    if _none(seen): return True
    if not story_place: return True
    if not re.search(r"\b[A-Z][a-z]", seen): return True   # "suburban neighborhood", "a city": not a place anyone can name
    a, b = _subject_words([seen]), _subject_words([story_place])
    if a & b: return True
    key = (seen.lower(), story_place.lower())
    if key not in _PLACE_CACHE:
        try:
            with LLM(cfg, log, lambda: False) as llm:
                j = llm.chat_json("Answer with JSON only.", f'Is "{seen}" located in, or a well-known part of, "{story_place}"? '
                                  'Reply {"inside": true} or {"inside": false}.', max_tokens=50)
            _PLACE_CACHE[key] = str(j.get("inside")).strip().lower() in ("true", "yes", "1")
        except Exception:
            _PLACE_CACHE[key] = True   # can't tell: not a contradiction we can prove
    return _PLACE_CACHE[key]


_KIND_SYN = {"car": {"car", "sedan", "saloon", "hatchback", "suv", "coupe", "convertible", "electric car", "ev", "estate", "wagon", "crossover", "taxi", "vehicle"},
             "pen": {"pen", "fountain pen"}, "cat": {"cat", "kitten"}, "dog": {"dog", "puppy"},
             "buildings": {"property", "properties", "building", "buildings", "apartment", "apartments", "house", "houses", "villa", "villas", "hotel", "tower", "towers", "property", "homes", "home", "skyline"}}


def _syn(k):
    """The words that count as the same kind as k (its own group in _KIND_SYN, found by key or member)."""
    k = k.lower().strip(); base = k.rstrip("s")
    for key, group in _KIND_SYN.items():
        if k == key or base == key or k in group or base in group: return group | {k, base}
    return {k, base}


def kind_match(kind, shown):
    """The clip shows something of the beat's kind (sedan for car, apartment block for buildings)."""
    if _none(kind) or _none(shown): return False
    k = kind.lower().strip(); syn = _syn(k)
    words = set(re.findall(r"[a-z]+", shown.lower()))
    return bool(words & syn or any(w.rstrip("s") in syn for w in words))


def kind_clash(kind, shown, main=""):
    """True when the clip shows another kind of thing than the beat's (a pickup truck for "a car", a dog for "a cat",
    a ballpoint for "a fountain pen")."""
    if _none(kind) or _none(shown): return False
    k, sh, m = kind.lower().strip(), shown.lower().strip(), (main or "").lower()
    if "fountain pen" in m and "fountain" not in sh: return "pen" in sh or "ballpoint" in sh or "marker" in sh
    if re.search(r"\b(pickup|pick-up|truck|lorry|van|bus|tractor|motorbike|motorcycle|scooter|bicycle)\b", sh) and k in ("car", "cars", "electric car", "vehicle") \
            and not re.search(r"\b(truck|pickup|van|bus|motorbike|motorcycle)\b", m):
        return True
    syn = _syn(k)
    words = set(re.findall(r"[a-z]+", sh)) | {sh}
    if words & syn or any(w.rstrip("s") in syn for w in words): return False
    animals = {"cat", "dog", "horse", "bird", "cow", "sheep", "goat", "fish", "rabbit", "mouse"}
    if k.rstrip("s") in animals and words & animals: return True   # one animal shown for another
    return False   # different wording, not a proven contradiction


RELATE = """A news video's narration line and a description of a stock clip that would play over it.
What the whole video is about: "{story}"
Narration line: "{narration}"
Clip shows: "{seen}"
Is the clip clearly UNRELATED to the line and to the video's story (a washing machine, a spinning coin or wax seals over a line about an AI
company's funding)? Loosely related scenes are fine (offices, screens, money, documents, a city skyline for a business story;
people at work for a company story). Reply with JSON only: {{"unrelated": true or false, "why": "a few words"}}"""
_RELATE_CACHE = {}


def text_unrelated(cfg, narration, seen, log=print, story=""):
    """The script AI (stronger at meaning than the small vision model) judges the vision model's description against the
    narration. -> reason string when clearly unrelated, else "". Can't tell -> "" (not a proven contradiction)."""
    if not cfg.get("clip_relate_check", True) or not seen or not narration: return ""
    key = (narration[:200], seen[:200])
    if key not in _RELATE_CACHE:
        try:
            with LLM(cfg, log, lambda: False) as llm:
                j = llm.chat_json("You are a precise video editor. Reply with JSON only.",
                                  RELATE.format(story=(story or narration)[:400].replace('"', "'"), narration=narration[:400].replace('"', "'"),
                                                seen=seen[:300].replace('"', "'")), max_tokens=80)
            _RELATE_CACHE[key] = (str(j.get("why") or "unrelated")[:60]) if str(j.get("unrelated")).strip().lower() in ("true", "yes", "1") else ""
        except Exception:
            _RELATE_CACHE[key] = ""
    return _RELATE_CACHE[key]


def literal(main, kind, narration):
    """The beat's main subject only binds when the line actually names it ("beachfront property" for a line about property
    transfers, not "a bank vault" the script AI imagined for a line about money)."""
    if not narration: return True
    have = {_stem(w) for w in re.findall(r"[a-z0-9]+", narration.lower())}
    want = {_stem(w) for w in _syn(kind) for w in re.findall(r"[a-z0-9]+", w)} if kind else set()
    want |= {_stem(w) for w in re.findall(r"[a-z0-9]+", (main or "").lower()) if len(w) > 3 and w not in GENERIC}
    return bool(have & want)


def contra_verdict(cfg, j, mainv, narration_place="", neutral=False, log=print, narration="", story=""):
    """-> (ok, reason) from the CONTRA answers."""
    yes = lambda k, d=False: str(j.get(k, d)).strip().lower() in ("true", "yes", "1")
    if yes("platform"): return False, "copyright: screen capture / thumbnail / channel watermark"
    if yes("overlay_text"): return False, "text/logo overlay"
    if not yes("same_scene", True): return False, "scene cut"
    if not yes("looks_ok", True): return False, "poor footage"
    main, kind, place = (mainv or {}).get("main", ""), (mainv or {}).get("kind", ""), (mainv or {}).get("place", "") or narration_place
    seen_place = str(j.get("place_seen") or "none").strip()
    if neutral and not _none(seen_place): return False, f"shows a recognisable place ({seen_place[:40]}); the closing card stays neutral"
    if not place_ok(cfg, seen_place, place, log): return False, f"shows {seen_place[:40]}; the story is set in {place}"
    if main and literal(main, kind, narration) and str(j.get("main_visible", "unclear")).strip().lower() == "no" and not kind_match(kind, str(j.get("kind_shown") or "")):
        return False, f"doesn't show {main}"
    if kind_clash(kind, str(j.get("kind_shown") or ""), main): return False, f"shows a {str(j.get('kind_shown'))[:30]}, not {main or kind}"
    if yes("mood_clash"): return False, "the mood contradicts the narration"
    if yes("unrelated"): return False, "nothing to do with what the narration says"
    if yes("stand_in"): return False, "a stranger would be taken for a real person the narration names"
    if not neutral:
        why = text_unrelated(cfg, narration, str(j.get("seen") or ""), log, story)
        if why: return False, f"unrelated to the narration ({why})"
    return True, ""


def verify(cfg, c, sheet_path, log, subject=None, ref=None, avoid=None, narration="", guard=None, mainv=None, place="", neutral=False, story=""):
    """-> (ok, reason, seen). Generic slots: hard checks + no visible third-party brand.
    Subject-locked slots: the clip must positively match the subject (brand evidence and the vision model agreeing with a reference photo)."""
    from PIL import Image, ImageStat
    if sum(ImageStat.Stat(Image.open(sheet_path).convert("L")).mean) < 28: return False, "too dark", ""
    if sharpness(sheet_path) < 6: return False, "soft/blurry", ""
    if cfg.get("vet_provider", "local") == "off":
        return (not subject), ("subject can't be confirmed with vetting off" if subject else ""), c["desc"]
    img = sheet_path
    if subject and ref:
        img = side_by_side(ref, sheet_path, sheet_path.with_name(sheet_path.stem + "_vs.jpg"))
    v2 = cfg.get("clip_check_v2", True) and not subject
    mv = mainv or {}
    if v2:
        prompt = CONTRA.format(main=mv.get("main") or "the thing the narration is about", kind=mv.get("kind") or "thing",
                               narration=(narration or c["query"])[:300].replace('"', "'"))
    else:
        prompt = STRICT.format(subject=subject["name"]) if (subject and ref) else VET.format(query=subject["name"] if subject else c["query"], narration=(narration or c["query"])[:400].replace('"', "'"))
    if avoid and not subject: prompt += AVOID.format(avoid="; or ".join(avoid)[:500])
    try: j = parse_json(_vision(cfg, img, prompt))
    except Exception as e:
        if subject: return False, f"vision check unavailable ({str(e)[:60]}); subject can't be confirmed", c["desc"]
        log(f"  vision check unavailable ({str(e)[:80]}); accepting {c['id']}"); return True, "", c["desc"]
    yes = lambda k, d: str(j.get(k, d)).strip().lower() in ("true", "yes", "1")
    seen = str(j.get("seen") or c["desc"])[:160]
    if v2:
        ok, why = contra_verdict(cfg, j, mv, place, neutral, log, narration=narration or c.get("query", ""), story=story)
        if not ok: return False, why, seen
        story_brands = [b for v in ((guard or {}).get("kinds") or {}).values() for b in v]
        other = [b for b in _brands(j) if not any(_norm_brand(sb) and (_norm_brand(sb) in _norm_brand(b) or _norm_brand(b) in _norm_brand(sb)) for sb in story_brands)]
        if other: return False, f"shows another brand ({', '.join(other)[:60]})", seen
        if avoid and yes("forbidden", False): return False, "shows something the story is about, but not the right one", seen
        ok2, why2 = make_check(cfg, c, sheet_path, guard, narration, log)
        if not ok2: return False, why2, seen
        c["shows"] = str(j.get("main_visible", "")).strip().lower()
        return True, "", seen
    if yes("platform", False): return False, "copyright: screen capture / thumbnail / channel watermark", seen
    if yes("overlay_text", False): return False, "text/logo overlay", seen
    if not yes("same_scene", True): return False, "scene cut", seen
    if not yes("looks_ok", True): return False, "poor footage", seen
    brands = _brands(j); key = _norm_brand((subject or {}).get("brand", ""))
    other = [b for b in brands if not (key and (key in _norm_brand(b) or _norm_brand(b) in key))]
    if other: return False, f"shows another brand ({', '.join(other)[:60]})", seen
    if avoid and not subject and yes("forbidden", False): return False, "shows something the story is about, but not the right one", seen
    if not subject and str(j.get("fits", "yes")).strip().lower() == "no": return False, "doesn't fit what the narration says", seen
    if subject:
        evidence = bool(key) and (any(key in _norm_brand(b) for b in brands) or key in _norm_brand(c.get("desc", "")))
        same = str(j.get("same_subject", j.get("shows", ""))).strip().lower()
        if same == "no": return False, f"not {subject['name']}", seen
        if key and not evidence: return False, f"no visible sign of {subject.get('brand')}", seen
        if not key and same != "yes": return False, f"not confirmed as {subject['name']}", seen
    ok2, why2 = make_check(cfg, c, sheet_path, guard, narration, log)   # a closer look: the story's make, never a lookalike
    if not ok2: return False, why2, seen
    c["shows"] = str(j.get("shows", j.get("same_subject", ""))).strip().lower()
    return True, "", seen

def side_by_side(ref, sheet_path, out):
    """Reference photo (left) next to the clip's 4-frame sheet (right), one image for the vision model."""
    from PIL import Image, ImageDraw
    if out.exists(): return out
    a = Image.open(ref).convert("RGB"); b = Image.open(sheet_path).convert("RGB")
    h = 480; a = a.resize((max(1, int(a.width * h / a.height)), h)); b = b.resize((max(1, int(b.width * h / b.height)), h))
    im = Image.new("RGB", (a.width + b.width + 40, h + 40), (20, 20, 20)); d = ImageDraw.Draw(im)
    im.paste(a, (0, 40)); im.paste(b, (a.width + 40, 40))
    d.text((8, 10), "LEFT: reference photo", fill=(255, 220, 0)); d.text((a.width + 48, 10), "RIGHT: stock clip frames", fill=(255, 220, 0))
    im.save(out, "JPEG", quality=88)
    return out

# ------------------------------------------------------------------ reference photos (Wikimedia Commons)
def reference(subject, out_dir, log):
    """A photo of the subject from Wikimedia Commons (free API, no key), cached per subject. None if nothing usable."""
    name = subject.get("name", ""); slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:60]
    out_dir.mkdir(parents=True, exist_ok=True); out = out_dir / f"{slug}.jpg"
    if out.exists(): return out
    if (out_dir / f"{slug}.none").exists(): return None
    for q in (name, subject.get("brand", "")):
        if not q: continue
        r = _get("https://commons.wikimedia.org/w/api.php", log, {"action": "query", "format": "json", "generator": "search",
                 "gsrsearch": f"{q} filetype:bitmap", "gsrnamespace": 6, "gsrlimit": 8, "prop": "imageinfo",
                 "iiprop": "url|size|mime", "iiurlwidth": 900})
        if not r or r.status_code != 200: continue
        pages = sorted((r.json().get("query") or {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
        for pg in pages:
            ii = (pg.get("imageinfo") or [{}])[0]
            if ii.get("mime") not in ("image/jpeg", "image/png") or (ii.get("width") or 0) < 600: continue
            try:
                img = requests.get(ii.get("thumburl") or ii["url"], headers=UA, timeout=60); img.raise_for_status()
                from PIL import Image
                Image.open(io.BytesIO(img.content)).convert("RGB").save(out, "JPEG", quality=90)
                log(f"  reference photo for '{name}': {pg.get('title', '')[:80]}")
                return out
            except Exception: continue
    (out_dir / f"{slug}.none").write_text("no usable Commons photo", encoding="utf-8")
    log(f"  no reference photo found for '{name}'; matching on visible brand only")
    return None

# ------------------------------------------------------------------ fetch
def fetch(c, out, max_secs):
    """Cut up to max_secs straight from the source URL (no full download) and normalise:
    portrait -> 1080x1920 (cropped), landscape -> 1920x1080 (cropped). Near-lossless so the final render is the only real compression."""
    from .render_media import inspect_video
    if Path(out).exists():
        try:
            inspect_video(out)
            return out
        except (OSError, ValueError, subprocess.TimeoutExpired):
            Path(out).unlink(missing_ok=True)
    dur = float(c.get("dur") or 0)
    start = 0.3 if dur < 20 else min(dur * 0.15, 20.0)
    length = max(3.0, min(max_secs, (dur - start - 0.3) if dur else max_secs))
    W, H = (1080, 1920) if c.get("orient", "portrait") == "portrait" else (1920, 1080)
    for attempt in range(2):
        try:
            media.ff("-user_agent", UA["User-Agent"], "-ss", f"{start:.2f}", "-i", c["file"], "-t", f"{length:.2f}", "-an",
                     "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},fps=30,format=yuv420p",
                     "-c:v", "libx264", "-preset", "veryfast", "-crf", "12", out, timeout=600)   # light on CPU so it can run beside narration
            inspect_video(out)  # ffprobe metadata + strict full-frame decode before selection
            return out
        except Exception as e:
            Path(out).unlink(missing_ok=True)  # do not cache a partial/undecodable download
            if attempt: raise RuntimeError(f"download of {c['id']} failed: {str(e)[:200]}")
    raise RuntimeError(f"download of {c['id']} produced no video")

# ------------------------------------------------------------------ one call for a list of slots
GENERIC = set("""a an the and or of in on at to for with from by into over under near close up closeup shot shots view views
aerial footage video videos clip background scene scenes slow motion timelapse time lapse cinematic stock b roll broll
person people man men woman women hands hand someone close-up top down wide angle macro camera-angle detail details
dark light bright night day modern old new big small""".split())


def _stem(w):
    for suf in ("ing", "ers", "er", "es", "ed", "s"):
        if len(w) > len(suf) + 2 and w.endswith(suf): return w[:-len(suf)]
    return w


def _subject_words(texts):
    return {_stem(w) for t in texts for w in re.findall(r"[a-z0-9]+", str(t).lower()) if len(w) > 2 and w not in GENERIC}


NARRATION_COMMON = set("""that this with from have will just about after before their there they them then than when what which
while were been being into onto over more most much many some such only also very really said says told make made made makes
used uses using like even still into year years week weeks today first last could would should every other another again
because thing things something someone people time times computer computers data technology tech digital internet online
business work working screen software device devices system systems future modern""".split())   # too broad to prove relevance


def narration_words(text):
    """Concrete words of the narration: names (Google, Willow), topic nouns (quantum, recorder)."""
    return {_stem(w) for w in re.findall(r"[a-z0-9]+", str(text).lower()) if len(w) > 3 and w not in GENERIC and w not in NARRATION_COMMON}


def on_subject(c, slot_queries, subject=None, narration=""):
    """Hard relevance gate before any model or vision check: the clip's own title/tags must name the subject of the shot,
    i.e. share a content word with the slot's queries (or its locked subject). A tissue roll found by "hidden camera in office
    ceiling" shares none and is rejected."""
    want = _subject_words(list(slot_queries) + ([subject["name"]] if subject and subject.get("name") else []))
    desc = str(c.get("desc", ""))
    if desc.count(",") >= 6: desc = ",".join(desc.split(",")[:8])   # Pixabay tag lists: only the leading (most relevant) tags count
    have = _subject_words([desc, c.get("title", "")])
    if want and not want & have: return False
    nar = narration_words(narration)   # and a concrete word of what is actually being said ("quantum", "Google", "recorder")
    return bool(nar & have) if nar else True


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
        qs = list(s["queries"])
        sj = s.get("subject") or {}
        if sj.get("name") and not any(sj["name"].lower() in q.lower() for q in qs): qs = [sj["name"]] + qs   # locked: search the subject itself too
        cands[s["id"]] = search_slot(qs[:3], orient, s["text"], log, want_long_side, st["cache"])
    save()
    unranked = [s for s in todo if s["id"] not in st["ranked"]]
    if unranked:
        log(f"  ranking candidates by meaning...")
        st["ranked"].update(rank(cfg, [{"id": s["id"], "text": s["text"], "subject": s.get("subject"), "cands": cands[s["id"]]} for s in unranked], 5, log, stop)); save()
    used = {c["id"] for v in st["picked"].values() for c in v}
    refs = {}
    for s_ in todo:
        sj = s_.get("subject")
        if sj and sj.get("name") and sj["name"] not in refs: refs[sj["name"]] = reference(sj, out_dir / "refs", log)
    ensure_vet_model(cfg, log)
    guard = story_guard(Path(out_dir).parent, " ".join(str(x.get("text") or "") for x in slots))
    mains = beat_mains(cfg, slots, log, out_dir / "mains.json") if cfg.get("clip_check_v2", True) else {}
    story_text = " ".join(str(x.get("narration") or x.get("text") or "") for x in slots if not x.get("cta"))[:600]
    places = [v.get("place") for v in mains.values() if v.get("place")]
    story_place = max(set(places), key=places.count) if places else ""
    if mains: log("  clip check: each clip must show the beat's main subject, the same kind of thing, and no other place than the story's"
                  + (f" ({story_place})" if story_place else ""))
    if guard["kinds"] or guard["side"]:
        log(f"  story guard: {', '.join(f'{k} = {'/'.join(v)}' for k, v in guard['kinds'].items()) or 'no branded subject'}"
            + (f"; cars drive with the wheel on the {guard['side']}" if guard["side"] else ""))
    try:
        for s in todo:
            if stop(): raise RuntimeError("cancelled")
            byid = {c["id"]: c for c in cands[s["id"]]}; got = []
            order = list(st["ranked"].get(s["id"], []))
            sj = s.get("subject") if (s.get("subject") or {}).get("name") else None
            if sj: order += [c["id"] for c in cands[s["id"]][:8] if c["id"] not in order]   # locked: check more, but each must match the subject
            elif fallback: order += [c["id"] for c in cands[s["id"]][:6] if c["id"] not in order]   # Shorts: never leave a beat empty
            for cid in order:
                if len(got) >= need[s["id"]]: break
                c = byid.get(cid)
                if not c or cid in used: continue
                ranked = cid in (st["ranked"].get(s["id"]) or [])   # DeepSeek already judged it by meaning: the vision check decides
                if cfg.get("stock_subject_gate", True) and not s.get("cta") and not (ranked and not sj) and \
                        not on_subject(c, s["queries"], sj, narration=s.get("narration") or s.get("text") or ""):
                    log(f"  {s['id']}: skipped {c['src']} clip {cid} (its description names neither the shot's subject nor anything the narration says: {c.get('desc', '')[:50]})")
                    st.setdefault("rejected", {}).setdefault(s["id"], []).append({"id": cid, "src": c["src"], "why": "off-subject description", "desc": c.get("desc", "")[:80]})
                    continue
                try: sh = sheet(c, out_dir / "sheets")
                except Exception as e: log(f"  preview of {cid} failed ({str(e)[:60]})"); continue
                mv = mains.get(s["id"], {})
                ok, why, seen = verify(cfg, c, sh, log, subject=sj, ref=refs.get(sj["name"]) if sj else None, avoid=s.get("avoid"),
                                      narration=s.get("narration") or s["text"], guard=guard, mainv=mv,
                                      place=mv.get("place") or story_place, neutral=bool(s.get("cta")), story=story_text)
                if not ok:
                    log(f"  {s['id']}: skipped {c['src']} clip {cid} ({why})")
                    st.setdefault("rejected", {}).setdefault(s["id"], []).append({"id": cid, "src": c["src"], "why": why, "sheet": str(sh), "desc": c.get("desc", "")[:80],
                        "clip": {k: c.get(k) for k in ("id", "src", "orient", "query", "dur", "w", "h", "file", "page", "author", "desc")}})
                    continue
                c["seen"] = seen; got.append({k: c.get(k) for k in ("id", "src", "orient", "query", "dur", "w", "h", "file", "page", "author", "desc", "seen")}); used.add(cid)
            st["picked"][s["id"]] = got; save()
            lock = f" [subject: {sj['name']}]" if sj else ""
            log(f"  {s['id']}{lock}: {len(got)}/{need[s['id']]} clip(s): " + "; ".join(f"{g['src']}: {g['seen'][:45]}" for g in got) if got else f"  {s['id']}{lock}: nothing suitable")
    finally:
        unload_vet_model(cfg)
    # download (only the seconds we need)
    (out_dir / "clips").mkdir(exist_ok=True)
    dropped = False
    for sid, v in st["picked"].items():
        for c in list(v):
            if stop(): raise RuntimeError("cancelled")
            out = out_dir / "clips" / f"{c['id']}.mp4"
            try: fetch(c, out, max_secs)
            except Exception as e:   # one clip that won't download (network, gone from the site) is dropped, not the whole job
                try: out.unlink(missing_ok=True)   # never leave a 0-byte file that later stages read as a clip
                except Exception: pass
                v.remove(c); dropped = True
                log(f"  {sid}: clip {c['id']} dropped ({str(e)[:120]}); the beat falls back to the visual ladder if it needs to")
    if dropped:
        try: state_file.write_text(json.dumps(st, indent=1), encoding="utf-8")
        except Exception: pass
    return st["picked"]

# ------------------------------------------------------------------ long videos: stock B-roll instead of GPU stills/motion
QUERIES = """For each shot below (an image prompt written for an AI generator, plus the narration it illustrates), write 2 stock-video
search phrases (3-5 words each) that would find REAL footage showing the same thing: subject + action + setting, people doing
things where possible. No abstract words ("AI", "future", "concept", "technology"), no famous people.
The story is about: {subjects}. When a shot shows one of these, put its brand and model in the phrases ("flydubai boeing 737
landing"); otherwise use no brand names.
Reply with ONLY JSON: {{"shot_id": {{"q": ["phrase", "phrase"]}}, ...}}

{shots}"""

def long_broll(job, plan, cfg, log, stop):
    """Give every AI still/motion visual a stock clip where a good one exists (v['stock'] = clip path); the rest stay AI-rendered."""
    from . import clips
    if clips.enabled(cfg): clips.for_long(job, plan, cfg, log, stop)   # your own footage first: those slots are never searched
    from . import source_visuals
    source_visuals.apply_long(job, plan, cfg, log)
    vis = [(s, v) for s in plan["sections"] for v in s["visuals"] if v["type"] in ("still", "motion") and not v.get("stock") and not v.get("no_stock")]
    if not vis: log("B-roll: nothing to do"); return
    d = job / "broll"; d.mkdir(exist_ok=True)
    qf = d / "queries.json"; qs = json.loads(qf.read_text(encoding="utf-8")) if qf.exists() else {}
    from . import coherence
    ents = coherence.entities(cfg, job, plan.get("title", ""), "\n".join(f"{s['title']}: {s['vo']}" for s in plan["sections"]), log, stop)
    subjects = ", ".join(e["name"] for e in ents if e["kind"] != "person") or "nothing specific"
    todo = [(s, v) for s, v in vis if v["id"] not in qs]
    if todo:
        with LLM(cfg, log, stop) as llm:
            for i in range(0, len(todo), 15):
                batch = todo[i:i + 15]
                txt = "\n".join(f"SHOT {v['id']}: image prompt: {v['prompt'][:300]} | narration: {s['vo'][:300]}" for s, v in batch)
                try: j = llm.chat_json("You are a precise video researcher.", QUERIES.format(shots=txt, subjects=subjects), max_tokens=2500)
                except Exception as e: log(f"  search phrases failed ({str(e)[:80]})"); j = {}
                for s, v in batch:
                    e = j.get(v["id"]); e = {"q": e} if isinstance(e, list) else (e if isinstance(e, dict) else {})
                    q = [x for x in (e.get("q") or []) if isinstance(x, str)][:2]
                    sj = e.get("subject") if isinstance(e.get("subject"), dict) and e["subject"].get("name") else None
                    qs[v["id"]] = {"q": q or [" ".join(v["prompt"].split()[:5])], "subject": sj}
        qf.write_text(json.dumps(qs, indent=1), encoding="utf-8")
    norm = lambda e: e if isinstance(e, dict) else {"q": e, "subject": None}   # older jobs stored a plain list
    slots = []
    for s, v in vis:
        q = norm(qs[v["id"]])["q"]
        sj, avoid = coherence.assign(ents, " ".join(q) + " " + v["prompt"])
        slots.append({"id": v["id"], "text": f"Shot: {v['prompt'][:300]} Narration: {s['vo'][:250]}", "queries": q, "subject": sj, "avoid": avoid})
        v["subject"] = sj
    locked = sum(1 for x in slots if x.get("subject"))
    if locked: log(f"  {locked} of {len(slots)} shot(s) locked to a story subject (e.g. {next(x['subject']['name'] for x in slots if x.get('subject'))}); they get real licensed photos of it, otherwise a 3D reconstruction")
    # stock libraries only for generic shots; subject-locked shots go to real photos (Openverse/Flickr/Commons), then reconstructions
    free = [x for x in slots if not x.get("subject")]
    picked = fill(cfg, free, "landscape", {x["id"]: 1 for x in free}, d, log, stop, want_long_side=1920, max_secs=12.0, state_file=d / "footage.json") if free else {}
    n = 0
    for s, v in vis:
        c = (picked.get(v["id"]) or [None])[0]
        if c and media.ok(d / "clips" / f"{c['id']}.mp4"):
            v["stock"] = str((d / "clips" / f"{c['id']}.mp4").relative_to(job)).replace("\\", "/"); v["stock_src"] = c["src"]; n += 1
    # locked shots with no confirmed footage: 3D reconstruction clips (never a photo-real AI image of the wrong livery/model)
    miss = [(s, v) for s, v in vis if v.get("subject") and not v.get("stock")]
    if miss:
        from . import short, photos
        k = {}; pics = {}; used = set()
        phases = coherence.beat_phases(plan["sections"])
        for s, v in miss:
            if stop(): raise RuntimeError("cancelled")
            if cfg.get("ladder_v2"):   # v2 has no real-photo rung: the shot goes down the stills ladder (Gemini image -> Flow -> ...)
                v["type"] = "still"; v["v2"] = "image ladder"; continue
            i = k.get(s["id"], 0); k[s["id"]] = i + 1
            nm = v["subject"]["name"]
            if nm not in pics:
                try: pics[nm] = photos.find(cfg, v["subject"], d / "photos", log, want=10)
                except Exception as e: log(f"  photo search failed ({str(e)[:100]})"); pics[nm] = []
            bp = phases.get(s["id"], "")
            act = ""
            if cfg.get("ladder_v2"):   # an action shot ("the jet descended...") is animated, never a zoom-pan of a photo
                from . import physics, render
                act = physics.action({"vo": "", "subject": v["subject"]}, render.vo_slice(plan, s, v))[0]
                if act: log(f"  {v['id']}: action ({act}): no still photo, animation first")
            pc = None if act or v["subject"].get("interior") or bp == "air" else \
                 next((p for p in pics[nm] if p["id"] not in used and coherence.phase_ok(bp, p.get("phase"))), None)
            if pc:   # a real, openly licensed photo of the subject, slowly zoomed/panned
                out = d / "photo_clips" / f"{v['id']}.mp4"; out.parent.mkdir(exist_ok=True)
                try:
                    photos.kenburns(pc["path"], out, 9.0, (1920, 1080), i, credit=photos.short_credit(pc))
                    v["stock"] = str(out.relative_to(job)).replace("\\", "/"); v["stock_src"] = pc["src"]; v["credit"] = photos.credit(pc)
                    used.add(pc["id"]); n += 1; continue
                except Exception as e: log(f"  photo clip for {v['id']} failed ({str(e)[:100]})")
            if cfg.get("ladder_v2"):   # v2 has no 3D reconstruction (no generic spinning shapes): graphics -> physics -> illustration -> headline
                from . import render
                v["v2"] = render.v2_after_wangp(cfg, job, v, render.vo_slice(plan, s, v), log); n += 1; continue
            g = coherence.recon(v["subject"], ents, s["vo"], i, moment=phases.get(s["id"], ""))
            out = d / "recon" / f"{v['id']}.mp4"
            if g.get("kind") == "headline":   # no 3D model for this kind of subject (e.g. a fighter jet): a drawn card
                out = d / "cards" / f"{v['id']}.mp4"; photos.headline_clip(g["text"], g.get("kicker", ""), out, 9.0)
                v["stock"] = str(out.relative_to(job)).replace("\\", "/"); v["stock_src"] = "headline"; n += 1; continue
            try:
                short.render_recon(g, out, 9.0, (1920, 1080), cfg, log, stop)
                v["stock"] = str(out.relative_to(job)).replace("\\", "/"); v["stock_src"] = "reconstruction"; n += 1
            except Exception as e:
                # never hand a subject-locked shot to WanGP (an image model invents liveries/models): a drawn headline card instead
                log(f"  reconstruction for {v['id']} failed ({str(e)[:120]}); using a headline card")
                words = s["vo"].split(); text = " ".join(words[:10]).rstrip(",.;") + ("..." if len(words) > 10 else "")
                out = d / "cards" / f"{v['id']}.mp4"
                photos.headline_clip(text, v["subject"]["name"][:30], out, 9.0)   # if even this fails the job stops: no AI fallback
                v["stock"] = str(out.relative_to(job)).replace("\\", "/"); v["stock_src"] = "headline"; n += 1
        v2n = {}
        for _, v in miss:
            if v.get("v2"): v2n[v["v2"]] = v2n.get(v["v2"], 0) + 1
        log(f"  locked shots without footage: {sum(1 for _, v in miss if v.get('credit'))} real photo(s), "
            + (f"ladder v2: {', '.join(f'{k} {c}' for k, c in v2n.items())}, " if v2n else "")
            + f"{sum(1 for _, v in miss if v.get('stock_src') == 'reconstruction')} 3D reconstruction(s), "
            f"{sum(1 for _, v in miss if v.get('stock_src') == 'headline')} headline card(s)")
    bad = [v["id"] for _, v in vis if v.get("subject") and not v.get("stock") and not v.get("v2")]
    if bad: raise RuntimeError(f"subject-locked shots {', '.join(bad[:5])} have no visual; refusing to let the AI image model draw them")
    log(f"B-roll: {n} of {len(vis)} AI visuals replaced with real footage, " + ("v2 graphics / illustrations" if cfg.get("ladder_v2") else "reconstructions")
        + f"; {len(vis) - n} will be AI-rendered")
