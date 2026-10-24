"""Interview edit: your own footage where the ORIGINAL AUDIO leads and narration only bridges (owner, 2026-10-24).

Made for footage you shot yourself (no third-party copyright), e.g. a walk-and-talk interview filmed on the phone's front camera.
Nothing here strips the clip's sound (the rest of Video Studio does, by design, for third-party sources).

Steps (each cached in the work folder, so a re-run continues):
  1. prep        the interview's audio (16 kHz mono) for transcription
  2. transcribe  faster-whisper with word times (GPU large-v3-turbo, else CPU small.en) -> transcript.json
  3. plan        the script AI reads the numbered, timed transcript and picks the strongest moments (soundbites) and writes
                 short narration bridges (hook, place names, a line between topics, outro). One plan for a Short (<= ~90 s)
                 and one for a mini-documentary (8-12 min, chapters). Narration is at most ~15% of the runtime.
  4. cut         each soundbite cut WITH its audio: front-camera mirror removed (hflip), Short = 9:16 crop centred on the
                 faces found in it (OpenCV; centre if none), alternating gentle punch-ins; documentary = 16:9 as filmed.
                 Each bridge = narration (Kokoro) over your other clips from the same folder (B-roll, muted), or over the
                 next soundbite's picture when no B-roll fits.
  5. assemble    parts joined, captions burned in (soundbites: whisper's words; bridges: the narration text), music bed
                 ducked under every voice (music.mix).
Outputs: <work>/<name>_short.mp4, <work>/<name>_documentary.mp4, plus plan.json / transcript.json for review.
Visual work is ffmpeg on the CPU (no GPU effects); only transcription and Kokoro may use the GPU."""
import json
import math
import random
import re
import shutil
import time
from pathlib import Path

from . import media

VIDEO_EXT = (".mov", ".mp4", ".m4v", ".mkv")
CUT_VERSION = "7"   # bump when the way parts are cut changes, so cached parts are made again
PLAN = """You edit a documentary from the creator's OWN interview footage. The interview audio is the star: viewers should mostly
hear the people on camera. Your narration only bridges: a hook, where we are, a line between topics, a closing line.

About the footage (from the creator): {context}

Transcript, numbered segments with times (seconds from the start of the footage):
{segments}

Other clips in the same folder you may use as B-roll under narration (name: seconds): {broll}

Research notes (checked facts with sources; the ONLY facts you may add beyond the transcript):
{notes}

Write JSON only:
{{
 "title": "a YouTube title, under 70 characters, honest, no clickbait",
 "short": {{"items": [ ... ]}},
 "documentary": {{"chapters": [{{"title": "chapter title", "items": [ ... ]}}, ...]}}
}}
Each item is one of:
  {{"bite": [first_segment, last_segment]}}  consecutive segments played with their own audio (the main thing);
  {{"narr": "one or two short sentences", "broll": "a clip name from the list, or empty"}}  a bridge;
  {{"insert": "one or two sentences of context", "note": <research note number>, "visual": "what a photo for it should show,
    3-8 words (e.g. 'Sea Venture shipwreck painting', 'Hamilton Bermuda harbour')", "card": "optional on-screen fact, under 40
    characters (e.g. '~1,000 Muslims, 0.8% of Bermuda')"}}  a short context tidbit right after the soundbite it explains.
Rules:
- short: {short_secs} seconds or less in total; open with the single most striking soundbite or a one-line hook, 3-6 soundbites.
- documentary: {doc_min}-{doc_max} minutes in total, 4-7 chapters in a sensible order (you may rearrange the footage's order).
- Soundbites: complete thoughts (start and end at sentence boundaries), each 6-60 seconds; skip small talk, dead air,
  directions, repeated points and anything the speaker would not want aired (private details, addresses, phone numbers).
- Context inserts: sparingly, only where a soundbite raises a question a viewer would have (history, numbers, what happened
  next). short: at most 2; documentary: one or two per chapter (use most of the notes somewhere). Every insert uses exactly one research note and says only what
  that note says. Narration and inserts together stay under 30% of the runtime; the interview stays the main driver.
- Narration: at most 15% of the runtime, first person plural is fine ("we"), never invent facts that are not in the transcript
  or the creator's note, respectful and warm toward the people and their faith; light humour only at our own expense.
- Never put words in anyone's mouth; a soundbite is exactly what was said."""


def _log(log, m):
    (log or print)(m)


# ------------------------------------------------------------------ 1-2 transcript
def transcribe(src, work, log=print):
    out = Path(work) / "transcript.json"
    if out.exists(): return json.loads(out.read_text(encoding="utf-8"))
    wav = Path(work) / "audio16k.wav"
    if not media.ok(wav, 1):
        _log(log, "Interview: extracting the audio for transcription")
        media.ff("-i", src, "-map", "0:a:0", "-ac", 1, "-ar", 16000, wav, timeout=1800)
    from faster_whisper import WhisperModel
    def run(m, label):
        _log(log, f"Interview: transcribing {media.dur(wav) / 60:.0f} min ({label})")
        segs, _ = m.transcribe(str(wav), language="en", vad_filter=True, word_timestamps=True, beam_size=5)
        res, t0 = [], time.time()
        for s in segs:
            res.append({"i": len(res), "start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip(),
                        "words": [[w.word.strip(), round(w.start, 2), round(w.end, 2)] for w in (s.words or []) if w.word.strip()]})
            if time.time() - t0 > 60: _log(log, f"  transcribed to {int(s.end // 60)} min"); t0 = time.time()
        return res
    try: segs = run(WhisperModel("large-v3-turbo", device="cuda", compute_type="float16"), "GPU")
    except Exception as e:
        _log(log, f"  GPU transcription unavailable ({str(e)[:80]}); CPU")
        segs = run(WhisperModel("small.en", device="cpu", compute_type="int8"), "CPU")
    out.write_text(json.dumps(segs, indent=1, ensure_ascii=False), encoding="utf-8")
    return segs


# ------------------------------------------------------------------ 3 plan
def broll_list(src):
    """Your other clips in the interview's folder (name -> seconds), for narration bridges."""
    out = {}
    for f in sorted(Path(src).parent.iterdir()):
        if f.suffix.lower() in VIDEO_EXT and f.resolve() != Path(src).resolve():
            try: d = media.dur(f)
            except Exception: continue
            if d >= 3: out[f.stem] = round(d, 1)
    return out


def plan(cfg, segs, context, broll, work, log=print, short_secs=90, doc_min=8, doc_max=12, notes=None):
    out = Path(work) / "plan.json"
    if out.exists(): return json.loads(out.read_text(encoding="utf-8"))
    lines = "\n".join(f"[{s['i']}] {s['start']:.0f}-{s['end']:.0f}: {s['text']}" for s in segs)
    from .llm import LLM
    n = len(segs)
    def check(j, strict=True):
        for it in _items(j.get("short") or {}) + [x for c in (j.get("documentary") or {}).get("chapters", []) for x in c.get("items", [])]:
            if "bite" in it:
                a, b = it["bite"]
                if not (0 <= int(a) <= int(b) < n): raise ValueError(f"bite {it['bite']} is outside 0-{n - 1}")
                d = segs[int(b)]["end"] - segs[int(a)]["start"]
                if strict and d > 75: raise ValueError(f"bite {it['bite']} is {d:.0f} s long; soundbites must be 6-60 s (use fewer segments)")
        if not _items(j.get("short") or {}) or not (j.get("documentary") or {}).get("chapters"): raise ValueError("both short and documentary are needed")
        if strict:
            st = total_secs(_items(j["short"]), segs)
            if st > short_secs + 20: raise ValueError(f"the short is {st:.0f} s; it must be {short_secs} s or less")
            dt = total_secs([x for c in j["documentary"]["chapters"] for x in c.get("items", [])], segs) / 60
            if not doc_min - 2 <= dt <= doc_max + 3: raise ValueError(f"the documentary is {dt:.1f} min; it must be {doc_min}-{doc_max} min")
    _log(log, f"Interview: picking soundbites from {n} segments (script AI)")
    with LLM(dict(cfg), log, lambda: False) as llm:
        try: j = llm.chat_json("You are an award-winning documentary editor. Reply with JSON only.",
                          PLAN.format(context=context, segments=lines[:60000], broll=json.dumps(broll), short_secs=short_secs,
                                      notes="\n".join(f"[{i}] {n['fact']}" for i, n in enumerate(notes or [])) or "(none)",
                                      doc_min=doc_min, doc_max=doc_max), max_tokens=6000, check=check)
        except RuntimeError:   # lengths still off after 3 tries: take a valid plan and trim it to size
            j = llm.chat_json("You are an award-winning documentary editor. Reply with JSON only.",
                              PLAN.format(context=context, segments=lines[:60000], broll=json.dumps(broll), short_secs=short_secs,
                                          notes="\n".join(f"[{i}] {n['fact']}" for i, n in enumerate(notes or [])) or "(none)",
                                          doc_min=doc_min, doc_max=doc_max), max_tokens=6000, check=lambda x: check(x, False))
    j = fit(j, segs, short_secs)
    out.write_text(json.dumps(j, indent=1, ensure_ascii=False), encoding="utf-8")
    return j


SHORT = """Cut a YouTube Short (60-{short_secs} seconds) from a mini-documentary's material. The interview audio leads.
About the footage: {context}
The documentary's soundbites (segment numbers with their words) and context notes:
{material}
Rules: tell ONE story with a beginning, middle and end (pick the strongest thread, e.g. the land that was taken, or the community
that went from the Nation of Islam to its own mosque). Open with the most gripping soundbite of that thread (under 20 seconds);
then 2-4 more soundbites from the SAME thread (each 5-20 seconds; a sub-range of a soundbite's segments is fine), joined by up to
three one-sentence narration lines that carry the story forward; up to TWO context inserts from the notes that explain the
history behind it (only what the note says); END ON A SOUNDBITE that lands the story. No small talk, no logistics, nothing off-thread.
Narration only connects: it never states anything that is not in the transcript or the notes, never links two facts that the
sources don't link (e.g. do not claim the mosque stands on land that was taken), and attributes the speaker's claims to him
("Mr. Clinton says ...", "as he tells it ...") instead of stating them as fact.
Also write "hook": an on-screen line for the opening soundbite, under 45 characters, true to the story.
Reply with JSON only: {{"hook": "...", "items": [{{"bite": [first, last]}} | {{"narr": "...", "broll": ""}} | {{"insert": "...", "note": n, "visual": "...", "card": "..."}}]}}"""


def short_plan(cfg, segs, pl, context, notes, work, log=print, short_secs=90):
    """The Short, cut from the documentary's chosen material (a separate pass: one plan for both came out weak). Cached."""
    import hashlib
    out = Path(work) / f"short_plan_{hashlib.md5(SHORT.encode()).hexdigest()[:6]}.json"   # a changed brief makes a new plan
    if out.exists():
        j = json.loads(out.read_text(encoding="utf-8")); j["items"] = end_on_bite(_items(j)); return j
    from .llm import LLM
    bites = sorted({tuple(it["bite"]) for c in pl["documentary"]["chapters"] for it in c.get("items", []) if "bite" in it})
    mat = "\n".join(f"[{a}-{b}] " + " ".join(segs[i]["text"] for i in range(a, b + 1))[:600] for a, b in bites)
    mat += "\n\nNotes:\n" + ("\n".join(f"[{i}] {n['fact']}" for i, n in enumerate(notes or [])) or "(none)")
    n = len(segs)
    def check(j, strict=True):
        its = j.get("items") or []
        if not its or not any("bite" in it for it in its): raise ValueError("the Short needs soundbites")
        if strict and "bite" not in its[-1]: raise ValueError("the Short must END on a soundbite, not narration")
        for it in its:
            if "bite" in it:
                a, b = int(it["bite"][0]), int(it["bite"][1])
                if not 0 <= a <= b < n: raise ValueError(f"bite {it['bite']} out of range")
                if strict and segs[b]["end"] - segs[a]["start"] > 30: raise ValueError(f"bite {it['bite']} is longer than 20 s; use fewer segments")
        if strict and total_secs(its, segs) > short_secs + 20: raise ValueError(f"the Short is {total_secs(its, segs):.0f} s; keep it under {short_secs} s")
    try:
        with LLM(dict(cfg), log, lambda: False) as llm:
            try: j = llm.chat_json("You are a YouTube Shorts editor. Reply with JSON only.",
                                   SHORT.format(short_secs=short_secs, context=context, material=mat[:40000]), max_tokens=1500, check=check)
            except RuntimeError:   # still too long after 3 tries: take its story and trim it to size
                j = llm.chat_json("You are a YouTube Shorts editor. Reply with JSON only.",
                                  SHORT.format(short_secs=short_secs, context=context, material=mat[:40000]), max_tokens=1500,
                                  check=lambda x: check(x, False))
        j = fit({"short": j, "documentary": {"chapters": []}}, segs, short_secs, bite_max_short=22)["short"]
        j["items"] = end_on_bite(_items(j))
    except Exception as e:
        _log(log, f"  short plan: kept the combined plan's Short ({str(e)[:100]})"); return None
    out.write_text(json.dumps(j, indent=1, ensure_ascii=False), encoding="utf-8")
    return j


def total_secs(items, segs):
    """Rough runtime: soundbites from the transcript, narration at ~2.6 words a second."""
    t = 0.0
    for it in items:
        if "bite" in it: t += segs[int(it["bite"][1])]["end"] - segs[int(it["bite"][0])]["start"] + 0.45
        else: t += len(str(it.get("narr") or it.get("insert") or "").split()) / 2.6 + 0.35
    return t


def fit(j, segs, short_secs=90, bite_max_short=40, bite_max_doc=60):
    """Hard limits the script AI sometimes ignores: long soundbites end at a segment boundary within the limit; the Short loses
    items from the end until it fits (the opening is kept)."""
    def trim(items, mx):
        for it in items:
            if "bite" in it:
                a, b = int(it["bite"][0]), int(it["bite"][1])
                while b > a and segs[b]["end"] - segs[a]["start"] > mx: b -= 1
                it["bite"] = [a, b]
    trim(_items(j["short"]), bite_max_short)
    for c in j["documentary"]["chapters"]: trim(c.get("items", []), bite_max_doc)
    items = _items(j["short"])
    while len(items) > 2 and total_secs(items, segs) > short_secs + 10: items.pop(-2 if "narr" in items[-1] else -1)
    j["short"]["items"] = items
    return j


def _items(p):
    return list(p.get("items") or [])


def end_on_bite(items):
    """The Short ends on the guest's own words: trailing narration / context lines are dropped (the AI sometimes adds one)."""
    items = list(items)
    while len(items) > 1 and "bite" not in items[-1]: items.pop()
    return items


# ------------------------------------------------------------------ 4 cut
def _faces_x(src, t0, t1, flip=True):
    """Average horizontal centre (0..1) of faces in 3 frames of the range, or None (OpenCV; None when it isn't installed)."""
    try:
        import cv2
        import numpy as np  # noqa: F401
    except ImportError:
        return None
    casc = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    xs = []
    tmp = Path(media.__file__).parent / "_facegrab.jpg"
    for k in range(3):
        t = t0 + (t1 - t0) * (k + 1) / 4
        try:
            media.ff("-ss", f"{t:.2f}", "-i", src, "-frames:v", 1, "-vf", ("hflip," if flip else "") + "scale=640:-2", tmp, timeout=120)
            im = cv2.imread(str(tmp)); g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
            for (x, y, w, h) in casc.detectMultiScale(g, 1.15, 5, minSize=(40, 40)):
                xs.append(((x + w / 2) / im.shape[1], w * h))
        except Exception:
            continue
    try: tmp.unlink()
    except OSError: pass
    if not xs: return None
    tot = sum(a for _, a in xs)
    return sum(x * a for x, a in xs) / tot


def _vf(kind, xc=None, zoom=1.0, flip=True):
    """Video filter: mirror removed, then Short = 9:16 crop around xc (0..1) / documentary = 16:9; gentle zoom."""
    f = ["hflip"] if flip else []
    if kind == "short":
        xc = 0.5 if xc is None else min(max(xc, 0.0), 1.0)
        cw = f"ih*9/16/{zoom}"; ch = f"ih/{zoom}"
        f.append(f"crop={cw}:{ch}:max(0\\,min(iw-{cw}\\,iw*{xc:.3f}-{cw}/2)):(ih-{ch})/2")
        f.append("scale=1080:1920:flags=lanczos")
    else:
        if zoom > 1.0: f.append(f"crop=iw/{zoom}:ih/{zoom}")
        f.append("scale=1920:1080:force_original_aspect_ratio=decrease:flags=lanczos,pad=1920:1080:(ow-iw)/2:(oh-ih)/2")
    f.append("fps=30,format=yuv420p,setsar=1")
    return ",".join(f)


GENERIC = {"town", "city", "old", "aerial", "view", "island", "history", "historic", "photo", "image", "street", "people", "building",
           "buildings", "area", "land", "house", "houses", "black", "white", "early", "modern", "today", "parish", "local"}
FITS = """A documentary narrator says: "{line}"
Wikimedia Commons offers a photo titled: "{title}"
Would that photo be a fitting, honest illustration of what the narrator says (same place AND the same kind of subject or era)?
A group portrait of soldiers, a sports team, a ship or a map that is not what the line is about = no.
JSON: {{"fits": true|false, "why": "a few words"}}"""


def _fits(cfg, line, title, log=print):
    if not cfg or not line: return True
    try:
        from .llm import LLM
        with LLM(dict(cfg), log, lambda: False) as llm:
            j = llm.chat_json("You check picture choices for a documentary. Reply with JSON only.",
                              FITS.format(line=line[:400], title=title[:200]), max_tokens=120)
        ok = bool(j.get("fits"))
        if not ok: _log(log, f"    Commons photo '{title[:60]}' skipped: {str(j.get('why', ''))[:60]}")
        return ok
    except Exception:
        return True   # the checker being down doesn't block the edit


def commons_photo(query, out, log=print, place="Bermuda", cfg=None, line=""):
    """A freely licensed photo from Wikimedia Commons: each suggestion in the query (split at ';'), then shorter forms of it.
    -> (path, credit) or (None, "")."""
    tries = []
    for q in [x.strip() for x in re.split(r"[;|]", str(query)) if x.strip()]:
        words = [w for w in re.findall(r"[A-Za-z0-9']+", q) if w.lower() not in ("of", "the", "a", "an", "and", "on", "in", "with", "showing")]
        for t in (q, " ".join(words[:4]), " ".join(words[:2])):
            if t and place and place.lower() not in t.lower(): t = f"{t} {place}"   # stay in the story's place (no Dubai for Tucker's Town)
            if t and t not in tries: tries.append(t)
    for n, q in enumerate(tries[:8]):
        if n: time.sleep(1.5)   # Commons rate-limits bursts (429)
        got = _commons_one(q, out, log, need=[w for w in re.findall(r"[A-Za-z]{4,}", q) if w.lower() != place.lower()], place=place,
                           judge=(lambda t: _fits(cfg, line, t, log)) if cfg and line else None)
        if got[0]: return got
    return None, ""


def _commons_one(query, out, log=print, need=(), place="", judge=None):
    import requests
    UA = {"User-Agent": "VideoStudio/1.0 (interview edit; contact via YouTube channel)"}
    try:
        r = requests.get("https://commons.wikimedia.org/w/api.php", headers=UA, timeout=30, params={
            "action": "query", "format": "json", "generator": "search", "gsrsearch": f"{query} filetype:bitmap", "gsrnamespace": 6,
            "gsrlimit": 10, "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 1600,
            "iiextmetadatafilter": "Artist|LicenseShortName"})
        pages = sorted((r.json().get("query") or {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
        for pg in pages:
            ii = (pg.get("imageinfo") or [{}])[0]
            if ii.get("mime") not in ("image/jpeg", "image/png") or (ii.get("width") or 0) < 800: continue
            title = pg.get("title", "").lower()
            if place and place.lower() not in title: continue   # the file itself must be about the place (title names it)
            key = [w for w in need if w.lower() not in GENERIC]
            if key and not all(w.lower() in title for w in key): continue   # and about the thing asked for (every distinctive word)
            if need and not key and not any(w.lower() in title for w in need): continue
            if judge and not judge(pg.get("title", "")): continue   # and it actually shows what the line is about
            meta = ii.get("extmetadata") or {}
            lic = re.sub(r"<.*?>", "", (meta.get("LicenseShortName") or {}).get("value", "")).strip()
            if not lic or not re.search(r"CC|Public domain|PD", lic, re.I): continue
            artist = re.sub(r"<.*?>", "", (meta.get("Artist") or {}).get("value", "")).strip()[:60] or "Wikimedia Commons"
            img = requests.get(ii.get("thumburl") or ii["url"], headers=UA, timeout=60); img.raise_for_status()
            Path(out).write_bytes(img.content)
            _log(log, f"    Commons photo for '{query}': {pg.get('title', '')[:70]} ({lic})")
            return out, f"Photo: {artist} / Wikimedia Commons, {lic}"
    except Exception as e:
        _log(log, f"    Commons search failed ({str(e)[:80]})")
    return None, ""


def still_part(img, wav, out, kind):
    """A still with a slow push-in (CPU) under the narration."""
    w, h = (1080, 1920) if kind == "short" else (1920, 1080)
    d = media.dur(wav) + 0.35; n = int(d * 30) + 1
    vf = (f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase,crop={w * 2}:{h * 2},"
          f"zoompan=z='min(zoom+0.0006,1.10)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={n}:s={w}x{h}:fps=30,format=yuv420p,setsar=1,"
          f"fade=t=in:st=0:d=0.35,fade=t=out:st={d - 0.35:.2f}:d=0.35")
    media.ff("-loop", 1, "-i", img, "-i", wav, "-t", f"{d:.2f}", "-map", "0:v:0", "-map", "1:a:0", "-vf", vf,
             "-af", "loudnorm=I=-16:TP=-1.5:LRA=11,apad", *ENC, "-shortest", out, timeout=900)
    return out


ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]


def cut_bite(src, t0, t1, out, kind, k, flip=True):
    if media.ok(out, 0.5): return out
    xc = _faces_x(src, t0, t1, flip) if kind == "short" else None
    zoom = 1.0 if k % 2 == 0 else 1.12   # every other soundbite a little closer: a cut, not a jump
    media.ff("-ss", f"{t0:.2f}", "-i", src, "-t", f"{t1 - t0:.2f}", "-map", "0:v:0", "-map", "0:a:0",
             "-vf", _vf(kind, xc, zoom, flip), "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", *ENC, out, timeout=1800)
    return out


class Cutaways:
    """Pictures to cover a soundbite where only the camera holder's face is on screen: the guest elsewhere in the video first,
    then your B-roll clips (turned upright when filmed sideways). Each stretch is used once while others remain."""
    def __init__(self, src, an, used, broll_files, work, flip, log=print):
        from . import shots
        self.src, self.flip, self.work, self.log = src, flip, work, log
        self.runs = [[a, b] for a, b in shots.cutaway_pool(an, used)]
        self.an = an
        self.broll = [(f, media.dur(f)) for f in broll_files]
        self.bi = 0

    def take(self, secs):
        """-> (file, start, flip, guest_box, rotation)"""
        from . import shots
        for r in self.runs:
            if r[1] - r[0] >= secs:
                a = r[0]; r[0] += secs + 1
                gs = [f for s in self.an["secs"] if a <= s["t"] < a + secs for f in shots.split(s["faces"])[0]]
                g = [sum(x[n] for x in gs) / len(gs) for n in range(4)] if gs else None
                return self.src, float(a), self.flip, g, ""
        if self.broll:
            f, d = self.broll[self.bi % len(self.broll)]; self.bi += 1
            st = (self.bi * 7.3) % max(0.1, d - secs) if d > secs else 0.0
            return f, st, False, None, shots.orient(f, self.work, self.log)
        return self.src, 0.0, self.flip, None, ""


def cut_bite_framed(src, t0, t1, out, kind, flip, an, cuts, log=print):
    """A soundbite with its own audio and a framed picture: on the guest, level, and covered by a cutaway where only the
    holder's face would show."""
    if media.ok(out, 0.5): return out
    from . import shots
    tmpd = Path(out).with_suffix(""); tmpd.mkdir(exist_ok=True)
    segs, lst = [], tmpd / "v.txt"
    for n, (a, b, k, g, tilt) in enumerate(shots.plan_shots(an, t0, t1)):
        v = tmpd / f"s{n:02}.mp4"; d = b - a
        if k == "guest" and not shots.holder_out(kind, g): k = "self"   # owner: "cut me out completely" - no crop can, so cut away
        if k in ("self", "empty"):   # cutaway: the sound goes on, the picture shows the guest elsewhere / B-roll
            f, st, fl, gb, rot = cuts.take(d)
            vf = (rot + "," if rot else "") + shots.vf_frame(kind, gb, 0.0, fl)
            media.ff("-ss", f"{st:.2f}", "-i", f, "-t", f"{d:.2f}", "-an", "-vf", vf, *ENC[:6], v, timeout=900)
        else:
            media.ff("-ss", f"{a:.2f}", "-i", src, "-t", f"{d:.2f}", "-an", "-vf", shots.vf_frame(kind, g, tilt, flip), *ENC[:6], v, timeout=900)
        segs.append(v)
    lst.write_text("".join(f"file '{x.as_posix()}'\n" for x in segs), encoding="utf-8")
    media.ff("-f", "concat", "-safe", 0, "-i", lst, "-ss", f"{t0:.2f}", "-i", src, "-t", f"{t1 - t0:.2f}", "-map", "0:v:0", "-map", "1:a:0",
             "-c:v", "copy", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", *ENC[6:], "-shortest", out, timeout=1800)
    return out


def card_part(text_bg, d, out, kind, cfg=None):
    """A title / end card: a picture (file, start, flip, rotation) blurred and darkened, silent (the music carries it)."""
    from . import shots
    f, st, fl, rot = text_bg
    vf = (rot + "," if rot else "") + shots.vf_frame(kind, None, 0.0, fl) + f",boxblur=18,eq=brightness=-0.18,fade=t=in:st=0:d=0.4,fade=t=out:st={d - 0.5:.2f}:d=0.5"
    media.ff("-ss", f"{st:.2f}", "-i", f, "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{d:.2f}", "-map", "0:v:0", "-map", "1:a:0",
             "-vf", vf, *ENC, "-shortest", out, timeout=600)
    return out


def cut_bridge(cfg, text, picture, out, kind, work, k, log=print):
    """Narration (Kokoro) over a muted picture: (file, start, flip) for B-roll or the next soundbite's footage."""
    if media.ok(out, 0.5): return out
    from . import tts
    wav = Path(work) / "narr" / f"n{k}.wav"; wav.parent.mkdir(exist_ok=True)
    tts.kokoro_batch(cfg, [(text, wav)], log, "interview narration")
    d = media.dur(wav) + 0.35
    from . import shots
    f, start, flip = picture[:3]; rot = picture[3] if len(picture) > 3 else ""; g = picture[4] if len(picture) > 4 else None
    vf = (rot + "," if rot else "") + shots.vf_frame(kind, g, 0.0, flip) + f",fade=t=in:st=0:d=0.3,fade=t=out:st={d - 0.3:.2f}:d=0.3"
    media.ff("-ss", f"{start:.2f}", "-i", f, "-i", wav, "-t", f"{d:.2f}", "-map", "0:v:0", "-map", "1:a:0",
             "-vf", vf, "-af", "loudnorm=I=-16:TP=-1.5:LRA=11,apad", *ENC, "-shortest", out, timeout=900)
    return out


# ------------------------------------------------------------------ 5 captions + assemble
ASS = """[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Arial,{fs},&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,1,0,0,0,100,100,0,0,1,5,2,2,{ml},{ml},{mv},1
Style: Narr,Arial,{fs},&H0066E0FF,&H0066E0FF,&H00000000,&H96000000,1,1,0,0,100,100,0,0,1,5,2,2,{ml},{ml},{mv},1
Style: Credit,Arial,{cs},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,1,7,30,30,30,1
Style: Hook,Arial Black,{hs},&H0000D7FF,&H0000D7FF,&H00000000,&HA0000000,1,0,0,0,100,100,0,0,1,7,3,8,60,60,{hv},1
Style: Title,Arial Black,{ts},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,6,3,5,80,80,0,1
Style: Sub,Arial,{ss},&H0000D7FF,&H0000D7FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,4,2,5,80,80,0,1
Style: Card,Arial,{ks},&H00FFFFFF,&H00FFFFFF,&H00000000,&HA0000000,1,0,0,0,100,100,0,0,3,18,0,5,60,60,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _t(t):
    t = max(0.0, t); return f"{int(t // 3600)}:{int(t % 3600 // 60):02}:{t % 60:05.2f}"


def _caption_lines(words, max_words):
    """[(text, start, end)] chunks of up to max_words, breaking after sentence ends."""
    out, cur = [], []
    for w, a, b in words:
        cur.append((w, a, b))
        if len(cur) >= max_words or re.search(r"[.!?]$", w):
            out.append((" ".join(x[0] for x in cur), cur[0][1], cur[-1][2])); cur = []
    if cur: out.append((" ".join(x[0] for x in cur), cur[0][1], cur[-1][2]))
    return out


def _writable(p):
    try:
        with open(p, "r+b"): return True
    except OSError: return False


def assemble(parts, out, kind, work, cfg, log=print, title=""):
    """parts: [{"file", "words": [(w, start, end)] relative to the part, "style": "Cap"|"Narr"}]."""
    w, h = (1080, 1920) if kind == "short" else (1920, 1080)
    fs, ml, mv, maxw = (70, 90, 430, 5) if kind == "short" else (54, 160, 60, 9)
    cs, ks = (30, 76) if kind == "short" else (24, 64)
    hs, hv = (92, 300) if kind == "short" else (80, 90)
    ts, ss = (96, 58) if kind == "short" else (96, 52)
    ev, t = [], 0.0
    lst = Path(work) / f"{kind}_concat.txt"
    with open(lst, "w", encoding="utf-8") as fh:
        for p in parts:
            fh.write(f"file '{Path(p['file']).as_posix()}'\n")
            d = media.dur(p["file"])
            if p.get("credit"): ev.append(f"Dialogue: 1,{_t(t)},{_t(t + d)},Credit,,0,0,0,,{p['credit']}\n")
            for line, style, dy in p.get("titles") or []:   # title / end card text: centred lines
                ev.append(f"Dialogue: 2,{_t(t + 0.3)},{_t(t + d - 0.3)},{style},,0,0,0,,{{\\fad(300,300)\\pos({w // 2},{h // 2 + dy})}}{line}\n")
            if p.get("hook"): ev.append(f"Dialogue: 2,{_t(t)},{_t(t + d)},Hook,,0,0,0,,{{\\fad(0,250)}}{p['hook']}\n")
            if p.get("card"): ev.append(f"Dialogue: 1,{_t(t + 0.3)},{_t(t + d - 0.2)},Card,,0,0,0,,{{\\fad(200,200)}}{p['card']}\n")
            for txt, a, b in _caption_lines(p.get("words") or [], maxw):
                if a >= d: break
                ev.append(f"Dialogue: 0,{_t(t + a)},{_t(t + min(b + 0.15, d))},{p.get('style', 'Cap')},,0,0,0,,{{\\fad(80,60)}}{txt}\n")
            t += d
    ass = Path(work) / f"{kind}.ass"
    ass.write_text(ASS.format(w=w, h=h, fs=fs, ml=ml, mv=mv, cs=cs, ks=ks, hs=hs, hv=hv, ts=ts, ss=ss) + "".join(ev), encoding="utf-8")
    joined = Path(work) / f"_{kind}_joined.mp4"
    media.ff("-f", "concat", "-safe", 0, "-i", lst, "-c", "copy", joined, timeout=1800)
    sub = ass.as_posix().replace(":", "\\:")
    media.ff("-i", joined, "-vf", f"subtitles='{sub}'", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "copy",
             "-movflags", "+faststart", out, timeout=7200)
    joined.unlink(missing_ok=True)
    try:
        from . import music
        if not _writable(out): raise RuntimeError(f"{Path(out).name} is open in another program (a player?); music not added")
        music.mix(out, dict(cfg, music_bed_db=float(cfg.get("interview_music_db", -8)), music_hook_db=float(cfg.get("interview_music_db", -8))),
                  log, 6.0, seed=title or kind, text=title)   # quieter than a narrated Short: the interview is the star
    except Exception as e:
        _log(log, f"  music skipped ({str(e)[:120]})")
    _log(log, f"Interview {kind}: {out} ({media.dur(out) / 60:.1f} min)")
    return out


# ------------------------------------------------------------------ the whole edit
HOOK = """Pick the cold open for a YouTube {what} made from this interview: the single most surprising, emotional or
curiosity-making line actually said (an exact quote, 6-20 words, from ONE segment), plus a hook line shown on screen over it.
About the footage: {context}
Transcript:
{segments}
Rules: the quote must be copied exactly from the segment; the hook text is under 45 characters, true to what is said, no
clickbait lies, respectful to the people in it; never private details. Reply with JSON only:
{{"seg": <segment number>, "quote": "exact words", "text": "on-screen hook"}}"""


def _norm(w): return re.sub(r"[^a-z0-9]", "", w.lower())


def hook(cfg, segs, context, kind, work, log=print):
    """-> {"t0", "t1", "text", "quote"} for the cold open (cached in hook_<kind>.json), or None."""
    out = Path(work) / f"hook_{kind}.json"
    if out.exists(): return json.loads(out.read_text(encoding="utf-8"))
    import difflib
    from .llm import LLM
    lines = "\n".join(f"[{x['i']}] {x['text']}" for x in segs)
    def check(j):
        i = int(j.get("seg", -1))
        if not 0 <= i < len(segs): raise ValueError("seg out of range")
        if not str(j.get("text") or "").strip() or len(str(j.get("quote") or "").split()) < 4: raise ValueError("quote and text needed")
    try:
        with LLM(dict(cfg), log, lambda: False) as llm:
            j = llm.chat_json("You are a YouTube documentary editor. Reply with JSON only.",
                              HOOK.format(what="Short" if kind == "short" else "mini-documentary", context=context, segments=lines[:60000]),
                              max_tokens=300, check=check)
    except Exception as e:
        _log(log, f"  hook: none ({str(e)[:100]})"); return None
    q = [_norm(w) for w in str(j["quote"]).split() if _norm(w)]
    for lo, hi in ((int(j["seg"]) - 3, int(j["seg"]) + 4), (0, len(segs))):   # near the named segment, else anywhere
        words = [w for x in segs[max(0, lo):hi] for w in x["words"]]
        have = [_norm(w[0]) for w in words]
        m = difflib.SequenceMatcher(None, have, q, autojunk=False).find_longest_match(0, len(have), 0, len(q))
        if m.size >= max(3, len(q) // 2): break
    if m.size < max(3, len(q) // 2): _log(log, "  hook: the quote wasn't found in the transcript; no cold open"); return None
    a = max(0, m.a - (m.b if m.b else 0)); b = min(len(words) - 1, m.a + m.size - 1 + (len(q) - m.b - m.size))
    res = {"t0": max(0.0, words[a][1] - 0.15), "t1": words[b][2] + 0.35, "text": str(j["text"]).strip()[:48], "quote": j["quote"],
           "words": [(w[0], w[1], w[2]) for w in words[a:b + 1]]}
    out.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    _log(log, f"  hook ({kind}): \"{res['text']}\" over \"{res['quote'][:70]}\" ({res['t1'] - res['t0']:.1f}s)")
    return res


def build(cfg, src, work, context, log=print, kinds=("short", "documentary"), flip=True, name="interview", version="", notes=None):
    src = Path(src); root = Path(work); root.mkdir(parents=True, exist_ok=True)
    segs = transcribe(src, root, log)
    work = root / version if version else root; work.mkdir(parents=True, exist_ok=True)
    bf = root / "broll.json"   # probing every clip in the folder is slow on a busy PC: once per folder
    broll = json.loads(bf.read_text(encoding="utf-8")) if bf.exists() else broll_list(src)
    bf.write_text(json.dumps(broll, indent=1), encoding="utf-8")
    pl = plan(cfg, segs, context, broll, work, log, notes=notes)
    bdir = src.parent
    from . import shots
    an = shots.analyze(src, root, flip, log)
    bfiles = [x for x in sorted(bdir.iterdir()) if x.stem in broll and x.suffix.lower() in VIDEO_EXT]
    nice = next((x for x in bfiles if "bay" in x.stem.lower() or "wave" in x.stem.lower()), bfiles[0] if bfiles else None)
    card_bg = (nice, 2.0, False, shots.orient(nice, root, log)) if nice else (src, 30.0, flip, "")
    outs = {}
    for kind in kinds:
        sp = short_plan(cfg, segs, pl, context, notes, work, log) if kind == "short" and cfg.get("interview_short_pass", True) else None
        items = (_items(sp) if sp else _items(pl.get("short") or {})) if kind == "short" else [x for c in pl["documentary"]["chapters"] for x in c.get("items", [])]
        import hashlib   # cuts are cached per plan: a changed plan never reuses another plan's numbered parts
        kd = work / f"{kind}_{hashlib.md5((CUT_VERSION + json.dumps(items, sort_keys=True)).encode()).hexdigest()[:6]}"; kd.mkdir(exist_ok=True)
        parts, rnd = [], random.Random(7)
        from . import tts
        batch = [(it["narr"], kd / "narr" / f"n{k}.wav") for k, it in enumerate(items) if it.get("narr")] + \
                [(it["insert"], kd / "narr" / f"i{k}.wav") for k, it in enumerate(items) if it.get("insert")]
        if batch:   # all of this video's narration in one Kokoro run (each separate run costs ~2 min of start-up)
            (kd / "narr").mkdir(exist_ok=True); tts.kokoro_batch(cfg, batch, log, f"interview narration ({kind})")
        used = [(segs[int(x["bite"][0])]["start"], segs[int(x["bite"][1])]["end"]) for x in items if "bite" in x]
        cuts = Cutaways(src, an, used, bfiles, root, flip, log)
        hk = hook(cfg, segs, context, kind, work, log) if cfg.get("interview_hook", True) and not (kind == "short" and sp) else None
        if kind == "short" and sp and items and "bite" in items[0]:   # the Short's own opener is its cold open: hook text from its thread
            items[0] = dict(items[0], hook_text=str(sp.get("hook") or "")[:48])
        if hk:   # cold open: the most striking line, with the hook text on screen, before the story starts
            f = cut_bite_framed(src, hk["t0"], hk["t1"], kd / "hook.mp4", kind, flip, an, cuts, log)
            parts.append({"file": f, "words": [(w, s - hk["t0"], e - hk["t0"]) for w, s, e in hk["words"]], "style": "Cap", "hook": hk["text"]})
        if hk or not (kind == "short" and sp):   # title card: what this is, before the story (the Short's comes after its opener)
            tt = kd / "title.mp4"
            if not media.ok(tt, 0.5): card_part(card_bg, 3.2, tt, kind)
            parts.append({"file": tt, "words": [], "titles": [(pl.get("title", name), "Title", -50), ("A conversation in Bermuda", "Sub", 90)]})
        for k, it in enumerate(items):
            if "bite" in it:
                a, b = int(it["bite"][0]), int(it["bite"][1])
                t0 = max(0.0, segs[a]["start"] - 0.15); t1 = segs[b]["end"] + 0.3
                f = cut_bite_framed(src, t0, t1, kd / f"{k:02}_bite.mp4", kind, flip, an, cuts, log)
                words = [(wd, s - t0, e - t0) for x in segs[a:b + 1] for wd, s, e in x["words"]]
                parts.append({"file": f, "words": words, "style": "Cap", "hook": it.get("hook_text", "")})
                if it.get("hook_text"):   # the title card goes right after the opener
                    tt = kd / "title.mp4"
                    if not media.ok(tt, 0.5): card_part(card_bg, 3.2, tt, kind)
                    parts.append({"file": tt, "words": [], "titles": [(pl.get("title", name), "Title", -50), ("A conversation in Bermuda", "Sub", 90)]})
                _log(log, f"  {kind} {k:02}: soundbite {t0:.0f}-{t1:.0f}s \"{segs[a]['text'][:60]}\"")
            elif it.get("narr"):
                br = str(it.get("broll") or "")
                if br in broll:
                    bf = next((x for x in bdir.iterdir() if x.stem == br and x.suffix.lower() in VIDEO_EXT), None)
                    pic = (bf, rnd.uniform(0, max(0.0, broll[br] - 8)), False, shots.orient(bf, root, log))   # back camera: not mirrored
                else:   # the guest elsewhere in the video (framed on him), muted
                    f_, st_, fl_, g_, rot_ = cuts.take(8)
                    pic = (f_, st_, fl_, rot_, g_)
                f = cut_bridge(cfg, it["narr"], pic, kd / f"{k:02}_narr.mp4", kind, kd, k, log)
                from . import captions
                try: words = captions.word_times(kd / "narr" / f"n{k}.wav", it["narr"])
                except Exception: words = []
                parts.append({"file": f, "words": words, "style": "Narr"})
                _log(log, f"  {kind} {k:02}: narration \"{it['narr'][:60]}\"" + (f" over {br}" if br in broll else ""))
            elif it.get("insert"):   # a context tidbit: narration over a Commons photo (credited), else over your footage
                from . import tts, captions
                wav = kd / "narr" / f"i{k}.wav"; wav.parent.mkdir(exist_ok=True)
                tts.kokoro_batch(cfg, [(it["insert"], wav)], log, "interview context")
                f = kd / f"{k:02}_insert.mp4"; credit = ""
                try: had = json.loads((kd / f"{k:02}_insert.json").read_text(encoding="utf-8")).get("credit", "")
                except Exception: had = None
                if media.ok(f, 0.5) and had == "": f.unlink(missing_ok=True)   # made without a photo last time: try Commons again
                if not media.ok(f, 0.5):
                    img, credit = commons_photo(str(it.get("visual") or it["insert"])[:80], kd / f"{k:02}_photo.jpg", log, cfg=cfg, line=it["insert"])
                    if img: still_part(img, wav, f, kind)
                    else:
                        nxt = next((x for x in items[k + 1:] if "bite" in x), None)
                        st = segs[int(nxt["bite"][0])]["start"] if nxt else segs[-1]["start"]
                        d = media.dur(wav) + 0.35
                        media.ff("-ss", f"{st:.2f}", "-i", src, "-i", wav, "-t", f"{d:.2f}", "-map", "0:v:0", "-map", "1:a:0",
                                 "-vf", _vf(kind, None, 1.0, flip) + ",boxblur=12", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11,apad", *ENC, "-shortest", f, timeout=900)
                    (kd / f"{k:02}_insert.json").write_text(json.dumps({"credit": credit}), encoding="utf-8")
                else:
                    try: credit = json.loads((kd / f"{k:02}_insert.json").read_text(encoding="utf-8")).get("credit", "")
                    except Exception: credit = ""
                try: words = captions.word_times(wav, it["insert"])
                except Exception: words = []
                note = (notes or [{}] * 99)[int(it.get("note", 0))] if notes and str(it.get("note", "")).isdigit() and int(it["note"]) < len(notes) else {}
                parts.append({"file": f, "words": words, "style": "Narr", "credit": credit, "card": str(it.get("card") or "")[:48],
                              "source": note.get("source", "")})
                _log(log, f"  {kind} {k:02}: context \"{it['insert'][:60]}\"" + (f" [{credit}]" if credit else " (over blurred footage)"))
        ec = kd / "end.mp4"   # end card: thanks + subscribe, music carries it out
        if not media.ok(ec, 0.5): card_part(card_bg, 6.0 if kind == "documentary" else 4.0, ec, kind)
        parts.append({"file": ec, "words": [], "titles": [("Thank you, Mr. Clinton", "Title", -90), ("and the Islamic Center of Bermuda", "Sub", 20),
                                                          ("Subscribe for more journeys", "Sub", 120)]})
        outs[kind] = assemble(parts, work / f"{name}_{kind}.mp4", kind, kd, cfg, log, pl.get("title", name))
    srcs = sorted({n.get("source", "") for n in (notes or []) if n.get("source")})
    (work / "sources.txt").write_text("Sources for the context notes:\n" + "\n".join(srcs), encoding="utf-8")
    (work / "result.json").write_text(json.dumps({k: str(v) for k, v in outs.items()} | {"title": pl.get("title", ""), "sources": srcs}, indent=1), encoding="utf-8")
    return outs
