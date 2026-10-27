"""Frame quality check for every finished video (owner, 2026-10-24): smudges, fingers, sideways / upside-down picture, blur,
clothing or giant-face close-ups, black frames. Uses this PC's local vision model (Ollama); without it the check is skipped.
  qc_part   a frame every few seconds; a failing stretch is covered, under the same sound, by a still (turned upright when it
            was upside down, else the nearest clean frame, else blurred)
  qc_final  a frame every 10-30 s of the finished video -> <video>_qc.jpg (failures red) + <video>_qc.json

Recalibration (v2, 2026-10-26, after the first run flagged most frames of the news Shorts and the videos had to be
restored from preqc):
  - two-agree: a flagged frame is re-checked with a strict confirmation prompt; the fault counts only if both agree.
  - persistence: a hard fault counts only when the SAME problem appears in at least 2 consecutive samples;
    a single-sample hit (transition, cut) is recorded as ignored and never fixed.
  - hard / soft split: HARD faults (sideways, upside_down, black, finger, smudge) may be covered by a still;
    SOFT faults (blurry, face_closeup, clothing_closeup) are reported only, never auto-fixed.
  - qc_mode: cfg "qc_mode" = "report" (default) only reports - it never modifies the video; "fix" covers hard spans.
  - unchecked frames (vision model error) are counted, never silently passed: if more than 10% of a video's
    samples are unchecked, its QC status in the report is "incomplete", not "passed".

v3 (2026-10-26, after smoke test 1: specimen A passed, B's sideways / upside-down / black were all missed):
  - black is detected from pixels, not by asking the model: a frame whose mean luminance is under 6 is black.
  - persistence is resolved adaptively: an isolated hard flag probes the frames halfway to its neighbouring
    samples (+/- half a step); the same problem there confirms it. A 10 s fault can no longer fall between
    samples at a 6 s interval and die on the two-in-a-row rule.
  - the vision prompts judge orientation FIRST, using any visible text / captions / faces as the anchor, and an
    upside-down face is upside_down, not face_closeup.
  - every sample's first and confirmation verdicts are recorded in the reports ("samples" / row fields),
    so a miss can be attributed: the first look, or the confirmation.

v4 (2026-10-26, after smoke round 2: A failed - the orientation-first prompt made qwen2.5vl:7b call 24 of 30
upright samples sideways; B's black was named by both checks but dropped, and the pixel test missed it):
  - the vision prompts revert to the round-1 wording (A was clean under it). The model's DIRECT sideways /
    upside_down verdicts are ignored entirely - two rounds proved they are noise in both directions.
  - orientation is decided by rotate-and-compare instead: a 4-panel strip (as-is, 180, 90, 90 the other way)
    and one question - which panel looks upright and readable? "Cannot tell" is a valid answer and flags nothing.
  - two-agree is judged on the problem field alone: if both checks name the same problem it is confirmed,
    whatever the ok fields say (round 2's confirm replied ok:true with problem "black" and was discarded).
  - the pixel black test is a FLAT-black test: mean luminance under 24 AND stddev under 4. Limited-range video
    black measures 16, not 0; a dark but real scene has texture, a black frame does not.

v5 (2026-10-26, after smoke round 3: black PASS via the pixel test; orientation produced ZERO false flags on A
but also ZERO catches on B, and the strip answers were never recorded; B's upside-down sample at 37 s escaped
because a confirmed SOFT flag skipped the orientation check; A's remaining hard flags were "finger" on ordinary
footage of hands typing / pointing):
  - orientation is now PAIRWISE rotate-and-compare: the frame as-is against one rotation at a time (180, then
    90 CCW, then 90 CW), each side at readable height (768 px), instead of one 4-panel strip whose panels
    shrank past readability under the vision model's own downscale. Every pair's answer is recorded per
    sample (the "orient" field in the reports), so a miss is attributable: the model picked the as-is side,
    answered "none", or its reply failed to parse.
  - the orientation check now runs on frames with a confirmed SOFT fault too; only a confirmed HARD fault or
    an unchecked frame skips it.
  - "finger" is defined strictly in both prompts: a finger or thumb pressed against the lens, blocking the
    view. Hands visible IN the scene (typing, pointing, holding objects) are normal footage, not a fault.

v6 (2026-10-26, after smoke round 4: pairwise orientation FAILED the other way - the model answered "right"
on 22 of 29 upright A samples and 23 of 29 B samples, so every upright frame was flagged upside_down and B's
sideways segment was mislabelled upside_down; the 90-CW pair was never even reached. A left/right question
cannot be trusted from this model: the answer follows the side, not the picture):
  - orientation is now SINGLE-IMAGE upright tests, with no left/right choice anywhere: the frame as-is is
    shown alone and asked "is this picture upright?" (yes/no/unknown). Only when the as-is answer is NOT
    yes are the rotations shown alone, one at a time (180, then 90 CCW, then 90 CW), each asked the same
    question. A rotation fault counts ONLY on a discordant pair: as-is not-upright AND exactly one rotation
    upright (180 -> upside_down, either 90 -> sideways). If the as-is frame already reads upright, or no
    rotation reads upright, nothing is flagged. Every answer is recorded per sample (the "orient" field),
    so the next failure is attributable: as-is yes on a rotated segment means a yes-bias; as-is no with all
    rotations no means the model cannot read orientation in this format either; a rotated yes on an upright
    frame cannot flag anything, because the as-is yes short-circuits first.
  - everything else from v5 stands: pairwise code is gone, but the strict finger definition, the flat-black
    pixel test, orientation running on confirmed-SOFT frames, and the per-sample orient log all stay.

v7 (2026-10-26, after smoke round 5: single-image orientation passed EVERYTHING except B's upside-down
segment (30-40 s) - both samples, 31 s and 37 s, answered asis:yes on genuinely upside-down frames, so the
180 test never ran. Both frames carry upside-down caption text and an "AI SECURITY - CONDENSED" label at
the bottom: the generic "is this upright?" question never surfaced the text cue. The as-is yes can no longer
short-circuit on its own):
  - an as-is yes is now seconded by a TEXT-ANCHORED probe before it counts: the model must quote the
    clearest readable text in the frame and judge whether that text reads upright, upside down, or on its
    side. Probe upright or none (no readable text) accepts the as-is yes and the check ends, as before.
    Probe upside_down or sideways does NOT flag anything by itself - it only reopens the rotation tests
    (180, then 90 CCW, then 90 CW, each alone), and a fault still counts ONLY on the old discordant pair:
    as-is not accepted AND exactly one rotation upright (180 -> upside_down, either 90 -> sideways). If no
    rotation reads upright, nothing is flagged, so the probe cannot create a false flag on its own.
    The probe answer (and the quoted text, truncated) is logged in the orient field, e.g.
    asis:yes;text:upside_down("AI SECURITY");180:yes.
  - KNOWN RESIDUAL GAP, stated plainly: a textless upside-down frame still answers asis:yes + text:none
    and is accepted upright. The probe closes exactly the evidenced miss (text-carrying upside-down
    frames, which is what the smoke specimen's upside-down segment is); it does not claim to catch
    textless inversions. If round 6 shows one, that is a different, separately evidenced failure.
  - everything else from v6 stands: single-image tests, strict finger definition, flat-black pixel test,
    orientation on confirmed-SOFT frames, per-sample orient log.

v8 (2026-10-26) - THE SAFE VERSION, prepared at Tariq's order after he closed the smoke-test loop at round 6.
The loop's final tally: black SOLVED (pixel test), finger SOLVED (strict prompts), sideways SOLVED in qc_part
(single-image tests, every injected sample recovered in rounds 5-6), soft classes fine; upside_down NOT
catchable on qwen2.5vl:7b - round 6's text probe quoted the inverted captions word for word and still called
them upright, so this model reads inverted text without registering inversion. Tariq's condition for ever
enabling QC: it must not fail videos over orientation.
  - orientation is REPORT-ONLY: sideways / upside_down move from HARD to SOFT. Detection still runs exactly
    as v7 (single-image tests + text probe, answers logged per sample) and findings appear in the reports'
    soft lists and on the qc_final sheet as "(soft)" notes - but they can never form a cover span, never
    appear in would_fix / fixed, and never mark a qc_final frame failed. HARD is now black, finger, smudge:
    the classes with a clean six-round record.
  - the persistence probe reach is capped at 4 s (it was half the sample step). In qc_final (30 s step) a
    probe used to land 15 s away - inside a different shot - and round 6 showed a real neighbouring fault
    rescuing a false flag that way (B qc_final 2 s). qc_part's reach (3 s at a 6 s step) is unchanged.
  - nothing else changes: prompts, two-agree, the pixel black test, the finger definition, the orientation
    machinery and its logging are v7's, untouched. This file does not set qc_on / interview_qc - enabling
    QC at all stays Tariq's separate decision, made in config, not here.

v9 (2026-10-27, at Claude's request after the MSG 011 standalone repair was NOT run: every marked HARD
span on the SpaceX / Moonshots EP #305 explainer proved to be a false positive):
  - the explainer's 7 model-"black" spans are its own designed cards on a dark navy background (the title
    card and the big-number stat cards: "15 GW", "10x", "70%", "$2T", "318K", "2 tons"). Their pixel stats
    at 768 px: mean luminance 21-29, stddev 30-46 - dark, but nowhere near flat black, and the pixel test
    correctly says NOT black. Under v8 a model "black" verdict still counted as HARD once both looks
    agreed, so the two-agree rule did not protect dark designed cards. v9: BLACK IS DECIDED BY THE PIXEL
    TEST ONLY. A model "black" verdict (even two-agree) on a frame that fails the flat-black pixel test
    is vetoed - the sample is recorded ok with via "pixel-veto", and the model's claim stays visible in
    the sample's first / confirm fields.
  - the explainer's 1 model-"finger" span (495.5-502.5 s) is a whiteboard shot of a hand placing sticky
    notes - a hand IN the scene, confirmed "finger" by both looks despite the strict prompt. v9 applies
    the same idea with the matching measurement: a two-agree "finger" verdict is vetoed (recorded ok,
    via "detail-veto") when the frame carries real scene texture - luminance stddev at least
    FINGER_DETAIL_MIN (30) at the sample's own scale. A finger pressed on the lens is one blurry
    skin-coloured shape with nothing recognisable behind it - near-textureless by the fault's own
    definition - so a detailed frame cannot be that fault. CALIBRATION NOTE, stated plainly: the 30
    threshold is set from Claude's measured false positives (the dark cards' stddev ran 30-46); no
    measured true-finger sample exists yet, so if a future round produces one, re-check this number
    against it.
  - nothing else changes: the pixel test itself, the prompts, two-agree, persistence and the 4 s probe
    cap, the orientation machinery (report-only) and its logging are v8's, untouched. HARD stays black,
    finger, smudge. This file does not set qc_on / qc_mode - Claude returned qc_mode to "report" as a
    safety action on 2026-10-27, and any return to "fix" stays Tariq's separate decision, in config.
"""
import json
import shutil
from pathlib import Path

from . import media

ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-profile:v", "high"]

QCVER = 9
HARD = ("black", "finger", "smudge")
SOFT = ("blurry", "face_closeup", "clothing_closeup", "sideways", "upside_down")
FINGER_DETAIL_MIN = 30.0   # v9: a two-agree "finger" verdict on a frame whose luminance stddev reaches this
                           # is a hand in a textured scene, not a finger on the lens - see the v9 header note.


def _log(log, m):
    (log or print)(m)


def available(cfg):
    if cfg.get("vet_provider", "local") not in ("local", "", None) and cfg.get("qc_provider", "local") != "local": return True
    try:
        import requests
        return requests.get(cfg.get("ollama_url", "http://127.0.0.1:11434").rstrip("/") + "/api/tags", timeout=4).status_code == 200
    except Exception:
        return False


QC = """Quality check of one frame from a finished travel documentary. Reply with JSON only:
{"ok": true|false, "problem": "none|finger|smudge|sideways|upside_down|blurry|clothing_closeup|face_closeup|black"}
Not ok: a finger or thumb pressed against the lens itself, blocking the view (one big blurry skin-coloured shape with
nothing recognisable behind it), a smudge or fog on the lens, a picture lying on its side or upside down, a blurry smear,
a close-up of clothing filling the frame, one person's face filling most of the frame, or a black / empty frame.
Hands visible IN the picture - typing on a keyboard, pointing at a screen, holding or using objects - are normal
footage, NOT a finger fault."""

CONFIRM = """A first quality check of this single frame claimed the problem: "{problem}".
Be strict: confirm ONLY if that exact fault is obvious in this frame. A normal shot - including a person's face
in a talking-head shot, a dark but visible scene, or a frame caught mid-transition - is NOT a fault.
If the claimed problem is "finger": confirm ONLY when a finger or thumb is pressed against the lens, blocking the
camera's view. Hands visible in the scene - typing, pointing, holding objects - are NOT a finger fault.
Reply with JSON only: {{"ok": true|false, "problem": "none|finger|smudge|sideways|upside_down|blurry|clothing_closeup|face_closeup|black"}}"""

ORIENT1 = """This is a single picture, shown on its own. Look at any text or captions, at faces, and at which way
is up in the scene (sky, ground, people standing). Is this picture upright - the way it would normally be
viewed - or is it rotated? Reply with JSON only:
{{"upright": true}} if the picture looks upright and readable,
{{"upright": false}} if the picture looks rotated (on its side or upside down),
{{"upright": "unknown"}} if you cannot tell."""

ORIENT2 = """This is a single picture, shown on its own. Ignore everything except the TEXT in it - captions,
subtitles, labels, signs, on-screen graphics. Quote the clearest words you can actually read, if any.
Then say whether that text reads upright (normal reading direction), upside down, or on its side.
Reply with JSON only:
{{"text": "<the clearest words you read, or empty string if no text is readable>",
  "text_orientation": "upright"|"upside_down"|"sideways"|"none"}}
where "none" means no readable text is visible or you cannot tell which way the text reads. Do not guess
words that are not there: an empty text with "none" is a correct answer for a textless picture."""


def _pixel_flat_black(img):
    """A black frame is a measurement, not an opinion: FLAT black - mean luminance under 24 (limited-range
    video black measures 16, not 0) AND stddev under 4 (a dark but real scene has texture; a black frame has none)."""
    try:
        from PIL import Image, ImageStat
        st = ImageStat.Stat(Image.open(img).convert("L"))
        return st.mean[0] < 24.0 and st.stddev[0] < 4.0
    except Exception: return False


def _scene_detail(img):
    """Luminance stddev of the frame at its own scale - a texture measurement, companion to the flat-black
    test (v9). A finger pressed on the lens is a single blurry shape with nothing recognisable behind it,
    so its frame has little texture; a real scene (a whiteboard, a desk, a street) has plenty. Returns 0.0
    when the frame cannot be read, which never vetoes anything."""
    try:
        from PIL import Image, ImageStat
        return ImageStat.Stat(Image.open(img).convert("L")).stddev[0]
    except Exception: return 0.0


def _judge(cfg, img):
    """-> {"state": "ok"|"bad"|"unchecked", "prob", "raw", "first", "confirm", "via"}.
    Black is decided from pixels ONLY (v9): a model "black" verdict - even two-agree - on a frame that
    fails the flat-black pixel test is vetoed to ok (via "pixel-veto"); the pixel test is the only road
    to a black verdict. A two-agree "finger" verdict is likewise vetoed (via "detail-veto") when the
    frame carries real scene texture (see _scene_detail). Anything else: a flag is the problem FIELD of
    the first check; it stands only when the confirmation check names the SAME problem (the ok fields are
    ignored - the model pairs ok:true with a named problem too often to trust them). Direct sideways /
    upside_down verdicts are recorded but never acted on: orientation is decided separately, by
    single-image upright tests."""
    if _pixel_flat_black(img): return {"state": "bad", "prob": "black", "raw": "black", "first": "pixel", "confirm": "pixel", "via": "pixel"}
    from . import footage
    from .llm import parse_json
    try: j = parse_json(footage._vision(dict(cfg, vet_provider="local"), img, QC))
    except Exception: return {"state": "unchecked", "prob": "unchecked", "raw": "", "first": "error", "confirm": "", "via": "model"}
    prob = str(j.get("problem") or "none").strip().lower()
    if prob in ("none", ""): return {"state": "ok", "prob": "none", "raw": prob, "first": prob, "confirm": "", "via": "model"}
    try: j2 = parse_json(footage._vision(dict(cfg, vet_provider="local"), img, CONFIRM.format(problem=prob)))
    except Exception: return {"state": "unchecked", "prob": prob, "raw": prob, "first": prob, "confirm": "error", "via": "model"}
    prob2 = str(j2.get("problem") or "none").strip().lower()
    if prob2 != prob: return {"state": "ok", "prob": "none", "raw": prob, "first": prob, "confirm": prob2, "via": "model"}
    if prob in ("sideways", "upside_down"):   # both checks agree, and it still doesn't count: see _orientation
        return {"state": "ok", "prob": "none", "raw": prob, "first": prob, "confirm": prob2, "via": "model"}
    if prob == "black":   # v9: reachable only when the flat-black pixel test already failed (it runs first,
        # above) - a model "black" here is an opinion about a dark frame, and opinions no longer count.
        return {"state": "ok", "prob": "none", "raw": prob, "first": prob, "confirm": prob2, "via": "pixel-veto"}
    if prob == "finger" and _scene_detail(img) >= FINGER_DETAIL_MIN:   # v9: a frame with real scene texture
        # is a scene with a hand in it, not a finger on the lens - the pixel evidence vetoes the two-agree.
        return {"state": "ok", "prob": "none", "raw": prob, "first": prob, "confirm": prob2, "via": "detail-veto"}
    return {"state": "bad", "prob": prob, "raw": prob, "first": prob, "confirm": prob2, "via": "model"}


def _orient_single(cfg, im, img, tag, rot):
    """Show ONE version of the frame on its own (as-is when rot is None, else rotated) and ask whether it
    is upright. -> "yes" | "no" | "none" | "error:<why>" (an unparseable reply keeps its first 60 chars
    as evidence). There is no left/right choice in this question: round 4 proved the model answers "right"
    to a side-by-side pair almost regardless of the picture, so the pair format is retired entirely."""
    try:
        if rot is None: sp = Path(img)
        else:
            from PIL import Image
            sp = Path(img).with_name(Path(img).stem + f"_o1_{tag}.jpg")
            im.transpose(rot).save(sp, quality=85)
    except Exception: return "error:build"
    from . import footage
    from .llm import parse_json
    try: raw = footage._vision(dict(cfg, vet_provider="local"), sp, ORIENT1)
    except Exception: return "error:vision"
    try:
        j = parse_json(raw)
        a = (j or {}).get("upright")
    except Exception: return "error:parse:" + str(raw)[:60].replace("\n", " ")
    if a is True: return "yes"
    if a is False: return "no"
    if isinstance(a, str) and a.strip().lower() in ("unknown", "none", "cannot tell"): return "none"
    return "error:answer:" + str(a)[:20]


def _orient_text(cfg, img):
    """Text-anchored second opinion on the as-is frame -> "upright" | "upside_down" | "sideways" | "none" |
    "error:<why>", logged as text:<verdict>("<quoted text, truncated>"). Round 5 proved the generic
    upright question can answer yes on a genuinely upside-down frame that carries upside-down captions;
    this probe asks a different, narrower question (which way does the readable text read?) so a second
    yes-bias would have to survive two different wordings. It never flags anything on its own: it only
    reopens the rotation tests when it disagrees with the as-is yes."""
    from . import footage
    from .llm import parse_json
    try: raw = footage._vision(dict(cfg, vet_provider="local"), Path(img), ORIENT2)
    except Exception: return "error:vision"
    try:
        j = parse_json(raw)
        v = str((j or {}).get("text_orientation") or "").strip().lower()
        q = str((j or {}).get("text") or "").strip()
    except Exception: return "error:parse:" + str(raw)[:60].replace("\n", " ")
    if v not in ("upright", "upside_down", "sideways", "none"): return "error:answer:" + v[:20]
    if q: return f'{v}("{q[:30]}")'
    return v


def _orientation(cfg, img):
    """Orientation by single-image upright tests, with a text-anchored second opinion -> (fault | None, log).
    The frame as-is is judged alone first. If it reads upright, the text probe must second it: probe
    upright or none (no readable text) accepts the frame and the check ends; probe upside_down or sideways
    reopens the rotation tests instead of accepting. Only when the as-is answer is NOT accepted are the
    rotations judged alone, one at a time (180, then 90 CCW, then 90 CW): a rotation fault counts ONLY on
    a discordant pair, as-is not accepted AND that rotation upright (180 -> upside_down, either 90 ->
    sideways). If no rotation reads upright, nothing is flagged - so neither the as-is yes nor the probe
    can create a flag by itself. Every answer is logged, so the next miss is attributable: as-is yes +
    text upright on a rotated segment means both wordings share the yes-bias; as-is yes + text none on a
    textless rotated segment is the known residual gap; as-is no with all rotations no means the model
    cannot read orientation in this format either."""
    try:
        from PIL import Image
        im = Image.open(img).convert("RGB")
    except Exception: return None, "open-error"
    log = []
    a = _orient_single(cfg, im, img, "asis", None); log.append(f"asis:{a}")
    if a == "yes":
        t = _orient_text(cfg, img); log.append(f"text:{t}")
        if t.startswith("upside_down") or t.startswith("sideways"): pass  # reopen rotations below
        else: return None, ";".join(log)
    a = _orient_single(cfg, im, img, "180", Image.ROTATE_180); log.append(f"180:{a}")
    if a == "yes": return "upside_down", ";".join(log)
    a = _orient_single(cfg, im, img, "90ccw", Image.ROTATE_90); log.append(f"90ccw:{a}")
    if a == "yes": return "sideways", ";".join(log)
    a = _orient_single(cfg, im, img, "90cw", Image.ROTATE_270); log.append(f"90cw:{a}")
    if a == "yes": return "sideways", ";".join(log)
    return None, ";".join(log)


def _judge_frame(cfg, img):
    """Full per-frame verdict: the model/pixel judge, plus single-image orientation tests. Orientation runs on
    every frame that is not already a confirmed HARD fault or unchecked - INCLUDING frames with a confirmed
    SOFT fault: round 3's B 37 s sample was an upside-down face confirmed as face_closeup (soft), and the old
    order never orientation-tested it, so the rotation fault escaped both checks."""
    v = _judge(cfg, img)
    if v["state"] == "unchecked": return v
    if v["state"] == "bad" and v["prob"] in HARD: return v
    o, olog = _orientation(cfg, img)
    if o: return {"state": "bad", "prob": o, "raw": o, "first": v.get("first", ""), "confirm": v.get("confirm", ""),
                  "via": "orient", "orient": olog}
    return {**v, "orient": olog}


def _flags(samples):
    return [(s["state"] == "bad" and s["prob"] in HARD) for s in samples]


def _resolve(samples, probe):
    """Persistence, resolved adaptively. A hard flag stands when the same problem appears in a neighbouring
    sample; an ISOLATED hard flag probes the frames halfway to its neighbours (probe(t, prob) -> verdict dict
    or None) and stands only if the same problem shows there. Sets s["rescued"] on probed samples.
    v8: the probe reach is capped at 4 s - at qc_final's 30 s step, half a step is 15 s, far enough to land
    in a different shot and let an unrelated real fault "rescue" a false flag (round 6, B qc_final 2 s)."""
    flags = _flags(samples); keep = list(flags)
    for i, f in enumerate(flags):
        if not f: continue
        prev_ok = i > 0 and flags[i - 1] and samples[i - 1]["prob"] == samples[i]["prob"]
        next_ok = i < len(samples) - 1 and flags[i + 1] and samples[i + 1]["prob"] == samples[i]["prob"]
        if prev_ok or next_ok: continue
        s = samples[i]
        step = (samples[i + 1]["t"] - s["t"]) if i + 1 < len(samples) else ((s["t"] - samples[i - 1]["t"]) if i > 0 else 4.0)
        reach = min(step / 2, 4.0)
        rescued = False
        if probe:
            for dt in (-reach, reach):
                v = probe(s["t"] + dt, s["prob"])
                if v and v.get("state") == "bad" and v.get("prob") == s["prob"]: rescued = True; break
        keep[i] = rescued; s["rescued"] = rescued
    return keep


def _mode(cfg):
    m = str(cfg.get("qc_mode", "report") or "report").strip().lower()
    return m if m in ("report", "fix") else "report"


def qc_part(path, cfg, log=print, every=4.0, label="", kind="documentary"):
    """Owner, 2026-10-24: check every piece before it is stitched in. A frame every `every` seconds goes to the local vision
    model (twice, if the first check flags it); a confirmed HARD fault that persists across samples (+/- 2 s) is replaced,
    under the same sound, by a still: the frame turned right side up when it was upside down, else the nearest clean frame
    of the same piece, else that frame blurred. In report mode (default) nothing is replaced - the spans are only
    logged and written to the report. Cached: <piece>.qc.json (keyed by size, QC version and mode)."""
    path = Path(path); rep = path.with_suffix(".qc.json"); mode = _mode(cfg)
    if rep.exists():
        try:
            old = json.loads(rep.read_text(encoding="utf-8"))
            if old.get("size") == path.stat().st_size and old.get("qcver") == QCVER and old.get("mode") == mode: return path
        except Exception: pass
    d = media.dur(path)
    if d < 1.5: return path
    tmp = path.with_suffix(""); tmp.mkdir(exist_ok=True)
    times = [min(d - 0.3, 1.0 + k * every) for k in range(int(max(0.0, d - 1.0) // every) + 1)]
    samples = []
    for k, t in enumerate(times):
        img = tmp / f"qc{k:03}.jpg"
        media.ff("-ss", f"{t:.2f}", "-i", path, "-frames:v", 1, "-vf", "scale=768:-2", img, timeout=120)
        v = _judge_frame(cfg, img) if img.exists() else {"state": "unchecked", "prob": "unchecked", "raw": ""}
        samples.append({"t": t, "img": img, **v})
    nun = sum(1 for s in samples if s["state"] == "unchecked")
    incomplete = bool(samples) and nun / len(samples) > 0.10
    def probe(t2, prob):
        if t2 < 0 or t2 > d - 0.3: return None
        img2 = tmp / f"qcR{int(t2 * 10)}.jpg"
        media.ff("-ss", f"{t2:.2f}", "-i", path, "-frames:v", 1, "-vf", "scale=768:-2", img2, timeout=120)
        return _judge_frame(cfg, img2) if img2.exists() else None
    keep = _resolve(samples, probe)
    bad = [(s["t"], s["prob"], s["img"]) for s, k in zip(samples, keep) if k]
    single = [(s["t"], s["prob"]) for s, k in zip(samples, keep)
              if s["state"] == "bad" and s["prob"] in HARD and not k]
    soft = [(s["t"], s["prob"]) for s in samples if s["state"] == "bad" and s["prob"] in SOFT]
    for t, prob in single: _log(log, f"    QC {label}: {t:.1f}s {prob} ignored (single sample, not persistent)")
    spans = []
    for t, prob, img in bad:
        a, b = max(0.0, t - every / 2 - 0.5), min(d, t + every / 2 + 0.5)
        if spans and a <= spans[-1][1]: spans[-1][1] = max(spans[-1][1], b); spans[-1][2].append((t, prob, img))
        else: spans.append([a, b, [(t, prob, img)]])
    would = [(round(a, 1), round(b, 1), sorted({p for _, p, _ in items})) for a, b, items in spans]
    fixed = []
    if spans and mode == "report":
        for a, b, probs in would: _log(log, f"    QC {label}: REPORT ONLY {a:.1f}-{b:.1f}s {', '.join(probs)} - would be covered by a still in fix mode")
    elif spans:
        good = [(s["t"], s["img"]) for s in samples if s["state"] == "ok"]
        ins, flt, n = ["-i", str(path)], [], 1
        chain = "[0:v]"
        for a, b, items in spans:
            t, prob, img = items[0]
            still = tmp / f"fix_{a:.0f}.jpg"
            near = min(good, key=lambda g: abs(g[0] - t))[1] if good else None
            if prob == "upside_down":
                media.ff("-i", img, "-vf", "transpose=1,transpose=1", still, timeout=60); how = "turned upright"
            elif near is not None:
                shutil.copy(near, still); how = "nearest clean frame"
            else:
                media.ff("-i", img, "-vf", "boxblur=24:2", still, timeout=60); how = "blurred"
            ins += ["-loop", "1", "-t", f"{d:.2f}", "-i", str(still)]
            W, H = (1080, 1920) if kind == "short" else (1920, 1080)
            flt.append(f"[{n}:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1[s{n}]")
            flt.append(f"{chain}[s{n}]overlay=enable='between(t,{a:.2f},{b:.2f})'[o{n}]")
            chain = f"[o{n}]"; n += 1
            _log(log, f"    QC {label}: {a:.1f}-{b:.1f}s {', '.join(sorted({p for _, p, _ in items}))} -> still ({how})")
        fixed_mp4 = path.with_name(path.stem + "_qc.mp4")
        media.ff(*ins, "-filter_complex", ";".join(flt), "-map", chain, "-map", "0:a?", "-t", f"{d:.2f}", *ENC, "-c:a", "copy", fixed_mp4, timeout=1800)
        fixed_mp4.replace(path)
        fixed = [(t, p) for t, p, _ in bad]
    if incomplete: _log(log, f"    QC {label}: INCOMPLETE - {nun}/{len(samples)} frames unchecked (vision model)")
    rep.write_text(json.dumps({"qcver": QCVER, "mode": mode, "size": path.stat().st_size, "checked": len(samples),
                               "unchecked": nun, "status": "incomplete" if incomplete else "complete",
                               "fixed": fixed, "would_fix": would if mode == "report" else [],
                               "soft": soft, "ignored_single": single,
                               "samples": [{"t": round(s["t"], 1), "state": s["state"], "prob": s["prob"],
                                            "first": s.get("first", ""), "confirm": s.get("confirm", ""), "via": s.get("via", ""),
                                            "orient": s.get("orient", ""),
                                            "rescued": bool(s.get("rescued", False))} for s in samples]}, indent=1), encoding="utf-8")
    return path


def qc_final(out, cfg, work, log=print, every=30.0):
    """Pre-release check of the finished video: a frame every 30 s; a contact sheet with confirmed persistent
    HARD failures marked red and a report (qc report json) beside the video. Report-only by design."""
    from PIL import Image, ImageDraw
    out = Path(out); d = media.dur(out); tmp = Path(work) / "qc_final"; tmp.mkdir(exist_ok=True, parents=True)
    samples, ims = [], []
    for k in range(int(d // every) + 1):
        t = min(d - 1.0, 2.0 + k * every); img = tmp / f"f{k:03}.jpg"
        media.ff("-ss", f"{t:.2f}", "-i", out, "-frames:v", 1, "-vf", "scale=480:-2", img, timeout=120)
        if not img.exists(): continue
        v = _judge_frame(cfg, img)
        samples.append({"t": round(t, 1), **v}); ims.append((t, img))
    def probe(t2, prob):
        if t2 < 0 or t2 > d - 0.5: return None
        img2 = tmp / f"fR{int(t2 * 10)}.jpg"
        media.ff("-ss", f"{t2:.2f}", "-i", out, "-frames:v", 1, "-vf", "scale=480:-2", img2, timeout=120)
        return _judge_frame(cfg, img2) if img2.exists() else None
    keep = _resolve(samples, probe)
    rows = []
    for s, k in zip(samples, keep):
        hard = k
        rows.append({"t": s["t"], "ok": not hard,
                     "problem": s["prob"] if hard else ("none" if s["state"] != "unchecked" else "unchecked"),
                     "raw": s["raw"], "first": s.get("first", ""), "confirm": s.get("confirm", ""), "via": s.get("via", ""),
                     "orient": s.get("orient", ""),
                     "rescued": bool(s.get("rescued", False)), "unchecked": s["state"] == "unchecked",
                     "soft": s["prob"] if (s["state"] == "bad" and s["prob"] in SOFT) else ""})
    if ims:
        first = Image.open(ims[0][1]); w, h = first.size; cols = 6
        sheet = Image.new("RGB", (w * cols, h * ((len(ims) + cols - 1) // cols)))
        dr = ImageDraw.Draw(sheet)
        for i, ((t, img), r) in enumerate(zip(ims, rows)):
            x, y = (i % cols) * w, (i // cols) * h; sheet.paste(Image.open(img), (x, y))
            tag = "" if r["ok"] else r["problem"]
            if r["soft"] and r["ok"]: tag = r["soft"] + " (soft)"
            dr.rectangle([x, y, x + 170, y + 18], fill="black" if r["ok"] else "red"); dr.text((x + 3, y + 3), f"{int(t // 60)}:{int(t % 60):02d} {tag}", fill="yellow")
        sheet.save(tmp / (out.stem + "_qc.jpg"), quality=85)   # in the work folder: the output folder stays clean for the Publisher
    nun = sum(1 for r in rows if r["unchecked"])
    incomplete = bool(rows) and nun / len(rows) > 0.10
    (tmp / (out.stem + "_qc.json")).write_text(json.dumps(
        {"qcver": QCVER, "status": "incomplete" if incomplete else "complete", "unchecked": nun, "frames": rows}, indent=1), encoding="utf-8")
    nbad = sum(1 for r in rows if not r["ok"])
    _log(log, f"  final QC: {len(rows)} frames checked, {nbad} flagged"
         + (": " + ", ".join(f"{r['t']:.0f}s {r['problem']}" for r in rows if not r["ok"]) if nbad else "")
         + (f"; INCOMPLETE ({nun} unchecked)" if incomplete else ""))
