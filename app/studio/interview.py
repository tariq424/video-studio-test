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
CUT_VERSION = "18"   # bump when the way parts are cut changes, so cached parts are made again
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
_GPU_BAD = False
def cfg_gpu_ok():
    """GPU whisper only when the CUDA BLAS library is present (else ctranslate2 fails, and a retry hangs)."""
    import ctypes.util, os
    if os.name != "nt": return True
    return any(os.path.exists(os.path.join(d, "cublas64_12.dll")) for d in os.environ.get("PATH", "").split(os.pathsep) if d)


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
    global _GPU_BAD
    # a second CUDA attempt after a failed one (missing cublas) hangs forever, so try the GPU once per process
    if not _GPU_BAD and cfg_gpu_ok():
        try: segs = run(WhisperModel("large-v3-turbo", device="cuda", compute_type="float16"), "GPU")
        except Exception as e:
            _GPU_BAD = True
            _log(log, f"  GPU transcription unavailable ({str(e)[:80]}); CPU")
            segs = run(WhisperModel("small.en", device="cpu", compute_type="int8"), "CPU")
    else:
        try: segs = run(WhisperModel("small.en", device="cpu", compute_type="int8"), "CPU")
        except RuntimeError as e:   # the PC short of memory for a moment (the vision model / a news render): wait, try once more
            if "alloc" not in str(e): raise
            _log(log, "  transcription ran out of memory; waiting 2 min and trying again"); time.sleep(120)
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


SHORT = """Cut a YouTube Short of about {short_secs} seconds (at least {short_secs} minus 30) from a mini-documentary's material.
The interview audio leads.
About the footage: {context}
The documentary's soundbites (segment numbers with their words) and context notes:
{material}
Rules: tell ONE story with a beginning, middle and end that a tourist would want to watch. It MUST touch each of these topics,
using his own words about them where he talks about them: {topics}. Open with the most gripping soundbite (under 20 seconds);
then 6-10 more soundbites (each 5-20 seconds; a sub-range of a soundbite's segments is fine), joined by up to five one-sentence
narration lines that carry the story forward; up to THREE context inserts from the notes (only what the note says);
END ON A SOUNDBITE that lands the story. No small talk, no logistics, nothing off-thread.
Narration only connects: it never states anything that is not in the transcript or the notes, never links two facts that the
sources don't link (e.g. do not claim the mosque stands on land that was taken), and attributes the speaker's claims to him
("Mr. Clinton says ...", "as he tells it ...") instead of stating them as fact.
Also write "hook": an on-screen line for the opening soundbite, under 45 characters, true to the story.
Reply with JSON only: {{"hook": "...", "items": [{{"bite": [first, last]}} | {{"narr": "...", "broll": ""}} | {{"insert": "...", "note": n, "visual": "...", "card": "..."}}]}}"""


def short_plan(cfg, segs, pl, context, notes, work, log=print, short_secs=90, tri=None):
    """The Short, cut from the documentary's chosen material (a separate pass: one plan for both came out weak). Cached."""
    import hashlib
    topics = ", ".join(cfg.get("interview_short_topics") or []) or "(the strongest thread)"
    out = Path(work) / f"short_plan_{hashlib.md5((SHORT + topics + str(short_secs) + str(bool(tri))).encode()).hexdigest()[:6]}.json"   # a changed brief makes a new plan
    if cfg.get("interview_short_file") and Path(cfg["interview_short_file"]).exists():   # a Short plan written by hand
        return json.loads(Path(cfg["interview_short_file"]).read_text(encoding="utf-8"))
    if out.exists():
        j = json.loads(out.read_text(encoding="utf-8")); j["items"] = end_on_bite(_items(j)); return j
    from .llm import LLM
    if tri:   # everything the documentary keeps, from every clip (the drive, the third floor, the kebab window)
        bites = [tuple(it["bite"]) for it in augment_items(tri, segs) if "bite" in it]
    else:
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
                                   SHORT.format(short_secs=short_secs, context=context, material=mat[:60000], topics=topics), max_tokens=1500, check=check)
            except RuntimeError:   # still too long after 3 tries: take its story and trim it to size
                j = llm.chat_json("You are a YouTube Shorts editor. Reply with JSON only.",
                                  SHORT.format(short_secs=short_secs, context=context, material=mat[:60000], topics=topics), max_tokens=1500,
                                  check=lambda x: check(x, False))
        j = fit({"short": j, "documentary": {"chapters": []}}, segs, short_secs, bite_max_short=22)["short"]
        j["items"] = end_on_bite(_items(j))
    except Exception as e:
        _log(log, f"  short plan: kept the combined plan's Short ({str(e)[:100]})"); return None
    out.write_text(json.dumps(j, indent=1, ensure_ascii=False), encoding="utf-8")
    return j


TRIAGE = """You edit a documentary from the creator's OWN footage of a conversation. The guest's own telling is the backbone:
keep his narrative, in its original order, and AUGMENT it. The creator (the man holding the camera, asking questions) is a
visitor and not the subject.

About the footage (from the creator): {context}

Transcript, numbered segments with times (seconds):
{segments}

Research notes (checked facts with sources; the ONLY facts you may add):
{notes}

Mark up the WHOLE conversation. Reply with JSON only:
{{
 "title": "a YouTube title, under 70 characters, honest, no clickbait",
 "drop": [[first_seg, last_seg, "why"], ...],
 "facts": [{{"after": seg, "note": n, "text": "1-2 sentences, only what note n says", "visual": "what a photo for it should show, 3-8 words", "card": "on-screen fact under 40 characters"}}],
 "jokes": [{{"after": seg, "text": "one light, warm line"}}],
 "chapters": [{{"at": seg, "title": "2-5 words"}}],
 "pictures": [{{"from": seg, "to": seg, "visual": "the photographable thing he is talking about, 3-8 words, e.g. 'Tucker's Town Bermuda', 'St. George's Bermuda harbour', or empty"}}]
}}
Rules:
- drop ONLY what is boring or repetitive: small talk, directions and logistics, dead air, the same point said again, chatter about
  the drive, anything private (addresses, phone numbers, money of private people). Everything else stays, however long the video gets.
- facts: where he mentions something a viewer would want explained (a place, a law, a date, a group, a number), or in place of a
  dropped stretch. "after" = the segment after which his talk pauses for the fact (it must end a sentence); he picks up again at
  the next segment. Use most notes once; never two facts in a row; at most one fact per ~90 seconds of his talk.
  A fact must be about what he is talking about in the 3 segments before "after" - the same place, person or event he names
  there. Never put a fact about one place where he talks about another (e.g. Horseshoe Bay is not Tucker's Town); if no note
  fits what he is saying at a pause, put no fact there.
- jokes: at most 3, only in relaxed moments (the drive, food, sports, the weather), gentle and at our own expense; NEVER near
  slavery, race, land losses, poverty or religion.
- chapters: 4-8, at the segment where a new topic starts; the first at segment 0.
- pictures: cover every kept stretch with what he is talking about (one entry per topic stretch); empty when it's personal talk.
- Never put words in anyone's mouth; never invent facts."""


def triage(cfg, segs, context, notes, work, log=print):
    """The augment plan for the documentary (owner, 2026-10-24): keep the guest's narrative in order, drop only boring or repeated
    stretches, pause him for facts at natural breaks, a few light jokes in relaxed moments. Cached in triage.json."""
    out = Path(work) / "triage.json"
    if cfg.get("interview_triage_file") and Path(cfg["interview_triage_file"]).exists():   # an edit plan written by hand
        return json.loads(Path(cfg["interview_triage_file"]).read_text(encoding="utf-8"))
    if out.exists(): return json.loads(out.read_text(encoding="utf-8"))
    n = len(segs)
    lines = "\n".join((f"--- next clip of the same afternoon (clip {x['src']}) ---\n" if k and x.get("src", 0) != segs[k - 1].get("src", 0) else "")
                      + f"[{x['i']}] {x['start']:.0f}-{x['end']:.0f}: {x['text']}" for k, x in enumerate(segs))
    span = lambda a, b: sum(x["end"] - x["start"] for x in segs[a:b + 1])   # clips restart at 0 s: sum segments, never end - start
    total = span(0, n - 1)
    def check(j):
        for d in j.get("drop") or []:
            if int(d[1]) >= n and int(d[0]) < n: d[1] = n - 1                # a range running past the end: clamp, don't refuse
            if not (0 <= int(d[0]) <= int(d[1]) < n): raise ValueError(f"drop {d[:2]} is outside 0-{n - 1}")
        for f in (j.get("facts") or []) + (j.get("jokes") or []):
            if not 0 <= int(f.get("after", -1)) < n: raise ValueError(f"'after' {f.get('after')} is outside 0-{n - 1}")
            if not str(f.get("text") or "").strip(): raise ValueError("every fact / joke needs text")
        for f in j.get("facts") or []:
            if notes and not (str(f.get("note", "")).isdigit() and int(f["note"]) < len(notes)): raise ValueError(f"fact note {f.get('note')} isn't a note number")
        if not j.get("chapters"): raise ValueError("chapters are needed")
        dropped = sum(span(int(d[0]), int(d[1])) for d in j.get("drop") or [])
        if dropped > 0.6 * total: raise ValueError(f"{dropped / 60:.0f} min dropped; drop only boring or repeated stretches")
    _log(log, f"Interview: marking up all {n} segments (keep / drop / facts / jokes; script AI)")
    from .llm import LLM
    with LLM(dict(cfg), log, lambda: False) as llm:
        j = llm.chat_json("You are an award-winning documentary editor. Reply with JSON only.",
                          TRIAGE.format(context=context, segments=lines[:140000],
                                        notes="\n".join(f"[{i}] {x['fact']}" for i, x in enumerate(notes or [])) or "(none)"),
                          max_tokens=6000, check=check)
    out.write_text(json.dumps(j, indent=1, ensure_ascii=False), encoding="utf-8")
    dropped = sum(span(int(d[0]), int(d[1])) for d in j.get("drop") or [])
    _log(log, f"  triage: {len(j.get('drop') or [])} stretch(es) dropped ({dropped / 60:.1f} min), {len(j.get('facts') or [])} fact(s), "
              f"{len(j.get('jokes') or [])} joke(s), {len(j.get('chapters') or [])} chapter(s)")
    return j


def _cut_points(segs, a, b):
    """Audio in/out for segments a..b: halfway into the pauses around them, so pieces of one stretch join without repeats."""
    same = lambda i, j: segs[i].get("src", 0) == segs[j].get("src", 0)
    t0 = segs[a]["start"] - 0.15 if a == 0 or not same(a, a - 1) else max(segs[a]["start"] - 0.4, (segs[a - 1]["end"] + segs[a]["start"]) / 2)
    t1 = segs[b]["end"] + 0.3 if b == len(segs) - 1 or not same(b, b + 1) else min(segs[b]["end"] + 0.4, (segs[b]["end"] + segs[b + 1]["start"]) / 2)
    return max(0.0, t0), t1


def augment_items(tri, segs, max_bite=45.0):
    """Triage -> items in the guest's order: his talk (bites, split at facts / jokes / chapters and every ~max_bite s so each
    gets its own picture), the facts and jokes at their pauses, dropped stretches gone."""
    n = len(segs)
    ends = lambda i: 0 <= i < n and segs[i]["text"].rstrip()[-1:] in ".?!"
    drop = set()
    for d in tri.get("drop") or []:   # never cut him off mid-sentence: a drop starts after a finished sentence and ends at one
        a, b = int(d[0]), int(d[1])
        if tri.get("exact"): drop.update(range(a, b + 1)); continue   # a hand-written plan: its drops as written
        for _ in range(3):
            if a <= b and a > 0 and not ends(a - 1): a += 1
        for _ in range(3):
            if b >= a and not ends(b): b -= 1
        if a <= b: drop.update(range(a, b + 1))
    def at_end(i):   # a fact / joke waits for the end of his sentence
        for j in range(i, min(n, i + 4)):
            if ends(j): return j
        return i
    after = {}
    for f in tri.get("facts") or []: after.setdefault(at_end(int(f["after"])), []).append(dict(insert=f["text"], note=f.get("note"), visual=f.get("visual", ""), card=f.get("card", "")))
    for f in tri.get("jokes") or []: after.setdefault(at_end(int(f["after"])), []).append(dict(narr=f["text"], broll="", joke=True))
    chap = {int(c["at"]): str(c.get("title") or "")[:40] for c in tri.get("chapters") or [] if 0 <= int(c.get("at", -1)) < n}
    pics = [(int(p.get("from", 0)), int(p.get("to", 0)), str(p.get("visual") or "")) for p in tri.get("pictures") or []]
    def visual(a, b): return next((v for f, t, v in pics if v and f <= b and t >= a), "")
    items, cur, pend_chap = [], None, ""
    def flush():
        nonlocal cur
        if cur:
            it = {"bite": [cur[0], cur[1]], "visual": visual(cur[0], cur[1])}
            if cur[2]: it["chapter"] = cur[2]
            items.append(it); cur = None
    for i in range(n):
        if i in chap:
            flush(); pend_chap = chap[i]
        if cur and segs[i].get("src", 0) != segs[cur[0]].get("src", 0): flush()   # a new clip starts a new piece
        if i in drop:
            flush()
        else:
            if cur and segs[i]["end"] - segs[cur[0]]["start"] > max_bite and segs[i - 1]["text"].rstrip()[-1:] in ".?!": flush()
            if cur is None: cur = [i, i, pend_chap]; pend_chap = ""
            else: cur[1] = i
        if i in after:
            flush()
            for x in after[i]:
                if not tri.get("exact") and items and ("insert" in x or "narr" in x) and ("insert" in items[-1] or "narr" in items[-1]): continue   # never two in a row
                items.append(x)
    flush()
    return items


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


ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-profile:v", "high", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]


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


class TripFootage:
    """Your other trip clips and photos, from the catalogue (scripts/label_media.py catalog: place from GPS, what is seen, what
    is said). Used under his voice where the picture is bad (owner, 2026-10-24: "use my other Bermuda videos to replace blur"):
      place    - only clips GPS puts at a place he names (St. George's, Hamilton, Dockyard...)
      subject  - clips showing the kind of thing he talks about (houses, harbour, church, school, field...)
      scenery  - neutral Bermuda scenery (water, beach, street, sky) for stretches that name no place
    Never: face close-ups, shaky / dark clips, airport / plane / hotel-room clips; each stretch of a clip is used once."""
    SCENIC = {"beach", "ocean", "sea", "water", "harbour", "harbor", "bay", "coast", "coastline", "sunset", "sky", "boat", "boats",
              "landscape", "street", "road", "houses", "house", "town", "view", "island", "palm", "trees", "garden", "cliff", "lighthouse"}
    SKIP = {"airplane", "airport", "plane", "aircraft", "cabin", "seat", "hotel room", "bed", "bathroom", "screenshot", "phone", "menu",
            "selfie", "receipt", "document", "screen", "hotel", "guest room", "ironing", "couch", "sofa", "bedroom", "dimly lit",
            "traveller", "traveler", "tourist", "television", "tv ", "monitor", "laptop"}   # (the catalogue calls the person filming "the traveller": that is you)
    STOP = set("the a an and or of in on at to for with from by is are was were this that these those it its he she they them his her their "
               "what who where when how very just like yeah okay oh so but not no yes there here have has had be been do does did will "
               "would can could about over into up down out all some many more most also bermuda".split())

    def __init__(self, catalog_dir, exclude=(), root=None, log=print, near=None, radius_km=2.0):
        self.log, self.root, self.recs, self.pos = log, root, [], {}
        self.near, self.radius = near, radius_km
        ex = {str(Path(x)).lower() for x in exclude}
        lens = {round(float(x[1]), 1) for x in exclude if isinstance(x, tuple)}
        for f in sorted(Path(catalog_dir).glob("*.json")) if catalog_dir and Path(catalog_dir).is_dir() else []:
            try: r = json.loads(f.read_text(encoding="utf-8"))
            except Exception: continue
            p = Path(r.get("original", ""))
            if str(p).lower() in ex or not p.exists() or "vision failed" in str(r.get("description", "")): continue
            words = (str(r.get("subject", "")) + " " + str(r.get("description", ""))).lower()   # (tags echo the prompt's examples: not used)
            if r.get("face_closeup") or str(r.get("quality", "good")) in ("shaky", "dark", "blurry") or str(r.get("people", "")) == "one": continue
            if any(k in words for k in self.SKIP): continue
            vid = p.suffix.lower() in VIDEO_EXT
            if vid and float(r.get("seconds") or 0) < 3: continue
            hm = re.search(r"T(\d\d):", str(r.get("taken", "")))
            if hm and not 6 <= int(hm.group(1)) < 20: continue   # night clips (a hotel TV passed for "aerial view") don't fit a daytime story
            r["_vid"], r["_words"] = vid, set(re.findall(r"[a-z]{3,}", words)) - self.STOP
            r["_where"] = " ".join(str(r.get(k, "")) for k in ("place", "area", "address")).lower()
            r["_near"] = True
            if near and r.get("lat") is not None:   # filmed in the area of the conversation (Hamilton), not Dockyard / a hotel lawn
                km = 6371 * math.hypot(math.radians(float(r["lat"]) - near[0]), math.radians(float(r["lon"]) - near[1]) * math.cos(math.radians(near[0])))
                r["_near"] = km <= radius_km
            elif near: r["_near"] = False   # no GPS: can't tell where it was filmed
            self.recs.append(r)
        _log(log, f"  trip footage: {len(self.recs)} usable clip(s) / photo(s) from the catalogue")

    def _places(self, text):
        out = set()
        for m in re.finditer(r"\b(St\.? George'?s?|Hamilton|Dockyard|Somerset|Sandys|Paget|Warwick|Southampton|Horseshoe Bay|Tucker'?s Town|"
                             r"Flatts|Smith'?s|Devonshire|Pembroke|Crystal Caves?|Elbow Beach|Coco Reef|North Village|Bernard'?s Park|Front Street)\b", text, re.I):
            out.add(re.sub(r"[^a-z ]", "", m.group(1).lower()).replace("st georges", "st george").replace("st george s", "st george").strip())
        return out

    def pick(self, visual, text, d, mode):
        want = set(re.findall(r"[a-z]{3,}", (visual + " " + text).lower())) - self.STOP
        places = self._places(visual + " " + text)
        best, bs = None, 0.0
        for r in self.recs:
            if r["_vid"]:
                used = self.pos.get(r["original"], 0.5)
                if float(r.get("seconds") or 0) - used < min(d, 4.0): continue
            elif self.pos.get(r["original"]): continue
            if mode == "place":
                if not places or not any(pl in r["_where"].replace("'", "").replace(".", "") for pl in places): continue
                sc = 3 + len(want & r["_words"])
            elif mode == "subject":
                if not r["_near"]: continue   # owner: "Dockyard is nowhere near Hamilton" - only footage from where he is talking
                sc = len(want & r["_words"])
                if sc < 2 or str(r.get("people", "")) not in ("none", ""): continue
            else:
                if not r["_near"] or str(r.get("people", "")) not in ("none", ""): continue   # scenery: from the area, nobody in it
                sc = len(r["_words"] & self.SCENIC)
                if sc < 2 or places: continue   # a named place he talks about never gets anonymous scenery as if it were it
            sc += 0.5 if r["_vid"] else 0
            if sc > bs: best, bs = r, sc
        if not best: return None
        f = Path(best["original"])
        if best["_vid"] and self.root:   # a clip that looks sideways can't be turned reliably (one came out upside down): not used
            from . import shots
            if shots.orient(f, self.root, self.log):
                self.recs = [r for r in self.recs if r is not best]
                return self.pick(visual, text, d, mode)
        if not self._faceless(f, best, d):   # someone's face in the stretch we'd use (you, family): never; try the next best
            self.recs = [r for r in self.recs if r is not best]
            return self.pick(visual, text, d, mode)
        self.last = best["original"]
        if best["_vid"]:
            st = self.pos.get(best["original"], 0.5); self.pos[best["original"]] = st + d + 0.5
        else:
            st = 0.0; self.pos[best["original"]] = 1
        return f, st, best

    def _faceless(self, f, r, d):
        """No face bigger than a passer-by (> 1% of the frame) in the part of the clip we'd use (5 frames) / the photo.
        The catalogue's people / close-up flags missed family selfies; this checks the pixels."""
        from . import shots
        cv2, np = shots._cv()
        if not cv2: return True
        tmp = Path(self.root or ".") / "_trip_face.jpg"
        try:
            if r["_vid"]:
                st = self.pos.get(r["original"], 0.5); fd = float(r.get("seconds") or 0)
                times = [min(max(0.0, fd - 0.2), st + d * k / 4) for k in range(5)]
            else:
                times = [None]
            for t in times:
                if t is None:
                    if f.suffix.lower() == ".heic":
                        import pillow_heif; from PIL import Image
                        pillow_heif.register_heif_opener(); Image.open(f).convert("RGB").save(tmp, quality=90)
                    else: tmp = f
                else:
                    media.ff("-ss", f"{t:.2f}", "-i", f, "-frames:v", 1, "-vf", "scale=640:-2", tmp, timeout=120)
                im = cv2.imread(str(tmp))
                if im is None: continue
                if im.shape[1] > 960: im = cv2.resize(im, (960, int(im.shape[0] * 960 / im.shape[1])))
                for rot in (None, cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_90_COUNTERCLOCKWISE):   # sideways clips too
                    im2 = im if rot is None else cv2.rotate(im, rot)
                    if any(x[2] * x[3] > 0.01 for x in shots._faces(cv2, cv2.cvtColor(im2, cv2.COLOR_BGR2GRAY), im2)):
                        _log(self.log, f"    trip clip {f.name} skipped: a face in it"); return False
            return True
        except Exception:
            return False

    def render(self, pick, d, out, kind):
        from . import shots
        f, st, r = pick
        W, H = (1080, 1920) if kind == "short" else (1920, 1080)
        if r["_vid"]:
            rot = ""
            fd = float(r.get("seconds") or 0)
            vf = (rot + "," if rot else "") + f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},fps=30,format=yuv420p,setsar=1"
            media.ff(*(["-stream_loop", "-1"] if fd - st < d else []), "-ss", f"{min(st, max(0.0, fd - 1)):.2f}", "-i", f, "-t", f"{d:.2f}", "-an", "-vf", vf, *ENC[:6], out, timeout=900)
        else:
            img = f
            if f.suffix.lower() == ".heic":
                try:
                    import pillow_heif; from PIL import Image
                    pillow_heif.register_heif_opener(); img = Path(out).with_suffix(".jpg"); Image.open(f).convert("RGB").save(img, quality=92)
                except Exception: return None
            still_clip(img, d, out, kind)
        return out


class Ladder:
    """The picture for a stretch where his story is good but the picture isn't (car ceiling, blank wall, the camera holder):
    his voice goes on and the picture comes from the ladder, wherever it lands neatly (owner, 2026-10-24):
      1. a Wikimedia Commons photo of what he is talking about (title must name the place and the thing; story-fit check)
      2. stock video (Pexels / Pixabay / Internet Archive) through the clip checker (Bermuda, the right kind of thing)
      3. his own footage of that moment, blurred
    Short stretches (< 4 s) go straight to the blur, so pictures don't flash by. (AI images / Marble scenes: not in this edit.)"""
    def __init__(self, cfg, src, flip, kd, kind, log=print, own=None, scenic=None, trip=None):
        self.cfg, self.src, self.flip, self.kd, self.kind, self.log = cfg, src, flip, Path(kd), kind, log
        self.trip = trip
        self.scenic = scenic   # (file, start, flip, rotation): the bay, blurred under a stretch where only the holder is in shot
        self.photos, self.stock, self.uses, self.stock_tries = {}, {}, {}, 0
        self.own, self.own_i, self.own_pos = list(own or []), 0, {}
        (self.kd / "ladder").mkdir(exist_ok=True)

    OWN_WORDS = re.compile(r"mosque|masjid|musallah|islamic|prayer|center|centre|imam|muslim", re.I)

    def _own(self, visual, d):
        """Your own footage of the place he's talking about (clips filmed within ~150 m of the interview, no one's face in
        them): the mosque's prayer hall, its hallways. Only for stretches about that place."""
        if not self.own or not self.OWN_WORDS.search(visual or ""): return None
        for _ in range(len(self.own)):
            f, dur, rot = self.own[self.own_i % len(self.own)]; self.own_i += 1
            st = self.own_pos.get(str(f), 0.5)
            if dur - st >= d: self.own_pos[str(f)] = st + d + 0.5; return f, st, rot
        return None

    def _photo(self, visual, text):
        if visual not in self.photos:
            img, credit = commons_photo(visual, self.kd / "ladder" / f"p{len(self.photos):02}.jpg", self.log, cfg=self.cfg, line=text[:300])
            self.photos[visual] = (img, credit)
        img, credit = self.photos[visual]
        if img and self.uses.get(str(img), 0) < 2: self.uses[str(img)] = self.uses.get(str(img), 0) + 1; return img, credit
        return None, ""

    def _stock(self, visual, text):
        if visual in self.stock: return self.stock[visual]
        self.stock[visual] = None
        if self.stock_tries >= int(self.cfg.get("interview_stock_max", 10)): return None
        self.stock_tries += 1
        try:
            from . import footage
            sid = f"s{len(self.stock):02}"
            got = footage.fill(self.cfg, [{"id": sid, "text": text[:300], "narration": text[:300], "queries": [visual, re.sub(r"\bBermuda\b", "", visual).strip() + " Bermuda"]}],
                               "portrait" if self.kind == "short" else "landscape", {sid: 1}, self.kd / "ladder" / "stock", self.log, lambda: False,
                               1920, 12, self.kd / "ladder" / f"stock_{sid}.json")
            c = (got.get(sid) or [None])[0]
            if c and "bermuda" not in (str(c.get("desc", "")) + " " + str(c.get("seen", ""))).lower():
                _log(self.log, f"    stock clip {c.get('id')} not used: nothing says it is Bermuda ({str(c.get('desc', ''))[:50]}); a mosque elsewhere would mislead")
                c = None
            f = self.kd / "ladder" / "stock" / "clips" / f"{c['id']}.mp4" if c else None
            self.stock[visual] = (f, f"{c.get('src', 'stock')}: {c.get('author', '')}".strip(": ")) if f and f.exists() else None
        except Exception as e:
            _log(self.log, f"    stock search failed ({str(e)[:80]})")
        return self.stock[visual]

    def trip_clip(self, visual, text, d, out, modes):
        """Your own trip footage for d seconds -> (out, how, credit) or None."""
        if not self.trip: return None
        for m in modes:
            pk = self.trip.pick(visual or "", text or "", d, m)
            if pk and self.trip.render(pk, d, out, self.kind):
                r = pk[2]
                return out, f"trip {m}", ""
        return None

    def picture(self, a, b, out, visual="", text="", why=""):
        """A silent video for a..b of the source -> (path, how, credit)."""
        from . import shots
        d = b - a
        if d >= 4 and visual:
            ow = self._own(visual, d)
            if ow:
                f, st, rot = ow
                W, H = (1080, 1920) if self.kind == "short" else (1920, 1080)   # fill the frame (a portrait clip in a wide video: no black bars)
                vf = (rot + "," if rot else "") + f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},fps=30,format=yuv420p,setsar=1"
                media.ff("-ss", f"{st:.2f}", "-i", f, "-t", f"{d:.2f}", "-an", "-vf", vf, *ENC[:6], out, timeout=900)
                return out, "own footage", ""
            got = self.trip_clip(visual, text, d, out, ("place",))
            if got: return got
            img, credit = self._photo(visual, text)
            if img:
                still_clip(img, d, out, self.kind); return out, "photo", credit
            got = self.trip_clip(visual, text, d, out, ("subject",))
            if got: return got
            st = self._stock(visual, text)
            if st:
                f, credit = st
                fd = media.dur(f)
                vf = shots.vf_frame(self.kind, None, 0.0, False, 1080 if self.kind == "short" else 1920, 1920 if self.kind == "short" else 1080)
                media.ff(*(["-stream_loop", "-1"] if fd < d else []), "-i", f, "-t", f"{d:.2f}", "-an", "-vf", vf, *ENC[:6], out, timeout=900)
                return out, "stock", credit
        if d >= 3:
            got = self.trip_clip(visual, text, d, out, ("scenery",))
            if got: return got
        if why == "self" and self.scenic:   # a blurred face is still a face: the holder's shots go under the blurred bay instead
            f, st, fl, rot = self.scenic
            vf = (rot + "," if rot else "") + shots.vf_frame(self.kind, None, 0.0, fl) + ",boxblur=20:2,eq=brightness=-0.1"
            media.ff("-stream_loop", "-1", "-ss", f"{st + (a * 1.3) % 20:.2f}", "-i", f, "-t", f"{d:.2f}", "-an", "-vf", vf, *ENC[:6], out, timeout=900)
            return out, "blurred bay", ""
        vf = shots.vf_frame(self.kind, None, 0.0, self.flip) + ",boxblur=24:2,eq=brightness=-0.06"
        media.ff("-ss", f"{a:.2f}", "-i", self.src, "-t", f"{d:.2f}", "-an", "-vf", vf, *ENC[:6], out, timeout=900)
        return out, "blur", ""


def gps_of(path):
    """(lat, lon) from an iPhone video's location tag, or None."""
    import subprocess
    try:
        j = json.loads(subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)], capture_output=True, text=True, timeout=30).stdout or "{}")
        m = re.match(r"([+-]\d+\.\d+)([+-]\d+\.\d+)", j.get("format", {}).get("tags", {}).get("com.apple.quicktime.location.ISO6709", ""))
        return (float(m[1]), float(m[2])) if m else None
    except Exception:
        return None


def own_clips(src, root, log=print, radius=150.0):
    """Your other clips filmed near the interview (GPS in the files: iPhone ISO6709), with no face in them (the prayer hall,
    hallways): [(file, seconds, rotation)]. Copies with the same length count once. Cached in own_clips.json."""
    cache = Path(root) / "own_clips.json"
    if cache.exists():
        try: return [(Path(f), d, r) for f, d, r in json.loads(cache.read_text(encoding="utf-8"))]
        except Exception: pass
    import subprocess
    def tags(p):
        try:
            j = json.loads(subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(p)], capture_output=True, text=True, timeout=30).stdout or "{}")
            fm = j.get("format", {}); t = fm.get("tags", {})
            m = re.match(r"([+-]\d+\.\d+)([+-]\d+\.\d+)", t.get("com.apple.quicktime.location.ISO6709", ""))
            return float(fm.get("duration") or 0), ((float(m[1]), float(m[2])) if m else None)
        except Exception: return 0.0, None
    _, here = tags(src)
    if not here: return []
    from . import shots
    cv2, np = shots._cv()
    out, seen = [], set()
    files = sorted([f for f in Path(src).parent.iterdir() if f.suffix.lower() in VIDEO_EXT and f.resolve() != Path(src).resolve()],
                   key=lambda f: (f.stem.upper().startswith("IMG_"), f.name))   # named copies first
    for f in files:
        d, ll = tags(f)
        if d < 4 or not ll or round(d, 1) in seen: continue
        if re.search(r"with[-_ ]", f.stem, re.I): seen.add(round(d, 1)); continue   # "...-with-clinton": a person's clip (and its IMG_ copy)
        dist = 6371000 * math.hypot(math.radians(ll[0] - here[0]), math.radians(ll[1] - here[1]) * math.cos(math.radians(here[0])))
        if dist > radius or d > 600: continue
        rot = shots.orient(f, root, log)
        faces = False
        if cv2:
            for k in range(8):   # nobody's face: the place, not people (and never the camera holder)
                tmp = Path(root) / "_own.jpg"
                media.ff("-ss", f"{d * (k + 1) / 9:.2f}", "-i", f, "-frames:v", 1, "-vf", (rot + "," if rot else "") + "scale=640:-2", tmp, timeout=120)
                im = cv2.imread(str(tmp))
                if im is not None and any(x[2] * x[3] > 0.004 for x in shots._faces(cv2, cv2.cvtColor(im, cv2.COLOR_BGR2GRAY), im)): faces = True; break
        if faces: continue
        seen.add(round(d, 1)); out.append((f, d, rot))
    cache.write_text(json.dumps([(str(f), d, r) for f, d, r in out], indent=1), encoding="utf-8")
    _log(log, f"  own footage near the interview (no faces): {', '.join(f'{f.stem} ({d:.0f}s)' for f, d, _ in out) or 'none'}")
    return out


def still_clip(img, d, out, kind):
    """A still with a slow push-in, silent, d seconds."""
    w, h = (1080, 1920) if kind == "short" else (1920, 1080); n = int(d * 30) + 1
    vf = (f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase,crop={w * 2}:{h * 2},"
          f"zoompan=z='min(zoom+0.0005,1.10)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={n}:s={w}x{h}:fps=30,format=yuv420p,setsar=1,"
          f"fade=t=in:st=0:d=0.3,fade=t=out:st={max(0.0, d - 0.3):.2f}:d=0.3")
    media.ff("-loop", 1, "-i", img, "-t", f"{d:.2f}", "-an", "-vf", vf, *ENC[:6], out, timeout=900)
    return out


XFADE = 0.5   # seconds: picture changes inside his talk dissolve instead of cutting (owner, 2026-10-24: "transitions too fast")


def _snap(bounds, words, t0, t1, reach=1.2):
    """Move each picture change to the nearest pause between his words (within reach seconds), so the picture never
    changes in the middle of a word or phrase."""
    gaps = [(w1[2] + w2[1]) / 2 for w1, w2 in zip(words, words[1:]) if w2[1] - w1[2] >= 0.12]
    out, last = [], t0
    for b in bounds:
        near = [g for g in gaps if abs(g - b) <= reach and g - last >= 1.5 and t1 - g >= 1.5]
        nb = min(near, key=lambda g: abs(g - b)) if near else b
        if nb - last < 1.5 or t1 - nb < 1.5: continue   # too close to the previous change / the end: merge
        out.append(nb); last = nb
    return out


def cut_bite_framed(src, t0, t1, out, kind, flip, an, cuts, log=print, ladder=None, visual="", text="", credits=None, words=None,
                    soft_in=True, soft_out=True, keep=False, place=None):
    """A soundbite with its own audio and a framed picture: on the guest, level, covered where the picture is bad (the
    holder, a ceiling, a shirt close-up, the phone on its side). Picture changes sit in pauses and dissolve."""
    if media.ok(out, 0.5): return out
    from . import shots
    tmpd = Path(out).with_suffix(""); tmpd.mkdir(exist_ok=True)
    plan = shots.plan_keep(an, t0, t1, min_len=3.0) if keep else shots.plan_shots(an, t0, t1, min_len=3.0)
    if len(plan) > 1 and words:   # snap the changes to pauses
        nb = _snap([p[0] for p in plan[1:]], words, t0, t1)
        old = plan; plan = []
        edges = [t0] + nb + [t1]
        for a, b in zip(edges, edges[1:]):   # each new piece takes the kind of the old shot covering most of it
            best = max(old, key=lambda p: min(b, p[1]) - max(a, p[0]))
            plan.append((a, b, best[2], best[3], best[4]))
        merged = []
        for p in plan:   # neighbours of the same kind join
            if merged and merged[-1][2] == p[2] and merged[-1][3] == p[3]: merged[-1] = (merged[-1][0], p[1], p[2], p[3], p[4])
            else: merged.append(p)
        plan = merged
    segs, durs = [], []
    for n, (a, b, k, g, tilt) in enumerate(plan):
        v = tmpd / f"s{n:02}.mp4"; d = b - a
        ext = XFADE if n < len(plan) - 1 else 0.0   # each piece runs on under the dissolve into the next
        if keep and place and k == "none": k = "blur"   # a clip filmed mostly on the holder's neck (third floor): only shots of the guest stay
        if keep and k == "blur":   # the holder's close-up / a finger: the nearest clean moment of the SAME clip, else blurred
            cs = None if place else clean_start(an, a, b, d + ext, media.dur(src))   # (in a neck-filmed clip "clean" isn't)
            if cs is not None:
                media.ff("-ss", f"{cs:.2f}", "-i", src, "-t", f"{d + ext:.2f}", "-an", "-vf", shots.vf_frame(kind, None, 0.0, flip), *ENC[:10], v, timeout=900)
                _log(log, f"    {a:.0f}-{b:.0f}s: same scene from {cs:.0f}s (close-up / finger here)")
                segs.append(v); durs.append(d); continue
            if place:   # nothing clean nearby: the creator's own clip of the same place, same afternoon
                pf, pfl = place[int(a) % len(place)]
                pd = media.dur(pf); pst = (a * 7.3) % max(1.0, pd - d - ext - 1.0)
                prot = "" if pfl else shots.orient(pf, Path(out).parent.parent, log)
                media.ff("-ss", f"{pst:.2f}", "-i", pf, "-t", f"{d + ext:.2f}", "-an", "-vf", (prot + "," if prot else "") + shots.vf_frame(kind, None, 0.0, pfl),
                         *ENC[:10], v, timeout=900)
                _log(log, f"    {a:.0f}-{b:.0f}s: same place, {Path(pf).name} at {pst:.0f}s (close-up here, nothing clean nearby)")
                segs.append(v); durs.append(d); continue
        if keep:   # owner, 2026-10-25: his footage is never swapped - turned upright, blurred where not worth seeing sharp
            rot = int(k[4:]) if k.startswith("turn") else 0
            vf = shots.vf_frame(kind, g if k == "guest" else None, 0.0 if rot else tilt, flip, rot=rot, blur=(k == "blur"))
            media.ff("-ss", f"{a:.2f}", "-i", src, "-t", f"{d + ext:.2f}", "-an", "-vf", vf, *ENC[:10], v, timeout=900)
            if k != "none" and k != "guest": _log(log, f"    {a:.0f}-{b:.0f}s: {'turned upright (' + str(rot) + ' deg)' if rot else 'kept, blurred'}")
            segs.append(v); durs.append(d); continue
        if k == "guest" and not shots.holder_out(kind, g): k = "self"   # owner: "cut me out completely" - no crop can, so cut away
        if k in ("self", "empty") and ladder is not None:   # his voice goes on; the picture comes from the ladder
            _, how, credit = ladder.picture(a, b + ext, v, visual, text, why=k)
            if credits is not None: credits.append((a - t0, b - t0, how, credit))
            _log(log, f"    {a:.0f}-{b:.0f}s: {'holder in shot' if k == 'self' else 'ceiling / blank / unusable'} -> {how}" + (f" ({credit})" if credit else "")
                 + (f" [{Path(ladder.trip.last).name}]" if how.startswith("trip") and ladder.trip and getattr(ladder.trip, "last", None) else ""))
        elif k in ("self", "empty"):   # cutaway: the sound goes on, the picture shows the guest elsewhere / B-roll
            f, st, fl, gb, rot = cuts.take(d + ext)
            vf = (rot + "," if rot else "") + shots.vf_frame(kind, gb, 0.0, fl)
            media.ff("-ss", f"{st:.2f}", "-i", f, "-t", f"{d + ext:.2f}", "-an", "-vf", vf, *ENC[:10], v, timeout=900)
        else:
            media.ff("-ss", f"{a:.2f}", "-i", src, "-t", f"{d + ext:.2f}", "-an", "-vf", shots.vf_frame(kind, g, tilt, flip), *ENC[:10], v, timeout=900)
        segs.append(v); durs.append(d)
    T = t1 - t0
    edge = ",".join(([f"fade=t=in:st=0:d=0.3"] if soft_in else []) + ([f"fade=t=out:st={max(0.0, T - 0.3):.2f}:d=0.3"] if soft_out else [])) or "null"
    # (a soft start / end only where his talk meets a fact or a jump in time; two pieces of one continuous stretch join straight)
    if len(segs) == 1:
        vin = ["-i", segs[0]]; flt = ["-filter_complex", f"[0:v]{edge}[vo]"]; vmap = "[vo]"
    else:
        vin = [x for sg in segs for x in ("-i", sg)]
        chain, prev, off = [], "[0:v]", 0.0
        for i in range(1, len(segs)):
            off += durs[i - 1]
            lab = f"[x{i}]"
            chain.append(f"{prev}[{i}:v]xfade=transition=fade:duration={XFADE}:offset={off:.3f}{lab}")
            prev = lab
        chain.append(f"{prev}{edge}[vo]")
        flt = ["-filter_complex", ";".join(chain)]; vmap = "[vo]"
    n_in = len(segs)
    media.ff(*vin, "-ss", f"{t0:.2f}", "-i", src, *flt, "-t", f"{t1 - t0:.2f}", "-map", vmap, "-map", f"{n_in}:a:0",
             "-af", f"loudnorm=I=-16:TP=-1.5:LRA=11,afade=t=in:st=0:d=0.06,afade=t=out:st={max(0.0, t1 - t0 - 0.08):.2f}:d=0.08",
             *ENC, out, timeout=1800)
    return out


def clean_start(an, a, b, d, dur, reach=45.0):
    """Start of the nearest stretch of d seconds in the same clip (within reach) that is clean as filmed - no close-up of the
    camera holder, no finger, not on its side - outside a-b; None if there is none."""
    from . import shots
    by = {x["t"]: shots.kind_keep(x) for x in an.get("secs") or []}
    ok = lambda t0: t0 >= 0 and t0 + d <= dur - 0.2 and all(by.get(t, "none") in ("none", "guest") for t in range(int(t0), int(t0 + d) + 1))
    for step in range(0, int(reach) + 1):
        for t0 in (a - d - step, b + step):
            if ok(t0): return float(t0)
    return None


def scene_window(segs, items, k, d, durs):
    """Where a fact / joke pause takes its picture (owner, 2026-10-25: the real scene, never another place): the same clip
    near the pause, a stretch no soundbite shows (a dropped bit), else the seconds just before. -> (src index, start)."""
    prev = next((items[j]["bite"] for j in range(k - 1, -1, -1) if "bite" in items[j]), None)
    nxt = next((items[j]["bite"] for j in range(k + 1, len(items)) if "bite" in items[j]), None)
    anchor = int(prev[1]) if prev else int(nxt[0]) if nxt else 0
    si = segs[anchor].get("src", 0)
    t = segs[anchor]["end"] if prev else max(0.0, segs[anchor]["start"] - d)
    used = [(segs[int(it["bite"][0])]["start"], segs[int(it["bite"][1])]["end"]) for it in items
            if "bite" in it and segs[int(it["bite"][0])].get("src", 0) == si]
    free = lambda a: a >= 0 and a + d <= durs.get(si, 1e9) and not any(a < u1 and a + d > u0 for u0, u1 in used)
    for step in range(0, 46):
        for a in (t + 2 * step, t - d - 2 * step):
            if free(a): return si, a
    return si, max(0.0, (segs[anchor]["end"] if prev else segs[anchor]["start"]) - d)


def scene_part(src, flip, an, start, wav, out, kind, log=print):
    """Narration over the real scene (muted), turned upright / blurred like the soundbites."""
    d = media.dur(wav) + 0.35
    pic = Path(out).with_name(Path(out).stem + "_pic.mp4")
    cut_bite_framed(src, start, start + d, pic, kind, flip, an, None, log, keep=True)
    media.ff("-i", pic, "-i", wav, "-t", f"{d:.2f}", "-map", "0:v:0", "-map", "1:a:0",
             "-vf", f"fade=t=in:st=0:d=0.3,fade=t=out:st={d - 0.3:.2f}:d=0.3", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11,apad", *ENC, "-shortest", out, timeout=900)
    return out


def clip_part(clip, wav, out, kind, root, log=print, start=0.0, flip=False):
    """Narration over one of the creator's own clips of that exact place (named in the note), upright, back camera."""
    from . import shots
    d = media.dur(wav) + 0.35
    rot = "" if flip else shots.orient(clip, root, log)
    vf = (rot + "," if rot else "") + shots.vf_frame(kind, None, 0.0, flip) + f",fade=t=in:st=0:d=0.3,fade=t=out:st={d - 0.3:.2f}:d=0.3"
    loop = ["-stream_loop", "-1"] if media.dur(clip) < start + d else []
    media.ff(*loop, "-ss", f"{start:.2f}", "-i", clip, "-i", wav, "-t", f"{d:.2f}", "-map", "0:v:0", "-map", "1:a:0", "-vf", vf,
             "-af", "loudnorm=I=-16:TP=-1.5:LRA=11,apad", *ENC, "-shortest", out, timeout=900)
    return out


from .qc import qc_part, qc_final  # noqa: E402,F401  (the check lives in qc.py, shared with every video; _qc_frame left qc.py in v2+)


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
            if p.get("chapter"): ev.append(f"Dialogue: 1,{_t(t + 0.3)},{_t(t + min(3.5, d - 0.2))},Card,,0,0,0,,{{\\fad(250,250)}}{p['chapter']}\n")
            for a_, b_, c_ in p.get("credits") or []:
                ev.append(f"Dialogue: 1,{_t(t + a_)},{_t(t + min(b_, d))},Credit,,0,0,0,,{c_}\n")
            for txt, a, b in _caption_lines(p.get("words") or [], maxw):
                if a >= d: break
                ev.append(f"Dialogue: 0,{_t(t + a)},{_t(t + min(b + 0.15, d))},{p.get('style', 'Cap')},,0,0,0,,{{\\fad(80,60)}}{txt}\n")
            t += d
    ass = Path(work) / f"{kind}.ass"
    ass.write_text(ASS.format(w=w, h=h, fs=fs, ml=ml, mv=mv, cs=cs, ks=ks, hs=hs, hv=hv, ts=ts, ss=ss) + "".join(ev), encoding="utf-8")
    joined = Path(work) / f"_{kind}_joined.mp4"
    media.ff("-f", "concat", "-safe", 0, "-i", lst, "-c", "copy", joined, timeout=1800)
    sub = ass.as_posix().replace(":", "\\:")
    media.ff("-i", joined, "-vf", f"subtitles='{sub}'", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-profile:v", "high", "-movflags", "+faststart", "-c:a", "copy",
             "-movflags", "+faststart", out, timeout=7200)
    joined.unlink(missing_ok=True)
    try:
        from . import music
        if not _writable(out): raise RuntimeError(f"{Path(out).name} is open in another program (a player?); music not added")
        music.mix(out, dict(cfg, music_bed_db=float(cfg.get("interview_music_db", -5)), music_hook_db=float(cfg.get("interview_music_db", -5)),
                                music_duck_threshold=float(cfg.get("interview_duck_threshold", 0.08)), music_duck_ratio=float(cfg.get("interview_duck_ratio", 4))),
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


def build(cfg, src, work, context, log=print, kinds=("short", "documentary"), flip=True, name="interview", version="", notes=None, extras=None):
    src = Path(src); root = Path(work); root.mkdir(parents=True, exist_ok=True)
    segs = transcribe(src, root, log)
    main_segs = segs
    for x in segs: x.setdefault("src", 0)
    work = root / version if version else root; work.mkdir(parents=True, exist_ok=True)
    bf = root / "broll.json"   # probing every clip in the folder is slow on a busy PC: once per folder
    broll = json.loads(bf.read_text(encoding="utf-8")) if bf.exists() else broll_list(src)
    bf.write_text(json.dumps(broll, indent=1), encoding="utf-8")
    pl = plan(cfg, segs, context, broll, work, log, notes=notes)
    bdir = src.parent
    from . import shots
    shots.BACK_CAMERA["on"] = bool(cfg.get("interview_back_camera", False))   # back camera: big close faces are the guest, not the holder
    if shots.BACK_CAMERA["on"]: _log(log, "Interview: back-camera footage - every face on screen is the guest")
    an = shots.analyze(src, root, flip, log)
    if cfg.get("interview_vision_check", True): an = shots.vision_check(an, root, cfg, log)
    # more clips of the same conversation (owner, 2026-10-24: "use all the clips that can be used"): each transcribed and
    # framed on its own, then joined after the main one in the order they were filmed; segment numbers run on
    sources = [(src, flip, an)]
    before, after_ = [], []
    for k, ex in enumerate(extras or [], start=1):
        ep = Path(ex["src"] if isinstance(ex, dict) else ex); efl = bool(ex.get("flip", True)) if isinstance(ex, dict) else True
        ew = root / "extra" / ep.stem.rstrip("."); ew.mkdir(parents=True, exist_ok=True)
        es = transcribe(ep, ew, log)
        ean = shots.analyze(ep, ew, efl, log)
        if cfg.get("interview_vision_check", True): ean = shots.vision_check(ean, ew, cfg, log)
        sources.append((ep, efl, ean))
        (before if isinstance(ex, dict) and ex.get("before") else after_).append([dict(x, src=k) for x in es])
        _log(log, f"  clip {k}: {ep.name} ({len(es)} segments{', before the main clip' if isinstance(ex, dict) and ex.get('before') else ''})")
    if before or after_:   # filmed order: clips from before the main one first; numbers run on through all of them
        segs = [x for b in before for x in b] + segs + [x for a_ in after_ for x in a_]
        segs = [dict(x, i=j) for j, x in enumerate(segs)]
    bfiles = [x for x in sorted(bdir.iterdir()) if x.stem in broll and x.suffix.lower() in VIDEO_EXT]
    nice = next((x for x in bfiles if "bay" in x.stem.lower() or "wave" in x.stem.lower()), bfiles[0] if bfiles else None)
    keep = bool(cfg.get("interview_keep_scene", True))   # owner, 2026-10-25: never swap his footage for another place
    place = [(Path(x["src"]), bool(x.get("flip", False))) for x in cfg.get("interview_place_clips") or [] if Path(x["src"]).exists()]
    card_bg = (src, 30.0, flip, "") if keep or not nice else (nice, 2.0, False, shots.orient(nice, root, log))
    sdur = {i: media.dur(p_) for i, (p_, _, _) in enumerate(sources)}
    tri_all = triage(cfg, segs, context, notes, work, log) if cfg.get("interview_doc_mode", "augment") == "augment" else None
    if tri_all and cfg.get("interview_keep_srcs"):   # clips that are the visit itself (the kebab window): never dropped
        ks = set(int(x) for x in cfg["interview_keep_srcs"])
        tri_all = dict(tri_all, drop=[d_ for d_ in tri_all.get("drop") or [] if not any(segs[i].get("src", 0) in ks for i in range(int(d_[0]), int(d_[1]) + 1))])
    outs, trip = {}, None
    if cfg.get("interview_plan_only"):   # stop after the plans, for a look before hours of rendering
        sp_ = short_plan(cfg, segs, pl, context, notes, work, log, short_secs=int(cfg.get("interview_short_secs", 180)), tri=tri_all)
        rows = []
        for nm, its in (("documentary", augment_items(tri_all, segs) if tri_all else []), ("short", _items(sp_) if sp_ else [])):
            rows.append(f"===== {nm}")
            for it in its:
                if "bite" in it:
                    a_, b_ = int(it["bite"][0]), int(it["bite"][1])
                    rows.append(f"[clip {segs[a_].get('src', 0)} {segs[a_]['start']:.0f}-{segs[b_]['end']:.0f}s] " + " ".join(x["text"] for x in segs[a_:b_ + 1])[:300])
                else: rows.append("   >> " + json.dumps({k_: v_ for k_, v_ in it.items() if k_ in ("insert", "narr", "note", "card")}, ensure_ascii=False))
        (work / "plan_review.txt").write_text("\n".join(rows), encoding="utf-8")
        _log(log, f"plan only: {work / 'plan_review.txt'}"); return {"plan": str(work / "plan_review.txt")}
    for kind in kinds:
        sp = short_plan(cfg, segs, pl, context, notes, work, log, short_secs=int(cfg.get("interview_short_secs", 180)),
                        tri=tri_all) if kind == "short" and cfg.get("interview_short_pass", True) else None
        tri = tri_all if kind == "documentary" else None
        if tri: items = augment_items(tri, segs)
        else: items = (_items(sp) if sp else _items(pl.get("short") or {})) if kind == "short" else [x for c in pl["documentary"]["chapters"] for x in c.get("items", [])]
        vtitle = (tri or {}).get("title") or pl.get("title", name)
        import hashlib   # cuts are cached per plan: a changed plan never reuses another plan's numbered parts
        kd = work / f"{kind}_{hashlib.md5((CUT_VERSION + json.dumps(items, sort_keys=True)).encode()).hexdigest()[:6]}"; kd.mkdir(exist_ok=True)
        parts, rnd = [], random.Random(7)
        from . import tts
        batch = [(it["narr"], kd / "narr" / f"n{k}.wav") for k, it in enumerate(items) if it.get("narr")] + \
                [(it["insert"], kd / "narr" / f"i{k}.wav") for k, it in enumerate(items) if it.get("insert")]
        if batch:   # all of this video's narration in one Kokoro run (each separate run costs ~2 min of start-up)
            (kd / "narr").mkdir(exist_ok=True); tts.kokoro_batch(cfg, batch, log, f"interview narration ({kind})")
        used = [(segs[int(x["bite"][0])]["start"], segs[int(x["bite"][1])]["end"]) for x in items if "bite" in x and segs[int(x["bite"][0])].get("src", 0) == 0]
        cuts = Cutaways(src, an, used, bfiles, root, flip, log)
        oc = own_clips(src, root, log)
        if trip is None:
            trip = TripFootage(Path(src).parent / "labeled" / "catalog", [src] + [p_ for p_, _, _ in sources[1:]] + [f for f, _, _ in oc], root, log, near=gps_of(src),
                               radius_km=float(cfg.get("interview_trip_radius_km", 2.0))) if cfg.get("interview_trip_footage", True) else False
        ladder = Ladder(cfg, src, flip, kd, kind, log, own=oc, scenic=card_bg, trip=trip or None)
        hk = hook(cfg, main_segs, context, kind, work, log) if cfg.get("interview_hook", True) and not (kind == "short" and sp) else None
        if kind == "short" and sp and items and "bite" in items[0]:   # the Short's own opener is its cold open: hook text from its thread
            items[0] = dict(items[0], hook_text=str(sp.get("hook") or "")[:48])
        if hk:   # cold open: the most striking line, with the hook text on screen, before the story starts
            f = cut_bite_framed(src, hk["t0"], hk["t1"], kd / "hook.mp4", kind, flip, an, cuts, log, ladder=ladder, keep=keep)
            parts.append({"file": f, "words": [(w, s - hk["t0"], e - hk["t0"]) for w, s, e in hk["words"]], "style": "Cap", "hook": hk["text"],
                          "m": {"type": "bite", "src": str(src), "flip": flip, "si": 0, "t0": hk["t0"], "t1": hk["t1"], "text": hk.get("quote", "")}})
        if hk or not (kind == "short" and sp):   # title card: what this is, before the story (the Short's comes after its opener)
            tt = kd / "title.mp4"
            if not media.ok(tt, 0.5): card_part(card_bg, 3.2, tt, kind)
            parts.append({"file": tt, "words": [], "titles": [(vtitle, "Title", -50), ("A conversation in Bermuda", "Sub", 90)], "m": {"type": "card"}})
        for k, it in enumerate(items):
            if "bite" in it:
                a, b = int(it["bite"][0]), int(it["bite"][1])
                t0, t1 = _cut_points(segs, a, b) if tri else (max(0.0, segs[a]["start"] - 0.15), segs[b]["end"] + 0.3)
                said = " ".join(x["text"] for x in segs[a:b + 1])
                credits = []
                cj = kd / f"{k:02}_bite.json"
                if media.ok(kd / f"{k:02}_bite.mp4", 0.5) and cj.exists(): credits = json.loads(cj.read_text(encoding="utf-8"))
                bsrc, bflip, ban = sources[segs[a].get("src", 0)]
                ladder.src, ladder.flip = bsrc, bflip   # blur fallback from the clip being cut
                f = cut_bite_framed(bsrc, t0, t1, kd / f"{k:02}_bite.mp4", kind, bflip, ban, cuts, log, ladder=ladder,
                                    visual=str(it.get("visual") or ""), text=said, credits=credits,
                                    words=[w for x in segs[max(0, a - 1):b + 2] for w in x["words"]],
                                    soft_in=not (k > 0 and "bite" in items[k - 1] and int(items[k - 1]["bite"][1]) == a - 1),
                                    soft_out=not (k + 1 < len(items) and "bite" in items[k + 1] and int(items[k + 1]["bite"][0]) == b + 1), keep=keep,
                                    place=place if segs[a].get("src", 0) in set(int(x) for x in cfg.get("interview_place_srcs") or []) else None)
                cj.write_text(json.dumps(credits), encoding="utf-8")
                if cfg.get("interview_qc", False): qc_part(f, cfg, log, label=f"{kind} {k:02}", kind=kind)
                words = [(wd, s - t0, e - t0) for x in segs[a:b + 1] for wd, s, e in x["words"]]
                parts.append({"file": f, "words": words, "style": "Cap", "hook": it.get("hook_text", ""), "chapter": it.get("chapter", ""),
                              "credits": [(x[0], x[1], x[3]) for x in credits if x[3]],
                              "m": {"type": "bite", "src": str(bsrc), "flip": bflip, "si": segs[a].get("src", 0), "t0": t0, "t1": t1, "text": said}})
                if it.get("hook_text"):   # the title card goes right after the opener
                    tt = kd / "title.mp4"
                    if not media.ok(tt, 0.5): card_part(card_bg, 3.2, tt, kind)
                    parts.append({"file": tt, "words": [], "titles": [(vtitle, "Title", -50), ("A conversation in Bermuda", "Sub", 90)], "m": {"type": "card"}})
                _log(log, f"  {kind} {k:02}: soundbite {t0:.0f}-{t1:.0f}s \"{segs[a]['text'][:60]}\"")
            elif it.get("narr") and keep:   # a joke / bridge line over the real scene nearby, muted
                from . import captions
                wav = kd / "narr" / f"n{k}.wav"
                if not wav.exists(): tts.kokoro_batch(cfg, [(it["narr"], wav)], log, "interview narration")
                si, st = scene_window(segs, items, k, media.dur(wav) + 0.35, sdur)
                f = kd / f"{k:02}_narr.mp4"
                if not media.ok(f, 0.5): scene_part(sources[si][0], sources[si][1], sources[si][2], st, wav, f, kind, log)
                try: words = captions.word_times(wav, it["narr"])
                except Exception: words = []
                parts.append({"file": f, "words": words, "style": "Narr", "m": {"type": "narr", "text": it["narr"], "src": str(sources[si][0]),
                                                                                  "flip": sources[si][1], "si": si, "t0": st}})
                _log(log, f"  {kind} {k:02}: narration \"{it['narr'][:60]}\" over clip {si} at {st:.0f}s")
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
                if media.ok(f, 0.5) and had == "" and not keep: f.unlink(missing_ok=True)   # made without a photo last time: try Commons again
                note_ = (notes or [])[int(it["note"])] if notes and str(it.get("note", "")).isdigit() and int(it["note"]) < len(notes) else {}
                if keep and not media.ok(f, 0.5):   # owner, 2026-10-25: his own footage of that exact place, else the real scene here
                    clips = [Path(c) for c in (note_.get("clips") or []) if Path(c).exists()]
                    if clips:
                        c = clips[k % len(clips)]
                        if c.suffix.lower() in (".jpg", ".jpeg", ".png", ".heic", ".webp"): still_part(c, wav, f, kind)
                        else: clip_part(c, wav, f, kind, root, log, start=float(note_.get("clip_start", 0.0)), flip=bool(note_.get("clip_flip", False)))
                        credit = ""; _log(log, f"    fact over your clip {c.name}")
                    else:
                        si, st = scene_window(segs, items, k, media.dur(wav) + 0.35, sdur)
                        scene_part(sources[si][0], sources[si][1], sources[si][2], st, wav, f, kind, log)
                        _log(log, f"    fact over the scene: clip {si} at {st:.0f}s")
                    (kd / f"{k:02}_insert.json").write_text(json.dumps({"credit": ""}), encoding="utf-8")
                if not media.ok(f, 0.5) and cfg.get("interview_fact_ladder", False):   # owner, 2026-10-27: outside media through the QC repair ladder
                    try:
                        from . import qc_repair
                        d = media.dur(wav) + 0.35
                        clip, rung = qc_repair.ladder_clip(cfg, it["insert"], str(it.get("visual") or ""), d, kind, kd / "ladder" / f"{k:02}", root,
                                                           src=sources[0][0], log=log)
                        if clip:
                            media.ff("-i", clip, "-i", wav, "-t", f"{d:.2f}", "-map", "0:v:0", "-map", "1:a:0",
                                     "-vf", f"fade=t=in:st=0:d=0.3,fade=t=out:st={d - 0.3:.2f}:d=0.3", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11,apad",
                                     *ENC, "-shortest", f, timeout=900)
                            credit = ""; _log(log, f"    fact picture from the repair ladder: {rung}")
                            (kd / f"{k:02}_insert.json").write_text(json.dumps({"credit": "", "rung": rung}), encoding="utf-8")
                    except Exception as e:
                        if str(e) == "cancelled": raise
                        _log(log, f"    fact ladder skipped ({type(e).__name__}: {str(e)[:150]}); the usual photo / stock path")
                if not media.ok(f, 0.5):
                    img, credit = commons_photo(str(it.get("visual") or it["insert"])[:80], kd / f"{k:02}_photo.jpg", log, cfg=cfg, line=it["insert"])
                    st_ = None if img else ladder._stock(str(it.get("visual") or "")[:80], it["insert"]) if it.get("visual") else None
                    if img: still_part(img, wav, f, kind)
                    elif st_:   # stock video through the clip checker, under the fact
                        sf, credit = st_; d = media.dur(wav) + 0.35
                        media.ff(*(["-stream_loop", "-1"] if media.dur(sf) < d else []), "-i", sf, "-i", wav, "-t", f"{d:.2f}", "-map", "0:v:0", "-map", "1:a:0",
                                 "-vf", shots.vf_frame(kind, None, 0.0, False, 1080 if kind == "short" else 1920, 1920 if kind == "short" else 1080)
                                 + f",fade=t=in:st=0:d=0.3,fade=t=out:st={d - 0.3:.2f}:d=0.3",
                                 "-af", "loudnorm=I=-16:TP=-1.5:LRA=11,apad", *ENC, "-shortest", f, timeout=900)
                    elif ladder.trip_clip(str(it.get("visual") or ""), it["insert"], media.dur(wav) + 0.35, kd / f"{k:02}_insert_pic.mp4", ("place", "subject", "scenery")):
                        d = media.dur(wav) + 0.35   # your own trip footage under the fact
                        media.ff("-i", kd / f"{k:02}_insert_pic.mp4", "-i", wav, "-t", f"{d:.2f}", "-map", "0:v:0", "-map", "1:a:0",
                                 "-vf", f"fade=t=in:st=0:d=0.3,fade=t=out:st={d - 0.3:.2f}:d=0.3", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11,apad", *ENC, "-shortest", f, timeout=900)
                    else:   # no photo / clip: the scenic background (the bay), heavily blurred - never a person's face
                        bf_, bst_, bfl_, brot_ = card_bg
                        d = media.dur(wav) + 0.35
                        media.ff(*(["-stream_loop", "-1"] if media.dur(bf_) < bst_ + d else []), "-ss", f"{bst_ + (k * 3.7) % 20:.2f}", "-i", bf_, "-i", wav,
                                 "-t", f"{d:.2f}", "-map", "0:v:0", "-map", "1:a:0",
                                 "-vf", (brot_ + "," if brot_ else "") + shots.vf_frame(kind, None, 0.0, bfl_) + ",boxblur=20:2,eq=brightness=-0.1",
                                 "-af", "loudnorm=I=-16:TP=-1.5:LRA=11,apad", *ENC, "-shortest", f, timeout=900)
                    (kd / f"{k:02}_insert.json").write_text(json.dumps({"credit": credit}), encoding="utf-8")
                else:
                    try: credit = json.loads((kd / f"{k:02}_insert.json").read_text(encoding="utf-8")).get("credit", "")
                    except Exception: credit = ""
                try: words = captions.word_times(wav, it["insert"])
                except Exception: words = []
                note = (notes or [{}] * 99)[int(it.get("note", 0))] if notes and str(it.get("note", "")).isdigit() and int(it["note"]) < len(notes) else {}
                if cfg.get("interview_qc", False): qc_part(f, cfg, log, label=f"{kind} {k:02} fact", kind=kind)
                parts.append({"file": f, "words": words, "style": "Narr", "credit": credit, "card": str(it.get("card") or "")[:48],
                              "source": note.get("source", ""), "m": {"type": "fact", "text": it["insert"], "note": it.get("note")}})
                _log(log, f"  {kind} {k:02}: context \"{it['insert'][:60]}\"" + (f" [{credit}]" if credit else " (over blurred footage)"))
        ec = kd / "end.mp4"   # end card: thanks + subscribe, music carries it out
        if not media.ok(ec, 0.5): card_part(card_bg, 6.0 if kind == "documentary" else 4.0, ec, kind)
        parts.append({"file": ec, "words": [], "titles": [(str(cfg.get("interview_thanks") or "Thank you, Mr. Clinton"), "Title", -90), (str(cfg.get("interview_thanks_sub") or "and the Islamic Center of Bermuda"), "Sub", 20),
                                                          ("Subscribe for more journeys", "Sub", 120)], "m": {"type": "card"}})
        man = {"kind": kind, "out": str(work / f"{name}_{kind}.mp4"), "title": vtitle, "gps": gps_of(src), "parts": parts,
               "sources": [[str(p_), fl_, str(root if i_ == 0 else root / "extra" / Path(p_).stem.rstrip("."))] for i_, (p_, fl_, _a) in enumerate(sources)],
               "cfg": {k_: cfg[k_] for k_ in ("interview_music_db", "interview_duck_threshold", "interview_duck_ratio") if k_ in cfg}}
        (work / f"{name}_{kind}_parts.json").write_text(json.dumps(man, indent=1, ensure_ascii=False, default=str), encoding="utf-8")   # for the Video Studio editor
        if cfg.get("interview_manifest_only") and Path(man["out"]).exists():
            outs[kind] = Path(man["out"]); _log(log, f"  manifest written: {name}_{kind}_parts.json"); continue
        outs[kind] = assemble(parts, work / f"{name}_{kind}.mp4", kind, kd, cfg, log, vtitle)
        if cfg.get("interview_qc", False):
            try: qc_final(outs[kind], cfg, kd, log, every=30.0 if kind == "documentary" else 10.0)
            except Exception as e: _log(log, f"  final QC failed to run ({str(e)[:100]})")
    srcs = sorted({n.get("source", "") for n in (notes or []) if n.get("source")})
    (work / "sources.txt").write_text("Sources for the context notes:\n" + "\n".join(srcs), encoding="utf-8")
    (work / "result.json").write_text(json.dumps({k: str(v) for k, v in outs.items()} | {"title": pl.get("title", ""), "sources": srcs}, indent=1), encoding="utf-8")
    return outs
