"""Interview jobs in the Video Studio editor (owner, 2026-10-25): the interview edit (interview.py) opened as a job, so the
owner can scrub it, open any piece (a soundbite, a fact, a narration line), see other pictures for it, preview, apply, undo,
and chat about it - instead of another round of automatic versions.

A job made from an interview edit has state kind="interview" and two manifests, iedit/short.json and iedit/long.json
(written by interview.build: every piece in order with its file, captions, and where its picture came from).
Editing a piece changes only its PICTURE: his voice / the narration stays. Candidates for a piece:
  - in the video now; the same, blurred
  - the same clip at other moments that are clean as filmed (no close-up of the camera holder, no finger, not sideways)
  - the creator's other clips filmed at the same place the same day (catalogue GPS + time): the outside of the building,
    the greetings inside, the third floor ... (labelled with the catalogue's description)
  - a file the owner supplies (path on this PC)
Applying re-renders the piece and re-assembles the video (captions + music) - a minute for the Short, ~20 min for the
documentary. "Stop if not sure": pieces whose picture was a guess (blurred, covered from another clip, a fact over the
scene) are marked "check" on the timeline."""
import csv
import json
import math
import re
import shutil
import threading
import time
from pathlib import Path

from . import media

VIDEO = {".mov", ".mp4", ".m4v"}
PHOTO = {".jpg", ".jpeg", ".png"}


def is_interview(job):
    from .pipeline import Job
    return Job(job).state.get("kind") == "interview"


def _k(job):
    from .pipeline import Job
    t = Job(job).state.get("edit_target") or "short"
    return "long" if t == "long" else "short"


def _man_p(job, k): return Path(job) / "iedit" / f"{k}.json"
def _man(job, k=None): return json.loads(_man_p(job, k or _k(job)).read_text(encoding="utf-8"))
def _save_man(job, k, m): _man_p(job, k).write_text(json.dumps(m, indent=1, ensure_ascii=False), encoding="utf-8")


def outputs(job):
    return [k for k in ("short", "long") if _man_p(job, k).exists()]


def kind(job): return _k(job)


def set_target(job, target):
    from .pipeline import Job
    if target not in ("short", "long") or not _man_p(job, target).exists(): raise ValueError(f"this job has no {target} video")
    Job(job).save(edit_target=target)


def workspace(job, k=None):
    return Path(job) if (k or _k(job)) == "short" else Path(job) / "longedit"


def _rd(job, k=None):
    sd = workspace(job, k) / "short"; rd = sd / "review"; rd.mkdir(parents=True, exist_ok=True)
    return sd, rd


def _label(p, i):
    m = p.get("m") or {}; t = m.get("type", "")
    if t == "bite": lab = "Soundbite" + (f" · {p['chapter']}" if p.get("chapter") else "")
    elif t == "fact": lab = f"Fact · {p.get('card') or ''}".strip(" ·")
    elif t == "narr": lab = "Narration"
    else: lab = "Title / end card"
    return ("⚠ check · " if p.get("check") else "") + lab


def _vo(p):
    m = p.get("m") or {}
    return m.get("text") or " ".join(w[0] for w in (p.get("words") or []))


def _pic_source(p):
    """Editor-only note (owner, 2026-10-27): where this piece's picture came from - the ladder rung that
    supplied it (read from the sibling <k>_insert.json the build wrote), a photo credit, or the footage
    file. Shown in the editor only; never rendered into the video."""
    m = p.get("m") or {}
    t = m.get("type", "")
    f = Path(p.get("file") or "")
    try:
        if t == "bite":
            return "Your footage · " + Path(m.get("src") or f).name
        if t == "narr":
            if m.get("src"):
                return "Your footage · " + Path(m["src"]).name
            return "Picture · " + f.name if f.name else ""
        if t == "fact":
            rung = credit = ""
            try:
                ins = json.loads(f.with_suffix(".json").read_text(encoding="utf-8"))
                rung, credit = str(ins.get("rung") or ""), str(ins.get("credit") or "")
            except Exception:
                pass
            credit = credit or str(p.get("credit") or "")
            if rung:
                return f"Ladder · {rung} · {f.name}"
            if credit:
                return f"Photo · {credit} · {f.name}"
            return f"Insert · {f.name} (over blurred footage)"
        if t == "card":
            return "Card · " + f.name
    except Exception:
        pass
    return f.name


def beats(job):
    k = _k(job); m = _man(job, k); out, t = [], 0.0
    for i, p in enumerate(m["parts"]):
        d = float(p.get("dur") or media.dur(p["file"]))
        out.append({"id": f"p{i:02}", "start": round(t, 3), "dur": round(d, 3), "label": _label(p, i), "vo": _vo(p)[:600],
                    "editable": (p.get("m") or {}).get("type") in ("bite", "fact", "narr"), "own": True, "source": _pic_source(p)})
        t += d
    return {"kind": "short" if k == "short" else "long", "beats": out}


def _part(job, bid, k=None):
    m = _man(job, k); i = int(bid[1:]); return m, i, m["parts"][i]


# ---------------------------------------------------------------- candidates
def _keep_kinds(an_dir):
    from . import shots
    try: an = json.loads((Path(an_dir) / "faces.json").read_text(encoding="utf-8"))
    except Exception: return {}
    return {x["t"]: shots.kind_keep(x) for x in an.get("secs") or []}


def _same_clip(m, p, d, n=5, reach=150.0):
    """Clean windows of the piece's own clip near it: [(start, label)]."""
    mm = p.get("m") or {}
    if mm.get("src") is None or mm.get("si") is None: return []
    src, fl, an_dir = m["sources"][int(mm["si"])]
    by = _keep_kinds(an_dir)
    if not by: return []
    dur = media.dur(src); t0 = float(mm.get("t0") or 0); t1 = float(mm.get("t1") or t0 + d)
    ok = lambda a: a >= 0 and a + d <= dur - 0.2 and not (a < t1 and a + d > t0) and all(by.get(t, "none") in ("none", "guest") for t in range(int(a), int(a + d) + 1))
    out, step = [], 0
    while len(out) < n and step <= reach:
        for a in (t0 - d - step, t1 + step):
            if ok(a) and all(abs(a - x) > d for x, _ in out): out.append((a, f"Same clip at {int(a // 60)}:{int(a % 60):02}, clean as filmed"))
        step += 5
    return [(src, fl, a, lab) for a, lab in out[:n]]


def _place_clips(m, p, n=14, radius=250.0):
    """The creator's other clips at the same place the same day, from the folder's catalogue."""
    mm = p.get("m") or {}
    src = Path(mm["src"]) if mm.get("src") else Path(m["sources"][0][0])
    lab_dir = Path(m["sources"][0][0]).parent / "labeled"
    if not (lab_dir / "index.csv").exists() or not m.get("gps"): return []
    la, lo = m["gps"]
    desc = {}
    try:
        for r in csv.DictReader(open(lab_dir / "catalog.csv", encoding="utf-8-sig")):
            desc[Path(r["original"].replace("\\", "/")).name] = r
    except Exception: pass
    rows = list(csv.DictReader(open(lab_dir / "index.csv", encoding="utf-8-sig")))
    day = next((r["taken"][:10] for r in rows if r["file"] == Path(m["sources"][0][0]).name), "")
    used = {Path(x[0]).name for x in m["sources"]}
    out, seen = [], set()
    for r in rows:
        f = Path(m["sources"][0][0]).parent / r["file"]
        if f.suffix.lower() not in VIDEO | PHOTO or f.name == src.name or (day and r["taken"][:10] != day): continue
        try: dist = 6371000 * math.hypot(math.radians(float(r["lat"]) - la), math.radians(float(r["lon"]) - lo) * math.cos(math.radians(la)))
        except ValueError: continue
        if dist > radius: continue
        c = desc.get(r["file"], {})
        if str(c.get("face_closeup", "")).lower() == "true": continue
        key = (r["taken"][:16], r["seconds"])
        if key in seen: continue   # an IMG_ copy and its named copy
        seen.add(key)
        d = (c.get("description") or r.get("place") or "").split(" / ")[0][:90]
        flip = f.name in used and next((bool(x[1]) for x in m["sources"] if Path(x[0]).name == f.name), False)
        out.append((f, flip, 1.0 if f.suffix.lower() in VIDEO else 0.0, f"{r['taken'][11:16]} · {f.name} · {d}"))
    return out[:n]


def _thumb(item, out, kind):
    from . import shots
    W, H = (270, 480) if kind == "short" else (480, 270)
    f = Path(item["file"])
    if f.suffix.lower() in PHOTO:
        media.ff("-i", f, "-frames:v", 1, "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}", out, timeout=60)
    else:
        vf = shots.vf_frame("short" if kind == "short" else "documentary", None, 0.0, bool(item.get("flip")), blur=bool(item.get("blur")))
        media.ff("-ss", f"{float(item.get('start', 0)) + min(1.0, float(item.get('dur', 2)) / 2):.2f}", "-i", f, "-frames:v", 1, "-vf", vf + f",scale={W}:{H}", out, timeout=60)


def open_beat(job, bid, cfg, log):
    from . import review
    job = Path(job); k = _k(job); ws = workspace(job, k); sd, rd = _rd(job, k)
    with review._lock(ws):
        rv = review.load(ws) or {"mode": "edit", "status": "closed", "next": 1, "beats": {}, "cands": {}}
        m, i, p = _part(job, bid, k)
        d = float(p.get("dur") or media.dur(p["file"]))
        b = rv["beats"].get(bid)
        if not b or b.get("file") != p["file"]:   # first open, or the piece changed: build its candidates
            b = rv["beats"][bid] = {"vo": _vo(p), "secs": d, "auto": [], "cands": [], "decision": "auto", "chosen": [], "uncertain": bool(p.get("check")),
                                    "why": "", "history": [], "busy": "", "msg": "", "notes": [], "file": p["file"], "current": []}
            def add(rung, item, why):
                cid = f"{bid}_{len(b['cands'])}"
                th = rd / "thumbs" / f"{cid}.jpg"; th.parent.mkdir(exist_ok=True)
                try: _thumb(dict(item, dur=d), th, k)
                except Exception: return None
                rv["cands"][cid] = {"id": cid, "beat": bid, "rung": rung, "ok": True, "why": why, "item": item, "thumb": review._rel(th, sd),
                                    "secs": d, "key": f"{item.get('file')}|{item.get('start', 0)}|{item.get('blur', False)}"}
                b["cands"].append(cid); return cid
            cur = add("current", {"file": p["file"], "start": 0.0, "flip": False, "part": True}, "in the video now")
            b["current"] = [cur] if cur else []; b["auto"] = list(b["current"])
            add("own", {"file": p["file"], "start": 0.0, "flip": False, "part": True, "blur": True}, "the same, blurred")
            for f, fl, a, lab in _same_clip(m, p, d): add("own", {"file": str(f), "start": a, "flip": fl}, lab)
            for f, fl, a, lab in _place_clips(m, p): add("own", {"file": str(f), "start": a, "flip": fl}, lab)
            review.save(ws, rv)
        return rv


def supply(job, bid, src, space=None):
    from . import review
    job = Path(job); k = _k(job); ws = workspace(job, k); sd, rd = _rd(job, k)
    f = Path(src.strip().strip('"'))
    if not f.is_file(): raise ValueError(f"File not found on this PC: {f}")
    rv = open_beat(job, bid, {}, print); b = rv["beats"][bid]
    cid = f"{bid}_u{len(b['cands'])}"; th = rd / "thumbs" / f"{cid}.jpg"; th.parent.mkdir(exist_ok=True)
    item = {"file": str(f), "start": 0.0, "flip": False, "user": True}
    _thumb(dict(item, dur=b["secs"]), th, k)
    rv["cands"][cid] = {"id": cid, "beat": bid, "rung": "supplied", "ok": True, "why": "your file", "item": item, "thumb": review._rel(th, sd), "secs": b["secs"], "key": str(f)}
    b["cands"].append(cid); b["chosen"] = [cid]
    review.save(ws, rv)
    return rv


# ---------------------------------------------------------------- rendering a piece with a new picture
def _picture(job, items, d, out, kind, scale=1.0):
    """Video-only file of length d from the chosen items (played in order, each an equal share)."""
    from . import shots
    W, H = (1080, 1920) if kind == "short" else (1920, 1080)
    W, H = int(W * scale) // 2 * 2, int(H * scale) // 2 * 2
    segs, share = [], d / max(1, len(items))
    for n, it in enumerate(items):
        f = Path(it["file"]); seg = Path(out).with_name(Path(out).stem + f"_{n}.mp4")
        if f.suffix.lower() in PHOTO:
            nfr = int(share * 30) + 1
            vf = (f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,crop={W * 2}:{H * 2},"
                  f"zoompan=z='min(zoom+0.0006,1.10)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={nfr}:s={W}x{H}:fps=30,format=yuv420p,setsar=1")
            media.ff("-loop", 1, "-i", f, "-t", f"{share:.2f}", "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", seg, timeout=900)
        else:
            rot = "" if it.get("part") or it.get("flip") else shots.orient(f, Path(job) / "iedit", print)
            vf = (rot + "," if rot else "") + shots.vf_frame("short" if kind == "short" else "documentary", None, 0.0, bool(it.get("flip")), blur=bool(it.get("blur")))
            if scale != 1.0: vf += f",scale={W}:{H}"
            st = float(it.get("start", 0)); loop = ["-stream_loop", "-1"] if media.dur(f) < st + share else []
            media.ff(*loop, "-ss", f"{st:.2f}", "-i", f, "-t", f"{share:.2f}", "-an", "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                     "-pix_fmt", "yuv420p", seg, timeout=900)
        segs.append(seg)
    if len(segs) == 1: shutil.move(str(segs[0]), str(out)); return out
    lst = Path(out).with_suffix(".txt"); lst.write_text("".join(f"file '{s.as_posix()}'\n" for s in segs), encoding="utf-8")
    media.ff("-f", "concat", "-safe", 0, "-i", lst, "-c", "copy", out, timeout=900)
    for s in segs: s.unlink(missing_ok=True)
    return out


def _render_piece(job, bid, cids, out, scale=1.0):
    from . import review
    k = _k(job); ws = workspace(job, k); rv = review.load(ws)
    m, i, p = _part(job, bid, k); d = float(p.get("dur") or media.dur(p["file"]))
    items = [rv["cands"][c]["item"] for c in cids if c in rv["cands"]]
    if not items: raise ValueError("pick at least one picture")
    if len(items) == 1 and items[0].get("part") and not items[0].get("blur"): shutil.copy2(p["file"], out); return out, d
    pic = Path(out).with_name(Path(out).stem + "_pic.mp4")
    _picture(job, items, d, pic, k, scale)
    media.ff("-i", pic, "-i", p["file"], "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "copy", "-t", f"{d:.3f}", out, timeout=900)
    pic.unlink(missing_ok=True)
    return out, d


def preview_cand(job, cid, space=None):
    """A 2-second look at one candidate (the Candidates pane's thumbnail click)."""
    from . import review
    k = "long" if space == "long" else "short"; ws = workspace(job, k); sd, rd = _rd(job, k); rv = review.load(ws); c = rv["cands"][cid]
    out = rd / "prev" / f"{cid}.mp4"; out.parent.mkdir(exist_ok=True)
    if not media.ok(out, 0.3): _picture(job, [dict(c["item"], start=float(c["item"].get("start", 0)))], 2.0, out, k, 0.5)
    return {"video": review._rel(out, sd)}


def preview(job, bid, cids, fit, cfg, log):
    out = Path(job) / "iedit" / "prev" / f"{_k(job)}_{bid}.mp4"; out.parent.mkdir(parents=True, exist_ok=True)
    _render_piece(job, bid, cids, out, scale=0.5)
    return {"video": str(out.relative_to(Path(job))).replace("\\", "/"), "fit": "as filmed", "why": "his voice / the narration stays; only the picture changes"}


def _assemble(job, k, cfg, log):
    from .pipeline import Job
    from . import interview
    m = _man(job, k); s = Job(job).state
    out = Path(s["short_output" if k == "short" else "output"])
    work = Path(job) / "iedit" / f"{k}_work"; work.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.stem + ".new.mp4")
    parts = [dict(p, words=[tuple(w) for w in p.get("words") or []], titles=[tuple(t) for t in p.get("titles") or []],
                  credits=[tuple(c) for c in p.get("credits") or []]) for p in m["parts"]]
    interview.assemble(parts, tmp, "short" if k == "short" else "documentary", work, dict(cfg, **(m.get("cfg") or {})), log, m.get("title", ""))
    prev = out.with_suffix(".prev")
    if out.exists(): shutil.copy2(out, prev)
    for n in range(20):
        try: tmp.replace(out); break
        except PermissionError:
            if n == 19: raise RuntimeError("Can't replace the video file — it's open in another app. Close the player and retry.")
            time.sleep(1)


def start_apply(job, bid, cids, fit, cfg, log):
    from . import edit
    key = str(Path(job))
    with edit._lk:
        if edit._busy.get(key): return "Already applying an edit to this video."
        k = _k(job)
        edit._busy[key] = f"Applying the new picture to {bid}" + (" (re-assembling the documentary takes ~20 min)" if k == "long" else " (about a minute)")
        edit._busy.pop(key + ":err", None)
    def run():
        from .pipeline import Job
        from . import review
        try:
            m, i, p = _part(job, bid, k)
            n = len(list((Path(job) / "iedit" / "parts").glob(f"{k}_{bid}_*.mp4"))) if (Path(job) / "iedit" / "parts").exists() else 0
            new = Path(job) / "iedit" / "parts" / f"{k}_{bid}_{n + 1}.mp4"; new.parent.mkdir(parents=True, exist_ok=True)
            _render_piece(job, bid, cids, new)
            hist = m.setdefault("history", []); hist.append({"bid": bid, "old": p["file"], "new": str(new), "t": time.time()})
            p["file"] = str(new); p["check"] = False; m["parts"][i] = p; _save_man(job, k, m)
            _assemble(job, k, cfg, log)
            ws = workspace(job, k); rv = review.load(ws)
            if rv and bid in rv["beats"]: rv["beats"].pop(bid); review.save(ws, rv)   # candidates rebuilt around the new piece on next open
            Job(job).save(edit_last={"beat": bid, "ok": True, "msg": "Applied.", "t": time.time()})
            log(f"Edit {bid} applied ({k})")
        except Exception as e:
            msg = str(e)[:300]; edit._busy[key + ":err"] = msg; log(f"Edit {bid} NOT applied: {msg}")
            try: Job(job).save(edit_last={"beat": bid, "ok": False, "msg": msg, "t": time.time()})
            except Exception: pass
        finally:
            edit._busy.pop(key, None)
    threading.Thread(target=run, daemon=True).start()
    return ""


def can_undo(job):
    try: return bool(_man(job).get("history"))
    except Exception: return False


def undo(job, log, cfg=None):
    from . import config
    k = _k(job); m = _man(job, k); h = m.get("history") or []
    if not h: raise ValueError("nothing to undo")
    last = h.pop(); i = int(last["bid"][1:]); m["parts"][i]["file"] = last["old"]; _save_man(job, k, m)
    _assemble(job, k, cfg or config.load(), log)


# ---------------------------------------------------------------- chat about a piece
CHAT = """You help the owner edit one piece of his interview video in an editor. The piece's audio (his voice or a narration
line) stays; only the picture can change. The words in this piece: {vo}
Pictures available for it (id: what it is):
{cands}
In the video now: {cur}
The owner says: {text}
Earlier in this conversation: {past}
Reply with JSON only: {{"reply": "short plain answer", "select": [ids to show, in order, or []], "apply": true|false}}
- "select" only ids from the list; pick the ones that match what he asks (e.g. "the outside of the building" -> the clip whose
  description says building / exterior; "where I greet people" -> greetings / salaam / prayer hall with people).
- "apply": true only when he clearly says to apply / use it / do it now. If nothing in the list fits, say so and suggest
  he supply a file (path on the PC) - never pretend."""


def chat(job, bid, text, cfg):
    from .pipeline import Job
    from . import review
    from .llm import LLM
    j = Job(job); k = _k(job); rv = open_beat(job, bid, cfg, j.log); b = rv["beats"][bid]
    cands = "\n".join(f"{c}: {rv['cands'][c]['why']}" for c in b["cands"])
    past = [e for e in (j.state.get("debug") or {}).get("chat", []) if e.get("beat") == bid][-4:]
    with LLM(dict(cfg), j.log, lambda: False) as llm:
        r = llm.chat_json("You are a careful video editor's assistant. Reply with JSON only.",
                          CHAT.format(vo=b["vo"][:600], cands=cands, cur=", ".join(b["current"]), text=text,
                                      past=" | ".join(f"you: {e['you']} -> {e['reply']}" for e in past) or "(none)"), max_tokens=400)
    sel = [c for c in (r.get("select") or []) if c in rv["cands"]]
    action = "none"
    reply = str(r.get("reply") or "")
    if sel and r.get("apply"):
        err = start_apply(job, bid, sel, "auto", cfg, j.log)
        action = "apply"
        if err: reply += f"\n(Couldn't do it: {err})"
    elif sel: action = "select"
    ent = {"t": time.strftime("%H:%M"), "beat": bid, "you": text, "reply": reply, "backend": "deepseek", "action": action, "kind": "interview"}
    if sel: ent["select"] = sel
    d = j.state.get("debug") or {}; d.setdefault("chat", []).append(ent); j.save(debug=d)
    return ent
