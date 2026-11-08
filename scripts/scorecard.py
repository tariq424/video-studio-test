"""Principle scorecard across several finished Shorts (owner, 2026-11-07: fixes are universal, checked across varied videos).

usage: app\\env\\Scripts\\python.exe scripts\\scorecard.py <job_id> [<job_id> ...] [--out DIR]
Writes DIR/scorecard.md (one table, a row per principle, a column per video) and DIR/<job>_sheet.jpg (contact sheets).
Reads only the job folders (log, timeline, prompts); never changes a job."""
import json, re, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from studio import config, people  # noqa: E402

PROMISE = re.compile(r"\b(full (breakdown|video|explainer|episode)|linked below|watch the full|longer video|part two)\b", re.I)
EXACT = re.compile(r"\bpoint (zero|one|two|three|four|five|six|seven|eight|nine)\b|\d+\.\d+", re.I)
NUMWORD = re.compile(r"\b(\d[\d,.]*|zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|thirty|forty|fifty|"
                     r"sixty|seventy|eighty|ninety|hundred|thousand|million|billion|percent)\b", re.I)


def job_dir(j):
    """The test bed's jobs first (42020), then the configured jobs folder."""
    for root in (Path(r"F:\videos_test\jobs"), Path(config.load().get("jobs_dir") or ".")):
        if (root / j / "state.json").exists(): return root / j
    raise FileNotFoundError(f"no job {j}")


def score(jd):
    jd = Path(jd); sd = jd / "short"; log = (jd / "log.txt").read_text(encoding="utf-8", errors="replace") if (jd / "log.txt").exists() else ""
    st = json.loads((jd / "state.json").read_text(encoding="utf-8"))
    tz = json.loads((sd / "public" / "teaser.json").read_text(encoding="utf-8"))
    ents = people.ents_for(jd)
    r = {"title": st.get("title", "")[:60], "status": st.get("status")}
    # turnaround and length
    ts = re.findall(r"^\[(\d\d):(\d\d):(\d\d)\]", log, re.M)   # first log line -> "Finished." (later editor work not counted)
    fin = re.search(r"^\[(\d\d):(\d\d):(\d\d)\] Finished\.", log, re.M)
    if ts and fin:
        sec = lambda h, m, s_: int(h) * 3600 + int(m) * 60 + int(s_)
        r["minutes"] = round(((sec(*fin.groups()) - sec(*ts[0])) % 86400) / 60, 1)
    else: r["minutes"] = None
    r["length_s"] = round(tz.get("total", 0))
    # WanGP last resort
    r["wangp_shots"] = sum(1 for b in tz["beats"] for g in b["bgs"] if re.search(r"WANGP|WAN", str(g.get("tag") or ""), re.I))
    # on-story: story QC flags, repairs, what stayed open
    qc = [int(m) for m in re.findall(r"story QC: \d+ shot\(s\) checked, (\d+) off-story", log)]
    r["offstory_first"] = qc[0] if qc else None
    r["offstory_last"] = qc[-1] if qc else None
    r["repairs"] = sum(int(m) for m in re.findall(r"QC repair: (\d+) of \d+ span", log))
    r["final_qc_flagged"] = (re.findall(r"final QC: \d+ frames checked, (\d+) flagged", log) or [None])[-1]
    # people: generated prompts for beats naming a person must be sketches; no rebuilt layouts anywhere
    stand_in, layouts, sketches = [], [], 0
    by_beat = {b["id"]: " ".join(str(w[0]) for w in b.get("words", [])) for b in tz["beats"]}
    for pf in list((sd / "imagegen").glob("*.prompt.txt")) + list((sd / "chain").glob("*.prompt.txt")):
        p = pf.read_text(encoding="utf-8", errors="replace"); bid = pf.name.split("_")[0]
        if people.rebuilds_layout(p): layouts.append(pf.name)
        if people.names(by_beat.get(bid, ""), ents) or (pf.parent.name in ("imagegen", "chain") and people.shows_person(p) and "sketch" not in p.lower()
                                                        and ((sd / "source_excerpts" / f"{bid}_snap.png").exists() or pf.parent.name == "chain")):
            if "sketch" in p.lower(): sketches += 1
            else: stand_in.append(pf.name)
    r["photo_standins"] = len(stand_in); r["sketches"] = sketches; r["rebuilt_layouts"] = len(layouts)
    # real source footage share and the speaker inset
    tot = src = 0.0
    for b in tz["beats"]:
        for i, g in enumerate(b["bgs"]):
            d = (b["bgs"][i + 1]["from"] if i + 1 < len(b["bgs"]) else b["dur"]) - g["from"]
            tot += d; src += d if str(g.get("tag") or "").startswith("SOURCE") else 0
    r["source_pct"] = round(100 * src / tot) if tot else 0
    named = [b for b in tz["beats"] if people.names(by_beat[b["id"]], ents) and not any((x.get("g") or {}).get("kind") == "cta" for x in b.get("graphics", []))]
    r["named_beats"] = len(named)
    r["inset_beats"] = sum(1 for b in named if any(g.get("inset") for g in b["bgs"]))
    # action beats: the narration describes an action -> it should move (any video, or a physics / motion animation), not a still
    from studio import physics
    MOVING = ("sim", "simmap", "motion", "recon")
    acts = [b for b in tz["beats"] if (physics.action({"vo": by_beat[b["id"]]})[0] or physics.event_action(by_beat[b["id"]]))
            and not any((x.get("g") or {}).get("kind") == "cta" for x in b.get("graphics", []))]
    r["action_beats"] = len(acts)
    r["action_moving"] = sum(1 for b in acts if any(g.get("type") == "video" or (g.get("g") or {}).get("kind") in MOVING for g in b["bgs"]))
    r["flow_clips"] = sum(1 for b in tz["beats"] for g in b["bgs"] if "FLOW" in str(g.get("tag") or ""))
    r["meta_video_clips"] = sum(1 for b in tz["beats"] for g in b["bgs"] if str(g.get("tag") or "") == "GENERATED · META")
    # pacing: longest single shot
    r["longest_shot_s"] = round(max(((b["bgs"][i + 1]["from"] if i + 1 < len(b["bgs"]) else b["dur"]) - g["from"]
                                     for b in tz["beats"] for i, g in enumerate(b["bgs"])), default=0), 1)
    # narration: exact decimals, sentences with 2+ numbers
    vo = " ".join(by_beat.values())
    sents = re.split(r"(?<=[.!?])\s+", vo)
    r["exact_decimals"] = len(EXACT.findall(vo))
    r["multi_number_sentences"] = sum(1 for s in sents if len(NUMWORD.findall(s)) >= 3)
    # ending: no link promise in the video; a quick last beat
    last = tz["beats"][-1]; cta_text = by_beat[last["id"]] + " " + " ".join(str((g.get("g") or {}).get(k) or "") for g in last.get("graphics", []) for k in ("badge", "line"))
    r["link_promise"] = bool(PROMISE.search(" ".join(by_beat.values()) + " " + cta_text))
    r["ending_words"] = len(by_beat[last["id"]].split())
    return r


ROWS = [  # (key, principle, pass test)
    ("status", "Job finished", lambda v: v == "finished"),
    ("minutes", "Turnaround (minutes)", lambda v: v is not None and v <= 45),
    ("length_s", "Length in s (complete beats; past 180 s is fine)", lambda v: True),
    ("wangp_shots", "WanGP last resort (shots made by WanGP)", lambda v: v == 0),
    ("offstory_first", "Off-story shots found by story QC", lambda v: True),
    ("offstory_last", "Off-story shots left after repair", lambda v: v in (0, None)),
    ("repairs", "QC repairs", lambda v: True),
    ("final_qc_flagged", "Final QC frames flagged", lambda v: v in ("0", None)),
    ("photo_standins", "Photo-real stand-ins for named people", lambda v: v == 0),
    ("sketches", "Sketches of named people", lambda v: True),
    ("rebuilt_layouts", "Rebuilt screen layouts (split screen / video call)", lambda v: v == 0),
    ("source_pct", "Real source footage (% of screen time)", lambda v: True),
    ("inset_beats", "Beats naming a person that show the speaker inset", lambda v: True),
    ("action_beats", "Action beats (narration describes motion)", lambda v: True),
    ("action_moving", "Action beats shown moving (video / physics)", lambda v: True),
    ("flow_clips", "Flow clips (cap 1)", lambda v: v <= 1),
    ("meta_video_clips", "Meta video clips (free, cap 3)", lambda v: v <= 3),
    ("longest_shot_s", "Longest single shot (s)", lambda v: v <= 15),
    ("exact_decimals", "Exact decimals read aloud", lambda v: v == 0),
    ("multi_number_sentences", "Sentences with 3+ numbers", lambda v: v == 0),
    ("link_promise", "Video promises a link", lambda v: not v),
    ("ending_words", "Words in the closing beat (no slow sign-off)", lambda v: v <= 6),
]


def sheet(jd, out):
    mp4 = next(iter(sorted((Path(jd) / "output").glob("*_short.mp4"))), None)
    if not mp4: return None
    dst = Path(out) / f"{Path(jd).name}_sheet.jpg"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(mp4), "-vf", "fps=1/6,scale=216:-2,tile=10x3", "-frames:v", "1", str(dst)], check=False)
    return dst if dst.exists() else None


def main(argv):
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else ROOT / "qc_smoke_results" / time.strftime("scorecard_%Y%m%d_%H%M")
    skip = {argv.index("--out") + 1} if "--out" in argv else set()
    ids = [a for k, a in enumerate(argv) if not a.startswith("--") and k not in skip]
    out.mkdir(parents=True, exist_ok=True)
    res = {}
    for j in ids:
        try: res[j] = score(job_dir(j))
        except Exception as e: res[j] = {"error": f"{type(e).__name__}: {e}"[:200]}
        try: sheet(job_dir(j), out)
        except FileNotFoundError: pass
    lines = ["| Principle | " + " | ".join(f"{(res[j].get('title') or j)[:28]}<br>`{j}`" for j in ids) + " |",
             "|---|" + "---|" * len(ids)]
    for key, name, ok in ROWS:
        cells = []
        for j in ids:
            v = res[j].get(key, "–") if "error" not in res[j] else "error"
            mark = "" if v in ("–", "error") else (" ✓" if ok(v) else " ✗")
            cells.append(f"{v}{mark}")
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    (out / "scorecard.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "scorecard.json").write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    print("\n".join(lines)); print(f"\n-> {out}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(sys.argv[1:])
