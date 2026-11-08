"""People policy (owner, 2026-11-07): one rule for every rung that makes or picks a picture of a person.

- Nobody is anonymised. Real source footage of the people in the story is used as it is (commentary on a clip is normal on
  YouTube; the owner's call).
- A GENERATED picture of a real, named person is drawn as a courtroom sketch artist's drawing (charcoal and pastel, a different
  angle), never a photo-real look-alike: a photo-real stranger passed off as the person ("a man who bears no resemblance to
  him") is worse than no picture, and a sketch reads at once as an illustration.
- A describer never rebuilds the source's screen layout (split screens, video-call panels, lower thirds): that produced
  strangers in a fake talk-show frame. It describes one real scene.
- Animation of a picture with people moves the camera, never their mouths (a face mouthing words under the narration).
- Speaker insert: when a beat names a person and the source has a frame for that beat, the beat's other shots (map, graphic,
  stock, generated) carry that real frame as a small inset, so the viewer sees who is being talked about."""
import json, re
from pathlib import Path

# the STYLE of a courtroom sketch, never the place: the first run put a settler leader "in a courtroom setting"
SKETCH = ("a hand-drawn illustration in the style of a courtroom sketch artist (charcoal and soft pastel on cream paper, loose quick "
          "strokes, visible paper grain), seen from a different angle than any photo of them, not a photograph. Only the drawing "
          "style is borrowed: the scene is where the story happens, never a courtroom, judge or trial")

DESCRIBE_RULE = ("Describe people as they look (age, hair, clothing, expression, what they are doing); do not anonymise anyone. "
                 "Ignore the screen layout: no split screens, video-call panels, picture-in-picture boxes, lower thirds or studio "
                 "graphics - describe ONE real-world scene with the main person in it.")

ANIMATE = ("Animate this image with a slow cinematic camera move. People stay still with their mouths closed: no talking, no lip "
           "movement. Keep everything else exactly the same.")

# a description that rebuilds a TV / video-call layout instead of a scene
LAYOUT = re.compile(r"(?i)split[- ]?screen|video[- ]call|zoom call|\bpanels?\b|three[- ]panel|side[- ]by[- ]side|lower[- ]third|"
                    r"picture[- ]in[- ]picture|webcam|talk[- ]show (still|set|frame)|broadcast (still|frame)")
_OLD = re.compile(r"(?i)\s*No real or recogni[sz]able people\.?|\s*no real or recogni[sz]able people")


# a person in a description of a REAL frame (snapshot of the source / your footage): named or not, they are a real person
PERSON = re.compile(r"(?i)\b(wom[ae]n|m[ae]n|person|people|lady|ladies|gentleman|girl|boy|guest|host|interviewer|speaker|figure|face|"
                    r"portrait|elderly|grey-haired|gray-haired|she|he|her|his|they)\b")
SNAP_RULE = (f"If the image shows a person, they are a real person: draw them as {SKETCH}; never a photo-real look-alike.")


def shows_person(text):
    return bool(PERSON.search(str(text or "")))


def ents_for(sd):
    """The story's entity list for a job dir or its short/ workspace. -> [] when there is none."""
    sd = Path(sd)
    for f in (sd / "entities.json", sd.parent / "entities.json"):
        if f.is_file():
            try: return json.loads(f.read_text(encoding="utf-8")) or []
            except ValueError: return []
    return []


def names(text, ents):
    """Real people from the entity list that the text names (full name or surname). -> [name, ...] in entity order."""
    low = " " + re.sub(r"[^a-z0-9 ]+", " ", str(text or "").lower()) + " "
    out = []
    for e in ents or []:
        if e.get("kind") != "person": continue
        nm = str(e.get("name") or "").strip()
        parts = [w for w in re.sub(r"[^a-z0-9 ]+", " ", nm.lower()).split() if len(w) > 2]
        if parts and (f" {' '.join(parts)} " in low or f" {parts[-1]} " in low) and nm not in out: out.append(nm)
    return out


def with_people(sec, sd=None, ents=None):
    """sec with "people" set (the named real people of its narration). Never changes the caller's dict."""
    if "people" in sec: return sec
    ents = ents if ents is not None else (ents_for(sd) if sd else [])
    return dict(sec, people=names(sec.get("vo", ""), ents))


def rule(ppl):
    """The people line for a generator prompt."""
    return f"Show {', '.join(ppl)} as {SKETCH}." if ppl else ""


def tail(sec_or_people, photo=True):
    """What every text-to-image prompt ends with: the sketch rule for named people (or a real person seen in the source frame the
    prompt was described from), else photorealistic; never text/logos."""
    ppl = sec_or_people.get("people") if isinstance(sec_or_people, dict) else list(sec_or_people or [])
    if ppl: return " " + rule(ppl) + " No text, no logos."
    if isinstance(sec_or_people, dict) and sec_or_people.get("person_in_frame"):
        return f" Any person in it is drawn as {SKETCH}. No text, no logos."
    return (" Photorealistic." if photo else "") + " No text, no logos."


def scrub(prompt):
    """Drop the old 'no real or recognizable people' wording from a stored prompt."""
    return _OLD.sub("", str(prompt or "")).strip()


def rebuilds_layout(prompt):
    return bool(LAYOUT.search(str(prompt or "")))


# ---------------------------------------------------------------- speaker insert
def inset_for(sd, sec, ents):
    """The real source frame to show as an inset in this beat, or None: the beat names a person and the source has a frame
    for this beat (its snapshot, else a frame from its source clip)."""
    sd = Path(sd); bid = sec.get("id", "")
    if not names(sec.get("vo", ""), ents): return None
    ex = sd / "source_excerpts"
    snap = ex / f"{bid}_snap.png"
    if snap.is_file(): return snap
    try:
        led = json.loads((ex / "usage.json").read_text(encoding="utf-8")).get(bid) or {}
        clip = ex / str(led.get("asset") or "")
        if led.get("asset") and clip.is_file():
            if clip.suffix.lower() == ".png": return clip
            from . import media
            out = ex / f"{bid}_inset.jpg"
            if not out.is_file():
                d = media.dur(clip) or 2.0
                media.ff("-ss", f"{min(1.0, d / 2):.2f}", "-i", clip, "-frames:v", 1, out, check=False, timeout=120)
            return out if out.is_file() else None
    except (OSError, ValueError):
        pass
    return None


def add_insets(sd, pub, sec, bgs, ents, used=None, log=print, cfg=None):
    """Give the beat's non-source shots the speaker inset (copied into the render's public dir). -> bgs"""
    if cfg is not None and not cfg.get("speaker_inset", True): return bgs
    if not bgs or sec.get("cta"): return bgs
    img = inset_for(sd, sec, ents)
    if not img: return bgs
    import shutil
    dst = Path(pub) / "media" / "fb" / f"inset_{sec.get('id', 'b')}_{Path(img).name}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists(): shutil.copy2(img, dst)
    if used is not None:
        try: used.append(str(Path(img).resolve().relative_to(Path(sd).resolve())).replace("\\", "/"))
        except ValueError: pass
    n = 0
    for bg in bgs:
        if str(bg.get("tag") or "").startswith("SOURCE") or bg.get("user"): continue
        if bg.get("type") == "graphic" and (bg.get("g") or {}).get("kind") in ("cta", "source_excerpt"): continue
        bg["inset"] = {"src": f"media/fb/{dst.name}"}; n += 1
    if n: log(f"  {sec.get('id')}: speaker inset (real source frame) on {n} shot(s)")
    return bgs
