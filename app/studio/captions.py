"""Kinetic captions: big bold words (one highlighted keyword) + a small emoji icon, timed to the narration.
Word times come from faster-whisper on each section's narration, aligned back to the script text."""
import json, re, difflib, os
from pathlib import Path

STOP = set("the a an and or but of to in on for with at by from is are was were be been it this that these those as not no so if then than too very just about into over under more most less can could would should will may might do does did have has had you your we our they their he his she her i me my them what which who how why when where there here all any some such only own same other its it's".split())
EMOJI_FONT = r"C:\Windows\Fonts\seguiemj.ttf"

def _norm(w): return re.sub(r"[^a-z0-9]", "", w.lower())

_model = None
def _whisper():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        _model = WhisperModel("small.en", device="cpu", compute_type="int8")
    return _model

def word_times(wav, script_text):
    """Return [(word, start, end)] for every script word (times relative to the wav)."""
    segs, _ = _whisper().transcribe(str(wav), language="en", word_timestamps=True, vad_filter=False, beam_size=1)
    ww = [(_norm(w.word), w.start, w.end) for s in segs for w in (s.words or []) if _norm(w.word)]
    words = script_text.split(); sn = [_norm(w) for w in words]
    t = [None] * len(words)
    sm = difflib.SequenceMatcher(None, sn, [x[0] for x in ww], autojunk=False)
    for a, b, n in sm.get_matching_blocks():
        for k in range(n): t[a + k] = (ww[b + k][1], ww[b + k][2])
    end_all = ww[-1][2] if ww else max(1.0, len(words) / 2.6)
    # interpolate gaps
    i = 0
    while i < len(words):
        if t[i] is None:
            j = i
            while j < len(words) and t[j] is None: j += 1
            t0 = t[i - 1][1] if i > 0 else 0.0
            t1 = t[j][0] if j < len(words) else end_all
            step = max(0.05, (t1 - t0) / (j - i))
            for k in range(i, j): t[k] = (t0 + (k - i) * step, t0 + (k - i + 1) * step)
            i = j
        else: i += 1
    return [(w, a, b) for w, (a, b) in zip(words, t)]

def groups(wt, max_words=24):
    """One caption per sentence; long sentences split at a comma/semicolon near the middle."""
    sents, cur = [], []
    for w, a, b in wt:
        cur.append((w, a, b))
        if re.search(r"[.!?][\"')\]]*$", w): sents.append(cur); cur = []
    if cur: sents.append(cur)
    def split(g):
        if len(g) <= max_words: return [g]
        mid = len(g) // 2
        cands = [i for i in range(4, len(g) - 4) if re.search(r"[,;:]$", g[i][0])]
        cut = (min(cands, key=lambda i: abs(i - mid)) + 1) if cands else mid
        return split(g[:cut]) + split(g[cut:])
    out = [x for g in sents for x in split(g)]
    res = []
    for g in out:
        clean = [x[0] for x in g]
        cand = [(i, _norm(c)) for i, c in enumerate(clean)]
        key = max(cand, key=lambda ic: (ic[1].isdigit() * 10 + (ic[1] not in STOP) * 5 + min(len(ic[1]), 12)))[0]
        if _norm(clean[key]) in STOP: key = -1
        res.append({"words": clean, "key": key, "start": g[0][1], "end": g[-1][2]})
    for i in range(len(res) - 1):   # keep the text up until the next sentence starts
        res[i]["end"] = max(res[i]["end"], res[i + 1]["start"])
    return res

EMOJI_PROMPT = """Below are the on-screen captions of an explainer video, numbered. Pick an emoji icon for about half of them (these are full sentences),
only where one clearly illustrates the caption's key word (e.g. money -> 💰, AI -> 🤖, brain -> 🧠, space -> 🚀, danger -> ⚠️,
school -> 🎓, time -> ⏰, growth -> 📈, energy -> ⚡, eye -> 👁️, lock/security -> 🔒, globe -> 🌍). Never two captions in a row.
Use common, unambiguous emoji only. No flags, no faces of specific people.
Reply with ONLY JSON mapping caption number to emoji, e.g. {{"1":"🤖","4":"💰"}}.

CAPTIONS:
{caps}"""

def pick_emojis(cfg, caps, log):
    try:
        from .llm import LLM
        with LLM(cfg, log) as llm:
            j = llm.chat_json("You are a video editor.", EMOJI_PROMPT.format(
                caps="\n".join(f"{i+1}. {' '.join(c['words'])}" for i, c in enumerate(caps))), max_tokens=3000)
        last = -5
        for k, e in sorted(((int(k), v) for k, v in j.items() if str(k).isdigit()), key=lambda x: x[0]):
            i = k - 1
            if 0 <= i < len(caps) and isinstance(e, str) and 0 < len(e) <= 8 and i - last >= 2:
                caps[i]["emoji"] = e; last = i
    except Exception as ex:
        log(f"  (emoji picking skipped: {str(ex)[:100]})")
    return caps

def emoji_png(e, out, size=130):
    from PIL import Image, ImageDraw, ImageFont
    f = ImageFont.truetype(EMOJI_FONT, 120)
    im = Image.new("RGBA", (300, 300), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.text((60, 60), e, font=f, embedded_color=True)
    bb = im.getbbox()
    if not bb: return False
    im = im.crop(bb); im.thumbnail((size, size))
    im.save(out); return True

def _ass_time(t):
    t = max(0, t); h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60
    return f"{h}:{m:02}:{s:05.2f}"

ASS_HEAD = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Arial,58,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,1,0,0,0,100,100,0,0,1,4,2,2,220,220,70,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
HILITE = "&H0000D7FF&"   # gold (BGR)   # red (BGR)

def write_ass(caps, out, offset=0.0, low=()):
    """low: [(t0, t1)] section-time intervals (e.g. chart slides) where captions sit lower."""
    lines = [ASS_HEAD]
    for c in caps:
        mv = 30 if any(a <= c["start"] + offset < b for a, b in low) else 0
        ws = list(c["words"])
        if c["key"] >= 0: ws[c["key"]] = "{\\c" + HILITE + "}" + ws[c["key"]] + "{\\c&H00FFFFFF&}"
        txt = "{\\fad(120,80)}" + " ".join(ws)
        lines.append(f"Dialogue: 0,{_ass_time(c['start'] + offset)},{_ass_time(c['end'] + offset)},Cap,,0,0,{mv},,{txt}\n")
    Path(out).write_text("".join(lines), encoding="utf-8")

def build_section(cfg, job, sid, vo_text, log):
    """Compute captions for one section (cached in captions/<sid>.json)."""
    d = job / "captions"; d.mkdir(exist_ok=True)
    js = d / f"v2_{sid}.json"
    if js.exists(): return json.loads(js.read_text(encoding="utf-8"))
    import unicodedata
    text = unicodedata.normalize("NFKD", vo_text).encode("ascii", "ignore").decode()
    caps = groups(word_times(job / "voice" / f"{sid}.wav", text))
    caps = pick_emojis(cfg, caps, log)
    for c in caps:
        if c.get("emoji"):
            p = d / ("e_" + "_".join(f"{ord(ch):x}" for ch in c["emoji"]) + ".png")
            if p.exists() or emoji_png(c["emoji"], p): c["emoji_png"] = str(p)
    js.write_text(json.dumps(caps, ensure_ascii=False, indent=1), encoding="utf-8")
    return caps
