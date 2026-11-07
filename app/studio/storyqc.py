"""Story QC (owner, 2026-11-07): the inspector that looks at the FINISHED video against what is being said.

The frame QC (qc.py) only finds technical faults (black, blurry, upside down, giant faces). This check takes a frame from every
background shot of the finished video, has the local vision model say what it shows (flags, places, landmarks, people, text),
and has the script AI compare that with the narration playing at that moment and with the story as a whole. A shot that
contradicts the story (another country's flag or city, a clearly unrelated scene) is flagged; in fix mode its span is handed
to qc_repair, which replaces it from the ladder while the narration plays on.

Skipped: the source's own clips (SOURCE tags) and the creator's own footage (they ARE the story). Never raises (cancel aside),
never blocks the job: an unavailable model just leaves the shot unchecked. Report: <job>/qc/<video>.story.json."""
import json, time
from pathlib import Path

from . import media

DESCRIBE = ("Describe this video frame in one or two sentences: the background scene. Name any flag (which country), city, "
            "landmark, country, recognisable place, vehicle make or readable text you can identify. Ignore caption text and "
            "graphic cards laid over the picture. Reply with JSON only: {\"shows\": \"...\"}")
JUDGE = """A news video's finished frame, described by a vision model, and the narration playing at that moment.
What the whole video is about: "{story}"
Narration at this moment: "{vo}"
The frame shows: "{shows}"
Does the picture CONTRADICT the story or the narration? Contradictions: another country's flag, a different country or city
than the story's, a recognisable place the story is not about, or something clearly unrelated to both the line and the story.
Generic or loosely related scenes (landscapes, roads, offices, crowds, maps, documents) are fine. A country, city, place or
flag that the narration line itself mentions or that is part of the story is NOT a contradiction: every side of a conflict
the story covers counts (Israeli or Palestinian flags in a story about Israel and Gaza; Egyptian streets over a line about
Egyptians). Only flag places and flags from OUTSIDE the story (Brazil, Turkey, the US in a story about Israel and Gaza).
Reply with JSON only: {{"contradicts": true or false, "why": "a few words"}}"""


def _timeline(job_dir, vert):
    p = Path(job_dir) / ("short" if vert else "build") / "public" / "teaser.json"
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return None


def _vo(beat, plan_vo):
    w = beat.get("words") or []
    txt = " ".join(str(x[0]) for x in w if isinstance(x, (list, tuple)) and x)
    return txt or plan_vo.get(beat.get("id"), "")


def shots(tl, plan_vo=None):
    """-> [{beat, t, a, b, tag, src, vo}]: one entry per background shot of the finished video, with the time of its middle frame.
    The source's own clips, the creator's footage and the closing card are left out."""
    out = []
    for bt in (tl or {}).get("beats") or []:
        bgs = bt.get("bgs") or []; s0, d = float(bt.get("start", 0)), float(bt.get("dur", 0))
        if bt.get("cta") or not bgs or d <= 0: continue
        vo = _vo(bt, plan_vo or {})
        for i, g in enumerate(bgs):
            tag = str(g.get("tag") or "")
            if tag.upper().startswith(("SOURCE", "YOUR", "OWN")) or g.get("own"): continue
            a = s0 + float(g.get("from") or 0)
            b = s0 + (float(bgs[i + 1].get("from") or 0) if i + 1 < len(bgs) else d)
            if b - a < 0.8: continue
            t = round(a + min(2.5, (b - a) / 2), 2)
            # Nov 7: one frame missed a VOTE + US flag clip (its first seconds read as "abstract blue design"), so a shot
            # long enough also gets a frame two thirds in; a shot is off-story when either frame is
            ts = [t] + ([round(a + (b - a) * 2 / 3, 2)] if b - a >= 4 else [])
            out.append({"beat": bt.get("id"), "t": t, "ts": ts, "a": round(a, 2), "b": round(b, 2),
                        "tag": tag, "src": str(g.get("src") or ""), "vo": vo})
    return out


def _script_cfg(cfg):
    c = dict(cfg)
    if c.get("script_provider") == "claude" and not c.get("anthropic_api_key"): c["script_provider"] = "deepseek" if c.get("deepseek_api_key") else "local"
    return c


def check(mp4, cfg, job_dir, log=print, vert=True, stop=lambda: False, only=None):
    """-> list of flagged shots [{beat, a, b, t, shows, why, src}]. Writes <job>/qc/<video>.story.json.
    only: [(a, b), ...] checks just the shots overlapping those spans (the verify pass after a repair)."""
    from . import footage
    from .llm import LLM, parse_json
    mp4 = Path(mp4); job_dir = Path(job_dir)
    rep = {"video": mp4.name, "started": time.strftime("%Y-%m-%d %H:%M:%S"), "shots": [], "flagged": []}
    rpath = job_dir / "qc" / f"{mp4.stem}.story{'_verify' if only else ''}.json"; rpath.parent.mkdir(parents=True, exist_ok=True)
    try:
        if not cfg.get("story_qc_on", True): return []
        tl = _timeline(job_dir, vert)
        plan = {}
        try:
            from .pipeline import Job
            p = Job(job_dir).short_plan() if vert else Job(job_dir).plan()
            plan = {s["id"]: s.get("vo", "") for s in (p or {}).get("sections", [])}
        except Exception: pass
        sh = shots(tl, plan)
        story_all = " ".join(dict.fromkeys(x["vo"] for x in sh))[:600]
        if only: sh = [x for x in sh if any(x["a"] < b - 0.05 and x["b"] > a + 0.05 for a, b in only)]
        sh = sh[:int(cfg.get("story_qc_max_shots", 40))]
        if not sh: log("  story QC: no timeline for this video; skipped"); return []
        story = story_all   # the whole video's story, also when only a few shots are checked
        work = job_dir / "qc" / "story"; work.mkdir(parents=True, exist_ok=True)
        vcfg = dict(cfg, vet_provider=cfg.get("vet_provider") if cfg.get("vet_provider") not in (None, "", "off") else "local")
        log(f"Story QC: {len(sh)} shot(s) of {mp4.name} checked against the narration")
        with LLM(_script_cfg(cfg), log, lambda: False) as llm:
            for k, s in enumerate(sh):
                if stop(): raise RuntimeError("cancelled")
                row = dict(s, shows="", contradicts=None, why="")
                seen, failed = [], ""
                for m, tt in enumerate(s.get("ts") or [s["t"]]):
                    img = work / f"{mp4.stem[:24]}_{k:03}_{m}.jpg"
                    media.ff("-ss", f"{tt:.2f}", "-i", mp4, "-frames:v", 1, "-vf", "scale=640:-2", img, check=False, timeout=120)
                    if not img.exists(): continue
                    try:
                        raw = str(footage._vision(vcfg, img, DESCRIBE) or "")
                        try: pj = parse_json(raw) or {}
                        except Exception: pj = {}
                        shows = pj.get("shows") if isinstance(pj, dict) else ""
                        if not shows and isinstance(pj, dict): shows = " ".join(str(v) for v in pj.values() if isinstance(v, str))
                        shows = str(shows or raw.strip().strip("`{}")).strip()[:300]   # a plain-text answer still counts
                        if shows and shows not in seen: seen.append(shows)
                    except Exception as e: failed = f"vision model unavailable ({str(e)[:60]})"
                if not seen and failed: row["why"] = failed; rep["shots"].append(row); continue
                if not seen and not failed and not any((work / f"{mp4.stem[:24]}_{k:03}_{m}.jpg").exists() for m in range(len(s.get("ts") or [1]))):
                    row["why"] = "no frame"; rep["shots"].append(row); continue
                row["shows"] = " / Later in the shot: ".join(seen)[:600]
                if not row["shows"]: row["contradicts"], row["why"] = False, "nothing identifiable in the frame"
                else:
                    try:
                        j = llm.chat_json("You are a precise video editor. Reply with JSON only.",
                                          JUDGE.format(story=story.replace('"', "'"), vo=s["vo"][:400].replace('"', "'"),
                                                       shows=row["shows"].replace('"', "'")), max_tokens=100)
                        row["contradicts"] = str(j.get("contradicts")).strip().lower() in ("true", "yes", "1")
                        row["why"] = str(j.get("why") or "")[:80]
                    except Exception as e: row["why"] = f"script AI unavailable ({str(e)[:60]})"
                rep["shots"].append(row)
                if row["contradicts"]:
                    rep["flagged"].append(row)
                    log(f"  story QC {s['beat']} {s['a']:.1f}-{s['b']:.1f}s: OFF-STORY - {row['shows'][:90]} ({row['why']})")
        n = len(rep["flagged"]); unk = sum(1 for r in rep["shots"] if r["contradicts"] is None)
        log(f"  story QC: {len(rep['shots'])} shot(s) checked, {n} off-story" + (f", {unk} unchecked" if unk else ""))
    except Exception as e:
        if str(e) == "cancelled" or type(e).__name__ == "Paused": raise
        log(f"  story QC skipped ({type(e).__name__}: {str(e)[:160]})")
    finally:
        try:
            footage.unload_vet_model(cfg)
        except Exception: pass
        rep["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
        try: rpath.write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding="utf-8")
        except OSError: pass
    return rep["flagged"]


def marks(flagged):
    """Flagged shots -> repair spans [(a, b, ["off_story"])], merged when they touch."""
    out = []
    for f in sorted(flagged, key=lambda x: x["a"]):
        if out and f["a"] <= out[-1][1] + 0.3: out[-1] = (out[-1][0], max(out[-1][1], f["b"]), out[-1][2])
        else: out.append((f["a"], f["b"], ["off_story"]))
    return out
