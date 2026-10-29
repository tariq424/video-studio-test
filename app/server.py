"""Video Studio: YouTube link, audio file (e.g. NotebookLM) or text in -> long explainer and/or a 2-3 min vertical Short out. Runs locally."""
import os, sys, json, socket
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory, abort
sys.path.insert(0, str(Path(__file__).resolve().parent))
from studio import config
from studio.pipeline import Studio, STAGES, stages_for
from studio.wangp import WanGP

VS_PORT = int(os.environ.get("PORT") or 42021)   # the launcher sets PORT; unset = live (42021) as before
app = Flask(__name__, static_folder="static"); studio = Studio(port=VS_PORT)

@app.get("/")
def index(): return send_from_directory(app.static_folder, "index.html")

@app.get("/api/settings")
def get_settings(): return jsonify(config.public())
@app.post("/api/settings")
def set_settings():
    try: config.save(request.json or {})
    except Exception as e: return jsonify(error=str(e)), 500
    return jsonify(config.public())

@app.post("/api/test_vision")
def test_vision():
    from studio import qa
    cfg = config.load(); b = request.json or {}
    ok, issue = qa.check(cfg, b["image"], b.get("prompt", "a photo"))
    return jsonify(ok=ok, issue=issue, provider=cfg.get("qa_provider"))

@app.get("/api/test_footage")
def test_footage():
    """Search every footage source once (keys never returned) so setup problems show up before a job runs."""
    from studio import footage
    q = request.args.get("q", "rocket launch"); orient = request.args.get("orient", "portrait"); logs = []
    out = {}
    for name, fn in (("Pexels", lambda: footage.pexels(q, orient, logs.append, 2560)), ("Pixabay", lambda: footage.pixabay(q, orient, logs.append, 2560)),
                     ("NASA", lambda: footage.nasa(q, logs.append, limit=3))):
        try: r = fn(); out[name] = {"count": len(r), "examples": [{"id": c["id"], "desc": c["desc"][:80], "size": f"{c['w']}x{c['h']}", "dur": c["dur"]} for c in r[:3]]}
        except Exception as e: out[name] = {"error": str(e)[:200]}
    keys = footage._keys()
    out["keys"] = {k: bool(keys.get(k)) for k in ("PEXELS_API_KEY", "PIXABAY_API_KEY")}; out["log"] = logs[-10:]
    return jsonify(out)

@app.post("/api/test_key")
def test_key():
    from studio.llm import LLM
    prov = (request.json or {}).get("provider", "zai")
    cfg = config.load(); cfg["script_provider"] = prov
    if prov == "local": return jsonify(ok=False, msg="Local AI has no key; it needs Ollama running.")
    if not cfg.get({"claude": "anthropic_api_key"}.get(prov, prov + "_api_key")): return jsonify(ok=False, msg="No key saved for " + prov)
    try:
        llm = LLM(cfg, lambda m: None); llm._chat("", "Reply with the single word OK.", 20)
        return jsonify(ok=True, msg=f"{prov}: key works with model {llm.name}")
    except Exception as e: return jsonify(ok=False, msg=f"{prov}: {str(e)[:300]}")

@app.get("/api/status")
def status():
    cfg = config.load()
    _wg = WanGP(cfg); _run = _wg.running()
    return jsonify(power=_power(), worker=os.environ.get("VS_WORKER", ""), wangp=_run, wangp_on_demand=_run or _wg.alive(), api_key=bool(cfg.get("anthropic_api_key")), zai_key=bool(cfg.get("zai_api_key")), deepseek_key=bool(cfg.get("deepseek_api_key")), provider=cfg.get("script_provider"), current=studio.current, stages=STAGES)

@app.get("/api/jobs")
def jobs(): return jsonify(studio.list())

@app.post("/api/jobs")
def create():
    from studio.sources import kind_of
    if request.mimetype in ("multipart/form-data", "application/x-www-form-urlencoded"):   # web form (optionally with a file)
        b = {k: v for k, v in request.form.items()}; f = request.files.get("file")
        b.setdefault("auto_approve", "true")   # script review is skipped unless the user ticks it off
        for k in ("presenter", "auto_approve", "captions"): b[k] = b.get(k) in ("true", "1", "on", True)
    else: b = request.get_json(silent=True) or {}; f = None
    sp = (b.get("src_path") or "").strip().strip('"')
    if sp and not (f and f.filename):   # a file on this PC by path (the /make page can't put a file into an upload field)
        if not Path(sp).is_file(): return jsonify(error=f"File not found on this PC: {sp}"), 400
        if not kind_of(Path(sp).name): return jsonify(error="Unsupported file type. Use audio (.mp3 .m4a .wav ...) or .txt .md .pdf .docx"), 400
        class _F:   # looks like an uploaded file to Studio.create
            filename = Path(sp).name
            def save(self, dst): import shutil; shutil.copy2(sp, dst)
        f = _F()
    if f is not None and f.filename and not kind_of(f.filename): return jsonify(error="Unsupported file type. Use audio (.mp3 .m4a .wav ...) or .txt .md .pdf .docx"), 400
    if b.get("mode") == "smoke" and not b.get("url") and not b.get("transcript") and not (f and f.filename):   # no source: the standard smoke video
        from studio import config as _cfg; b["url"] = _cfg.load().get("smoke_source", "")
    if not b.get("url") and not b.get("transcript") and not (f and f.filename): return jsonify(error="Give a YouTube link, a file, or paste some text."), 400
    try: mins, ssec = float(b.get("minutes", 15) or 15), float(b.get("short_secs", 165) or 165)
    except (TypeError, ValueError): return jsonify(error="Video lengths must be numbers."), 400
    if not 3 <= mins <= 20: return jsonify(error="Long video length must be 3 to 20 minutes."), 400
    if b.get("mode") != "smoke" and not 120 <= ssec <= 180: return jsonify(error="Short length must be 2:00 to 3:00."), 400
    from studio import debug as _dbg
    dbg_on = str(b.get("debug", "")).lower() in ("true", "1", "on")
    try: bps = _dbg.parse_all(b.get("breakpoints") or "")
    except ValueError as e: return jsonify(error=f"Breakpoint: {e}"), 400
    # your own clips (clips.py): uploads in "clips", paths on this PC in "clip_paths" (one per line), placement note in "clip_hints"
    cups = [x for x in (request.files.getlist("clips") if request.files else []) if x and x.filename]
    cpaths = b.get("clip_paths") or []
    if isinstance(cpaths, str): cpaths = [x for x in cpaths.splitlines() if x.strip()]
    own = None
    if cups or cpaths:
        from studio import config as _cfg
        if not _cfg.load().get("own_clips", False): return jsonify(error="Providing your own clips is switched off (setting own_clips)."), 400
        for p in cpaths:
            if not Path(p.strip().strip('"')).is_file(): return jsonify(error=f"Clip not found on this PC: {p.strip()}"), 400
        own = {"uploads": [(x.filename, x.save) for x in cups], "paths": cpaths, "hints": b.get("clip_hints", "")}
    try:
        jid = studio.create(b.get("url", "").strip(), mins, b.get("presenter", False), b.get("auto_approve", True), b.get("transcript", ""),
                            b.get("provider", ""), b.get("captions", True), b.get("mode", "both"), ssec,
                            f if (f and f.filename) else None, f.filename if f else "", b.get("src_title", ""), b.get("src_credit", ""),
                            b.get("visual_review") or config.load().get("visual_review_default", "never"), dbg_on=dbg_on, bps=bps, own_clips=own,
                            tts_engine=b.get("tts_engine", ""), audience=str(b.get("audience") or "").lower(),
                            newsroom=str(b.get("newsroom", "")).lower() in ("1", "true", "yes", "on"))   # Newsroom jobs queue ahead of hand jobs
    except ValueError as e: return jsonify(error=str(e)[:300]), 400
    return jsonify(id=jid)

# ---- house style learned from feedback (studio/style.py)
@app.get("/api/style")
def style_list():
    from studio import style
    return jsonify(rules=style.load(config.load()))

@app.post("/api/style")
def style_add():
    from studio import style
    b = request.get_json(silent=True) or {}
    try: return jsonify(rule=style.add(config.load(), b.get("rule", ""), b.get("area", "general")))
    except ValueError as e: return jsonify(error=str(e)), 400

@app.post("/api/style/learn")
def style_learn():
    from studio import style
    b = request.get_json(silent=True) or {}
    msgs = []
    try: r = style.learn(config.load(), b.get("note", ""), b.get("context", ""), b.get("job", ""), msgs.append)
    except ValueError as e: return jsonify(error=str(e)), 400
    except Exception as e: return jsonify(error="the script AI could not turn that into rules: " + " ".join(str(e).split())[:200]), 502
    return jsonify(**r)

@app.post("/api/style/import")
def style_import():
    from studio import style
    style.replace_all(config.load(), (request.get_json(silent=True) or {}).get("rules") or [])
    return jsonify(ok=True)

@app.delete("/api/style/<rid>")
def style_remove(rid):
    from studio import style
    return jsonify(ok=style.remove(config.load(), rid))

@app.post("/api/smoke")
def smoke():
    """Deprecated (the old fixed one-beat job is gone). Use POST /api/jobs with mode=smoke: the one smoke path."""
    return jsonify(error="Deprecated: start a smoke test with Make = 'Smoke test' (POST /api/jobs, mode=smoke)."), 410

# ---- visual review (Shorts)
def _interview(jid):
    """A job made from an interview edit (studio/interview_edit.py)."""
    from studio import interview_edit
    try: return interview_edit.is_interview(studio.job(jid).dir)
    except Exception: return False

def _ws(jid):
    """The review workspace: the job (Shorts) or job/longedit (long-video editing, ?space=long)."""
    d = studio.job(jid).dir
    return d / "longedit" if request.args.get("space") == "long" else d

def _rv_payload(jid):
    from studio import review
    rv = review.load(_ws(jid))
    if not rv: abort(404)
    return rv

@app.get("/api/jobs/<jid>/review")
def get_review(jid): return jsonify(_rv_payload(jid))

@app.post("/api/jobs/<jid>/review/<bid>")
def review_beat(jid, bid):
    from studio import review
    b = request.get_json(silent=True) or {}; a = b.get("action"); j = studio.job(jid); cfg = config.load(); ws = _ws(jid)
    try:
        if a in ("auto", "skip", "choose", "undo", "revert"):
            review.decide(ws, bid, a, b.get("cands") if a != "revert" else b.get("i"), cfg, j.log)
            j.log(f"Visual review {bid}: {a}" + (f" {', '.join(b.get('cands') or [])}" if a == "choose" else ""))
            from studio import debug as _dbg
            _dbg.trace(j.dir, {"ev": "decision", "beat": int(bid[1:]) + 1 if bid[1:].isdigit() else bid, "action": a,
                               "rungs": ", ".join(review.load(ws)["cands"][c]["rung"] for c in (b.get("cands") or []) if c in review.load(ws)["cands"]) if a == "choose" else ""})
        elif a == "supply" and _interview(jid):
            from studio import interview_edit; interview_edit.supply(j.dir, bid, b.get("src", "")); j.log(f"Edit {bid}: your file added")
        elif a == "supply": review.supply(ws, bid, b.get("src", ""), b.get("tag", ""), cfg, j.log); j.log(f"Visual review {bid}: your file added")
        elif _interview(jid): return jsonify(error="For an interview piece: pick a picture, supply a file, or ask in the chat."), 400
        elif a in ("expand", "refine", "animate"):
            err = review.start(studio, jid, bid, a, {"text": b.get("text", ""), "tag": b.get("tag", "")}, ws=ws)
            if err: return jsonify(error=err), 409
        else: return jsonify(error="unknown action"), 400
    except Exception as e: return jsonify(error=str(e)[:300]), 400
    return jsonify(_rv_payload(jid))

@app.post("/api/jobs/<jid>/review_all/<action>")
def review_all(jid, action):
    from studio import review
    j = studio.job(jid)
    try:
        if action == "approve_all": review.approve_all(j.dir); j.log("Visual review: approved the auto picks for all remaining beats")
        elif action != "continue": return jsonify(error="unknown action"), 400
        studio.continue_visuals(jid)
    except Exception as e: return jsonify(error=str(e)[:300]), 400
    return jsonify(ok=True)

@app.post("/api/jobs/<jid>/preview/<cid>")
def review_preview(jid, cid):
    from studio import review
    j = studio.job(jid)
    if _interview(jid):
        from studio import interview_edit
        try: return jsonify(interview_edit.preview_cand(j.dir, cid, request.args.get("space")))
        except Exception as e: return jsonify(error=str(e)[:300]), 400
    try: return jsonify(review.preview(_ws(jid), cid, config.load(), j.log))
    except Exception as e: return jsonify(error=str(e)[:300]), 400

# ---- post-render editing (every output type)
@app.get("/api/jobs/<jid>/edit/beats")
def edit_beats(jid):
    from studio import edit
    j = studio.job(jid)
    try: out = edit.beats(j.dir)
    except Exception as e: return jsonify(error=str(e)[:300], kind=None, beats=[])
    k = str(j.dir); out.update(busy=edit.status(j.dir), error=edit._busy.get(k + ":err", ""), edits=j.state.get("edits", []),
                                 undo=edit.can_undo(j.dir), history=edit.history(j.dir) if edit.v2() else [], outputs=edit.outputs(j.dir),
                                 target=edit.kind(j.dir), last=j.state.get("edit_last"))
    return jsonify(out)

def _editor_ns():
    return None if VS_PORT == 42021 else str(VS_PORT)

def _editor_owner(jid, sid):
    from studio import editor_session
    st = editor_session.state(namespace=_editor_ns())
    if not st:
        return False, "No editor session is open; open a beat first."
    if st.get("jid") != jid or not editor_session.is_owner(jid, os.getpid(), VS_PORT, sid, namespace=_editor_ns()):
        return False, f"Waiting: editor in use ({st.get('jid')})"
    return True, st

@app.post("/api/jobs/<jid>/edit/target")
def edit_target(jid):
    """A job with a Short and an explainer: which one the timeline editor works on (short | long)."""
    from studio import edit
    j = studio.job(jid); b = request.get_json(silent=True) or {}
    try: edit.set_target(j.dir, b.get("target", ""))
    except Exception as e: return jsonify(error=str(e)[:300]), 400
    return jsonify(ok=True, target=edit.kind(j.dir))

@app.post("/api/jobs/<jid>/edit/open/<bid>")
def edit_open(jid, bid):
    from studio import edit, editor_session
    j = studio.job(jid)
    b = request.get_json(silent=True) or {}
    sid = b.get("sid", "")
    ed = editor_session.acquire(jid, pid=os.getpid(), port=VS_PORT, sid=sid, namespace=_editor_ns())
    try: rv = edit.open_beat(j.dir, bid, config.load(), j.log)
    except Exception as e: return jsonify(error=str(e)[:300]), 400
    return jsonify(space="short" if edit.kind(j.dir) == "short" else "long", rv=rv,
                   editor={"ok": ed.get("ok", False), "waiting": ed.get("waiting", False),
                           "holder_jid": ed.get("holder_jid"), "holder_port": ed.get("holder_port"),
                           "age": ed.get("age", 0)})

@app.post("/api/jobs/<jid>/edit/chat")
def edit_chat(jid):
    """The pause chat, inside the timeline editor of a finished job (same routing and actions + "apply")."""
    from studio import debug
    b = request.get_json(silent=True) or {}; text = (b.get("text") or "").strip()
    if not text or not b.get("beat"): return jsonify(error="type a message (and open a beat)"), 400
    if _interview(jid):
        from studio import interview_edit
        try: return jsonify(interview_edit.chat(studio.job(jid).dir, b["beat"], text, config.load()))
        except Exception as e: return jsonify(error=str(e)[:300]), 500
    try: return jsonify(debug.chat(studio, jid, b["beat"], text, config.load(), edit=True))
    except Exception as e: return jsonify(error=str(e)[:300]), 500

@app.get("/api/jobs/<jid>/edit/chat")
def edit_chat_log(jid):
    j = studio.job(jid); bid = request.args.get("beat")
    return jsonify(chat=[e for e in (j.state.get("debug") or {}).get("chat", []) if not bid or e.get("beat") == bid])

@app.post("/api/jobs/<jid>/edit/<action>/<bid>")
def edit_act(jid, action, bid):
    from studio import edit, gpu_lock
    j = studio.job(jid); b = request.get_json(silent=True) or {}; cfg = config.load()
    sid = b.get("sid", "")
    ok, holder = _editor_owner(jid, sid)
    if not ok:
        return jsonify(error=holder), 409
    try:
        if action == "preview":
            with gpu_lock.holder(desc=f"editor-preview:{jid}:{bid}"):
                return jsonify(edit.preview(j.dir, bid, b.get("cands") or [], b.get("fit", "auto"), cfg, j.log))
        if action == "apply":
            err = edit.start_apply(j.dir, bid, b.get("cands") or [], b.get("fit", "auto"), cfg, j.log)
            return (jsonify(error=err), 409) if err else jsonify(ok=True)
    except Exception as e:
        return jsonify(error=str(e)[:300]), 400
    return jsonify(error="unknown action"), 400

@app.post("/api/jobs/<jid>/edit_all/<action>")
def edit_all(jid, action):
    from studio import edit, review, gpu_lock
    j = studio.job(jid)
    b = request.get_json(silent=True) or {}
    sid = b.get("sid", "")
    try:
        if action == "undo":
            ok, holder = _editor_owner(jid, sid)
            if not ok:
                return jsonify(error=holder), 409
            with gpu_lock.holder(desc=f"editor-undo:{jid}"):
                edit.undo(j.dir, j.log)
        elif action == "rerender":
            ok, holder = _editor_owner(jid, sid)
            if not ok:
                return jsonify(error=holder), 409
            studio.rerender(jid, str(b.get("target") or ""), bool(b.get("refresh_fallbacks")), editor_owned=True)
        elif action == "cleanup":
            review.prune(j.dir, j.log, full=True)
            if (j.dir / "longedit").exists(): review.prune(j.dir / "longedit", j.log, full=True)
        else: return jsonify(error="unknown action"), 400
    except Exception as e: return jsonify(error=str(e)[:300]), 400
    return jsonify(ok=True)

@app.get("/api/jobs/<jid>/thumbnail")
def get_thumb(jid):
    from studio import thumb916
    return jsonify(thumb916.options(studio.job(jid).dir))

@app.post("/api/jobs/<jid>/thumbnail")
def set_thumb(jid):
    from studio import thumb916
    j = studio.job(jid); b = request.get_json(silent=True) or {}
    try:
        if b.get("approve"):
            o = thumb916.options(j.dir); o["approved"] = True
            (j.dir / "short" / "thumb.json").write_text(json.dumps(o, indent=1), encoding="utf-8"); j.log("Thumbnail approved"); return jsonify(o)
        opts = {k: b.get(k) for k in ("beat", "size", "color", "text")}
        if b.get("src"):   # your own picture (a path on this PC or a URL)
            from studio import review
            src = b["src"].strip().strip('"')
            if src.lower().startswith("http"):
                import requests
                r = requests.get(src, timeout=60, headers={"User-Agent": "VideoStudio/1.0"})
                if r.status_code != 200 or "text/html" in r.headers.get("content-type", ""): raise RuntimeError("couldn't download that image")
                p = j.dir / "short" / "thumb_src.jpg"; p.write_bytes(r.content); src = str(p)
            opts["image"] = src
        elif "beat" in b and b.get("beat"): opts["image"] = ""
        thumb916.make(j.dir, j.short_plan(), config.load(), j.log, opts)
        return jsonify(thumb916.options(j.dir))
    except Exception as e: return jsonify(error=str(e)[:300]), 400

@app.get("/api/jobs/<jid>")
def job(jid):
    j = studio.job(jid)
    if not j.dir.exists(): abort(404)
    s = j.state; s["id"] = jid
    lp = j.dir / "log.txt"; s["log"] = lp.read_text(encoding="utf-8").splitlines()[-60:] if lp.exists() else []
    s["stages"] = stages_for(s.get("mode", "long"))
    sp = j.short_plan()
    if sp: s["short_summary"] = {"title": sp["title"], "beats": len(sp["sections"]), "words": sum(len(x["vo"].split()) for x in sp["sections"])}
    pl = j.plan()
    if pl: s["plan_summary"] = {"title": pl["title"], "sections": [{"id": x["id"], "title": x["title"], "words": len(x["vo"].split()), "visuals": len(x["visuals"])} for x in pl["sections"]]}
    return jsonify(s)

@app.get("/api/jobs/<jid>/plan")
def get_plan(jid): return jsonify(studio.job(jid).plan() or {})
@app.put("/api/jobs/<jid>/plan")
def put_plan(jid):
    from studio.writer import normalize
    studio.job(jid).save_plan(normalize(request.json)); studio.job(jid).log("Script edited in the web page"); return jsonify(ok=True)

@app.get("/api/jobs/<jid>/short_plan")
def get_short_plan(jid): return jsonify(studio.job(jid).short_plan() or {})
@app.put("/api/jobs/<jid>/short_plan")
def put_short_plan(jid):
    p = studio.job(jid).short_plan(); new = request.json or {}
    if not p: abort(404)
    p["title"] = new.get("title", p["title"])
    for a, b in zip(p["sections"], new.get("sections", [])):
        if isinstance(b.get("vo"), str) and b["vo"].strip(): a["vo"] = " ".join(b["vo"].split())
    studio.job(jid).save_short_plan(p); studio.job(jid).log("Short script edited in the web page"); return jsonify(ok=True)

@app.post("/api/jobs/<jid>/transcript")
def paste_transcript(jid):
    t = ((request.get_json(silent=True) or {}).get("text") or "").strip()
    if len(t.split()) < 50: return jsonify(error="That transcript is too short (need at least 50 words)."), 400
    studio.set_transcript(jid, t); return jsonify(ok=True)

# ---- debugger: breakpoints, Pause now, the debug switch, inspect, thumbnails, panel chat
@app.post("/api/jobs/<jid>/pause")
def job_pause(jid):
    if not studio.request_pause(jid): return jsonify(error="the job isn't running"), 400
    return jsonify(ok=True)

def _dbg_payload(jid):
    from studio import debug
    j = studio.job(jid); s = j.state; d = dict(s.get("debug") or {}); d.pop("checked", None)
    return {"status": s.get("status"), "stage": s.get("stage"), "pause": s.get("pause"), "pause_req": bool(s.get("pause_req")), "debug": d,
            "chains": debug.chains(j.dir), "trace": (j.dir / "trace.md").exists()}

@app.get("/api/jobs/<jid>/debug")
def get_debug(jid): return jsonify(_dbg_payload(jid))

@app.post("/api/jobs/<jid>/debug")
def set_debug(jid):
    from studio import debug
    b = request.get_json(silent=True) or {}; d = studio.job(jid).state.get("debug") or {}
    try:
        bps = None
        if "bps" in b: bps = debug.parse_all(b["bps"])
        if b.get("add"): bps = list(dict.fromkeys((bps if bps is not None else d.get("bps", [])) + [debug.parse(b["add"])]))
        if b.get("remove") is not None: bps = [x for x in (bps if bps is not None else d.get("bps", [])) if x != b["remove"]]
    except ValueError as e: return jsonify(error=str(e)), 400
    studio.set_debug(jid, on=b.get("on"), bps=bps, bps_off=b.get("bps_off"))
    return jsonify(_dbg_payload(jid))

@app.post("/api/jobs/<jid>/debug/thumbs")
def debug_thumbs(jid):
    """Generate thumbnails: coarse stills of every treatment in flight for the beat (stock, rejected stock, photos, stills, parallax...)."""
    from studio import review
    b = request.get_json(silent=True) or {}; bid = b.get("beat"); j = studio.job(jid); cfg = config.load()
    rv = review.load(j.dir)
    if not rv or bid not in rv.get("beats", {}):
        try: review.collect(j.dir, j.short_plan(), cfg, j.log, j.state.get("visual_review", "auto"), debug_beats=[bid]); rv = review.load(j.dir)
        except Exception as e: return jsonify(error=f"no treatments for this beat yet ({str(e)[:120]})"), 400
    cids = rv["beats"][bid]["cands"] if bid in rv.get("beats", {}) else []
    review.thumbs(j.dir, cfg, j.log, cids); j.log(f"Debug: thumbnails for {bid} ({len(cids)} treatments)")
    return jsonify(review.load(j.dir))

@app.post("/api/jobs/<jid>/debug/chat")
def debug_chat(jid):
    from studio import debug
    b = request.get_json(silent=True) or {}; text = (b.get("text") or "").strip()
    if not text or not b.get("beat"): return jsonify(error="type a message (and pick a beat)"), 400
    try: return jsonify(debug.chat(studio, jid, b["beat"], text, config.load()))
    except Exception as e: return jsonify(error=str(e)[:300]), 500

@app.post("/api/jobs/<jid>/debug/<action>")
def debug_action(jid, action):
    from studio import review, debug
    b = request.get_json(silent=True) or {}; j = studio.job(jid)
    if action == "skip":   # Skip step: this beat gets its headline card, then go on
        if b.get("beat"):
            review.decide(j.dir, b["beat"], "skip"); j.log(f"Debug: {b['beat']} skipped (headline card)")
            debug.trace(j.dir, {"ev": "skip", "beat": int(b["beat"][1:]) + 1})
        studio.resume(jid)
    elif action == "abort": studio.abort(jid)
    else: abort(404)
    return jsonify(ok=True)

@app.post("/api/jobs/<jid>/<action>")
def act(jid, action):
    if action == "stop": return jsonify(ok=True, state=studio.cancel_job(jid))   # Stop video: next safe point
    {"approve": studio.approve, "resume": studio.resume}[action](jid); return jsonify(ok=True)

@app.get("/api/jobs/<jid>/outputs")
def job_outputs(jid):
    """What a remote dispatcher (the Newsroom) copies back: output/ files plus the plans and the render timelines."""
    d = studio.job(jid).dir
    if not d.exists(): abort(404)
    out = [f"output/{f.name}" for f in sorted((d / "output").glob("*")) if f.is_file() and not f.name.startswith("_")] if (d / "output").is_dir() else []
    extra = [r for r in ("plan.json", "short/plan.json", "state.json", "short/public/teaser.json", "build/public/teaser.json") if (d / r).is_file()]
    return jsonify(files=out + extra)

@app.get("/files/<jid>/<path:p>")
def files(jid, p):
    d = studio.job(jid).dir.resolve(); f = (d / p).resolve()
    if d not in f.parents or not f.exists(): abort(404)
    return send_from_directory(f.parent, f.name)

# ---- /make: describe a video in plain English
@app.get("/make")
def make_page(): return send_from_directory(app.static_folder, "make.html")

@app.post("/make/parse")
def make_parse():
    from studio import make
    body = request.get_json(silent=True) or {}
    t = (body.get("text") or "").strip()
    if not t: return jsonify(error="Describe the video first."), 400
    audience = str(body.get('audience') or '').lower()
    if audience and audience not in make.AUDIENCE: return jsonify(error='Unknown audience'), 400
    return jsonify(make.parse(t, config.load(), audience=audience))

@app.get("/make/model")
def make_model():
    from studio import make
    m, why = make.model_status(config.load())
    return jsonify(model=m, problem=why, pull=make._pull["state"])

@app.get("/make/status")
def make_status():
    jid = request.args.get("job", "")
    j = studio.job(jid)
    if not jid or not j.dir.exists(): return jsonify(error="no such job"), 404
    s = j.state; lp = j.dir / "log.txt"
    out = {k: s.get(k) for k in ("status", "stage", "error", "title", "mode", "short_output", "output", "thumbnail", "edits")}
    out.update(id=jid, done=s.get("done", []), stages=stages_for(s.get("mode", "long")), current=studio.current,
               log=lp.read_text(encoding="utf-8").splitlines()[-25:] if lp.exists() else [])
    return jsonify(out)

@app.get("/make/saved")
def make_saved():
    from studio import make
    return jsonify(make.saved())

@app.post("/make/save")
def make_save():
    from studio import make
    b = request.get_json(silent=True) or {}
    if not b.get("name") or not isinstance(b.get("spec"), dict): return jsonify(error="name and spec needed"), 400
    return jsonify(make.save(b["name"], b["spec"], b.get("description", "")))

@app.delete("/make/saved/<name>")
def make_saved_delete(name):
    from studio import make
    return jsonify(make.delete(name))

@app.post("/make/runner")
def make_runner():
    from studio import make
    b = request.get_json(silent=True) or {}
    rid, err = make.runner_start(b.get("spec"), b.get("click_make", False), b.get("edit"), os.environ.get("PORT"))
    return (jsonify(error=err), 409) if err else jsonify(id=rid)

@app.get("/make/runner")
def make_runner_status():
    from studio import make
    return jsonify(make.runner_status(request.args.get("id")))

@app.post("/make/runner/cancel")
def make_runner_cancel():
    from studio import make
    return jsonify(cancelled=make.runner_cancel())

@app.get("/make/shots/<rid>/<name>")
def make_shot(rid, name):
    from studio import make
    d = (make.shots_root() / rid).resolve()
    if make.shots_root().resolve() not in d.parents: abort(404)
    return send_from_directory(d, name)

@app.get("/api/jobs/<jid>/editor")
def editor_status(jid):
    from studio import editor_session, gpu_lock
    sid = request.args.get("sid", "")
    st = editor_session.state(namespace=_editor_ns())
    return jsonify(
        active=bool(st),
        owner=bool(st and editor_session.is_owner(jid, os.getpid(), VS_PORT, sid, namespace=_editor_ns())),
        holder_jid=st.get("jid") if st else None,
        holder_port=st.get("port") if st else None,
        age=st.get("age", 0) if st else 0,
        active_applies=st.get("active_applies", 0) if st else 0,
        lock=gpu_lock.status(),
    )

@app.post("/api/jobs/<jid>/editor/heartbeat")
def editor_heartbeat(jid):
    from studio import editor_session
    b = request.get_json(silent=True) or {}
    rv = editor_session.heartbeat(
        jid, os.getpid(), VS_PORT, b.get("sid", ""),
        b.get("active_applies"), namespace=_editor_ns(),
    )
    return jsonify(ok=rv.get("ok", False), error=rv.get("error"))

@app.post("/api/jobs/<jid>/editor/close")
def editor_close(jid):
    from studio import editor_session
    b = request.get_json(silent=True) or {}
    editor_session.release(
        jid, pid=os.getpid(), port=VS_PORT,
        sid=b.get("sid", ""), namespace=_editor_ns(),
    )
    return jsonify(ok=True)

@app.post("/make/edit")
def make_edit():
    from studio import edit
    b = request.get_json(silent=True) or {}; j = studio.job(b.get("job", ""))
    if not j.dir.exists(): return jsonify(error="no such job"), 404
    sid = b.get("sid", "")
    ok, holder = _editor_owner(b.get("job", ""), sid)
    if not ok:
        return jsonify(error=holder), 409
    err = edit.start_apply(j.dir, b.get("beat", ""), b.get("cands") or [], b.get("fit", "auto"), config.load(), j.log)
    return (jsonify(error=err), 409) if err else jsonify(ok=True)

def _power():
    """On the Linux worker: is it on AC power? (it only takes jobs plugged in). Elsewhere: None."""
    import glob
    for f in glob.glob("/sys/class/power_supply/*/online"):
        try: return {"ac": open(f).read().strip() == "1"}
        except OSError: pass
    return None

# Network worker mode (the Linux laptop): VS_HOST=0.0.0.0 with VS_TOKEN; every request from another machine must carry
# the token (X-VS-Token header or ?k=). Without VS_TOKEN the server stays on 127.0.0.1 only.
@app.before_request
def _worker_guard():
    tok = os.environ.get("VS_TOKEN", "")
    if not tok or request.remote_addr in ("127.0.0.1", "::1"): return None
    if request.headers.get("X-VS-Token") == tok or request.args.get("k") == tok: return None
    return jsonify(error="token required"), 403

def free_port(p):
    for q in range(p, p + 50):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", q)) != 0: return q
    return p

if __name__ == "__main__":
    # fixed address http://127.0.0.1:42020 (PORT overrides); if it's taken, the next free port is used and printed
    want = int(os.environ.get("PORT") or 42020)
    port = want if os.environ.get("WERKZEUG_RUN_MAIN") else free_port(want)   # the reloader's child must reuse the parent's port
    os.environ["PORT"] = str(port)
    if port != want: print(f"Port {want} is busy; using {port} instead", flush=True)
    print(f"Video Studio running on http://127.0.0.1:{port}", flush=True)
    # VS_RELOAD=1: restart automatically when a .py file changes (development only - it also stops a running render;
    # the job is then marked stopped and Resume continues it)
    reload = os.environ.get("VS_RELOAD") == "1"
    host = os.environ.get("VS_HOST", "127.0.0.1") if os.environ.get("VS_TOKEN") else "127.0.0.1"
    app.run(host=host, port=port, debug=False, threaded=True, use_reloader=reload)
