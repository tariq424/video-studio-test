"""Job queue: one job renders at a time (single GPU). Each stage is resumable."""
import json, os, threading, time, traceback, re, shutil, datetime, queue
from pathlib import Path
from . import config, transcript, writer, render, assemble, media, sources, short, debug, gpu_lock
from .wangp import WanGP

STAGES = ["transcript", "script", "short_script", "review", "short_stock", "short_voice", "short_fallback", "short_review", "short_render",
          "charts", "voice", "captions", "broll", "presenter", "motion", "stills", "assemble"]
LONG = {"script", "charts", "voice", "captions", "broll", "presenter", "motion", "stills", "assemble"}
SHORT = {"short_script", "short_stock", "short_voice", "short_fallback", "short_review", "short_render"}
def stages_for(mode): return [s for s in STAGES if not ((mode == "short" and s in LONG) or (mode == "long" and s in SHORT))]

SMOKE_SECS = 30.0   # "smoke test" Shorts: about 75 words of narration including the closing line

GPU_STAGES = {"charts", "voice", "captions", "presenter", "motion", "stills", "assemble", "broll",
              "short_stock", "short_voice", "short_fallback", "short_review", "short_render"}   # every render stage (Claude: the draft left out short_render/assemble/charts)


class _StudioQueue:
    """Priority queue: editor-owned work, then Newsroom jobs, then hand jobs.

    Existing `Studio.q.put(jid)` call sites stay unchanged.
    """
    def __init__(self, studio):
        self._q = queue.PriorityQueue()
        self._studio = studio
        self._seq = 0
        self._lk = threading.Lock()

    def put(self, jid):
        with self._lk:
            self._seq += 1
            self._q.put((self._studio._prio(jid), self._seq, jid))

    def get(self):
        return self._q.get()[2]


LENGTH_TOL = 0.10   # a finished video more than 10% off the requested length is flagged (never rejected)

def _length_check(j, out, target, what, log):
    """After a render: warn (log + job page) when the video misses the requested length by more than LENGTH_TOL."""
    try:
        from . import media
        got, target = media.dur(out), float(target or 0)
        if target <= 0: return
        off = (got - target) / target
        warns = [w for w in (j.state.get("length_warnings") or []) if not w.startswith(what + ":")]
        # length policy (2026-10-14): shorter or longer than requested is fine; only a Short past 3:00 or an explainer past the
        # sanity ceiling (25 min for 15, x1.67) is an anomaly
        ceil = 180.0 if what == "Short" else target * 25 / 15
        if got > ceil + 0.5:
            w = f"{what}: {got:.0f}s vs {target:.0f}s requested ({off:+.0%}); over the {ceil:.0f}s maximum"
            log(f"WARNING: length anomaly. {w}"); warns.append(w)
        else: log(f"Length check: {what} {got:.0f}s vs {target:.0f}s requested ({off:+.0%}); within the {ceil:.0f}s maximum, OK")
        j.save(length_warnings=warns)
    except Exception as e: log(f"  length check skipped ({str(e)[:120]})")


SHORT_STAGES = {"short_script", "short_stock", "short_voice", "short_fallback", "short_review", "short_render"}
LONG_STAGES = {"script", "charts", "voice", "captions", "broll", "presenter", "motion", "stills", "assemble"}

def output_of(st):
    return "short" if st in SHORT_STAGES else "explainer" if st in LONG_STAGES else "both"

def progress(job, n, of):
    """Beat / section counter for the job page ("Explainer: voice - Beat 7 of 16"). Never raises."""
    try:
        j = Job(Path(job)); p = dict(j.state.get("prog") or {}); p.update(n=int(n), of=int(of)); j.save(prog=p)
    except Exception: pass

_slocks, _slocks_lk = {}, threading.Lock()
def _state_lock(d):
    with _slocks_lk: return _slocks.setdefault(str(d), threading.RLock())

class Job:
    def __init__(self, path): self.dir = Path(path)
    @property
    def state(self):
        p = self.dir / "state.json"
        for i in range(20):   # another thread may be replacing it right now: retry briefly instead of reading half a file
            if not p.exists(): return {}
            try: return json.loads(p.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                if i == 19: raise
                time.sleep(0.05)
    def save(self, **kw):
        with _state_lock(self.dir):
            s = self.state; s.update(kw); s["updated"] = time.time()
            p = self.dir / "state.json"; tmp = p.with_name(f"state.{threading.get_ident()}.tmp")
            tmp.write_text(json.dumps(s, indent=1), encoding="utf-8")
            for i in range(20):   # atomic swap (Windows refuses while a reader has the file open: retry)
                try: os.replace(tmp, p); break
                except PermissionError:
                    if i == 19: raise
                    time.sleep(0.05)
    def log(self, msg):
        line = f"[{datetime.datetime.now():%H:%M:%S}] {msg}"
        with open(self.dir / "log.txt", "a", encoding="utf-8") as f: f.write(line + "\n")
    def plan(self):
        p = self.dir / "plan.json"; return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    def save_plan(self, plan): (self.dir / "plan.json").write_text(json.dumps(plan, indent=1), encoding="utf-8")
    def short_plan(self):
        p = self.dir / "short" / "plan.json"; return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    def save_short_plan(self, plan):
        (self.dir / "short").mkdir(exist_ok=True); (self.dir / "short" / "plan.json").write_text(json.dumps(plan, indent=1), encoding="utf-8")

class Studio:
    def __init__(self, port=None):
        self.port = port
        self.live = port in (None, "42021", 42021)
        self.q = _StudioQueue(self)
        self.current = None; self.cancel = set()
        self._editor_waits = {}
        self._editor_waits_lk = threading.Lock()
        if not self.live:
            self._refuse_live_jobs_dir()
        try:   # jobs cut off by an app restart or PC reboot: show them as stopped (press Resume) instead of a stale "running"
            for d in self.jobs_dir().iterdir():
                if d.is_dir() and (d / "state.json").exists():
                    j = Job(d)
                    if j.state.get("status") in ("running", "queued"):
                        j.save(status="stopped"); j.log("Interrupted (the app or PC restarted). Press Resume to continue; finished work is kept.")
        except Exception: pass
        threading.Thread(target=self._editor_wait_watcher, daemon=True).start()
        threading.Thread(target=self._worker, daemon=True).start()

    def jobs_dir(self): d = Path(config.load()["jobs_dir"]); d.mkdir(parents=True, exist_ok=True); return d
    def job(self, jid): return Job(self.jobs_dir() / jid)
    def list(self):
        out = []
        for d in sorted(self.jobs_dir().iterdir(), reverse=True):
            if d.is_dir() and (d / "state.json").exists(): s = Job(d).state; s["id"] = d.name; out.append(s)
        return out

    def _prio(self, jid):
        try:
            s = self.job(jid).state
        except Exception:
            return 2
        if s.get("editor_owned"):
            return 0
        if s.get("newsroom") or s.get("priority") == "newsroom":
            return 1
        return 2

    def _enqueue(self, jid):
        self.q.put(jid)

    def _refuse_live_jobs_dir(self):
        live_settings = Path(r"F:\code\video-studio-test\settings.json")
        if not live_settings.exists():
            return
        try:
            import json as _json
            live_jobs = os.path.normpath(str(_json.loads(live_settings.read_text(encoding="utf-8")).get("jobs_dir", "")))
            my_jobs = os.path.normpath(str(config.load().get("jobs_dir", "")))
            if live_jobs and my_jobs == live_jobs:
                raise RuntimeError(f"Refusing to start this copy: it points at the live jobs_dir ({live_jobs})")
        except RuntimeError:
            raise
        except Exception:
            pass

    def _wait_editor_reservation(self, j, s, log, jid):
        from . import editor_session
        res = editor_session.active()
        if not res:
            return False

        label = f"Waiting: editor in use ({res.get('jid')})"
        if s.get("status") != "paused" or (s.get("pause") or {}).get("label") != label:
            j.save(status="paused", pause={"kind": "editor_wait", "label": label,
                                          "stage": s.get("stage"), "where": s.get("stage")}, pause_req=False)
            j.log(label + f" (holder pid {res.get('pid')}, port {res.get('port')}); it will continue automatically when the editor session releases.")
            with self._editor_waits_lk:
                self._editor_waits[jid] = time.time()
        return True

    def _requeue_editor_waits(self):
        from . import editor_session
        if editor_session.active():
            return

        with self._editor_waits_lk:
            waits = list(self._editor_waits.items())
            self._editor_waits.clear()

        for jid, _ in waits:
            try:
                job = self.job(jid)
            except Exception:
                continue
            if job.state.get("status") == "paused" and (job.state.get("pause") or {}).get("kind") == "editor_wait":
                job.save(status="queued", pause=None, pause_req=False, cancel_req=False, cancelled=False)
                job.log("Editor session released; continuing automatically.")
                self._enqueue(jid)

    def _editor_wait_watcher(self):
        while True:
            time.sleep(1.0)
            try:
                self._requeue_editor_waits()
            except Exception:
                pass

    def create(self, url, minutes, presenter=False, auto_approve=False, transcript_text="", provider="", captions=True,
               mode="both", short_secs=165, upload=None, upload_name="", src_title="", src_credit="", visual_review="auto", dbg_on=False, bps=None,
               own_clips=None, tts_engine="", audience="", newsroom=False):
        smoke = mode == "smoke"   # pipeline check: a ~30-second Short (about 75 words); real Shorts keep the 2:00 minimum
        if smoke: mode, short_secs = "short", SMOKE_SECS
        jid = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        j = self.job(jid); j.dir.mkdir(parents=True); (j.dir / "src").mkdir()
        up = ""
        if upload is not None:
            up = re.sub(r"[^A-Za-z0-9._ -]+", "_", upload_name or "upload")[:80]; upload.save(str(j.dir / "src" / up))
        elif transcript_text.strip():
            (j.dir / "src" / ("transcript_manual.txt" if url else "pasted.txt")).write_text(transcript_text, encoding="utf-8")
        j.save(url=url, minutes=float(minutes), presenter=bool(presenter), captions=bool(captions), auto_approve=bool(auto_approve), provider=provider or "",
               mode=mode if mode in ("long", "short", "both") else "both", short_secs=SMOKE_SECS if smoke else max(120.0, min(176.0, float(short_secs))), smoke=smoke,
               upload=up, src_title=src_title, src_credit=src_credit, visual_review=visual_review if visual_review in ("auto", "every", "never") else "auto", status="queued", stage="transcript", done=[], title="", created=time.time(),
               newsroom=bool(newsroom), priority=("newsroom" if newsroom else "normal"),
               debug={"on": bool(dbg_on), "bps": list(bps or []), "bps_off": False, "checked": [], "chat": []}, trace=bool(dbg_on))
        if dbg_on: debug.trace(j.dir, {"ev": "debug on", "at": "job start", "breakpoints": "; ".join(bps or []) or "none"})
        if own_clips:   # your footage + where it goes (clips.py places it after the script is written)
            from . import clips
            try: mc = clips.save(j.dir, own_clips.get("uploads") or [], own_clips.get("paths") or [], own_clips.get("hints", ""), j.log)
            except Exception:
                shutil.rmtree(j.dir, ignore_errors=True); raise
            j.save(my_clips=mc); j.log(f"Your clips: {len(mc)} file(s)" + (" with a placement note" if (own_clips.get("hints") or "").strip() else ""))
        if tts_engine in ("kokoro", "wanGP"): j.save(tts_engine=tts_engine)
        if audience in writer.AUDIENCE: j.save(audience=audience)
        what = url or (f"file {up}" if up else "pasted text")
        j.log(f"Job created for {what} (output: {'SMOKE TEST, ' if smoke else ''}{mode}; long {minutes} min, short {short_secs:.0f}s)"); self._enqueue(jid); return jid

    def approve(self, jid):
        j = self.job(jid); s = j.state
        if s.get("status") == "awaiting_review":
            d = s.get("done", []); d.append("review"); j.save(done=d, status="queued"); j.log("Script approved"); self._enqueue(jid)
    def continue_visuals(self, jid):
        """Visual review finished (every beat decided): render."""
        from . import review
        j = self.job(jid); review.close(j.dir)
        d = j.state.get("done", [])
        if "short_review" not in d: d.append("short_review")
        j.save(done=d, status="queued"); j.log("Visual review done; rendering"); self._enqueue(jid)

    def rerender(self, jid, target="", refresh_fallbacks=False, editor_owned=False):
        """Full re-render on request (post-render edits are kept: Shorts from the review decisions, long videos from edit_clip).
        A job with both outputs re-renders the one being edited (edit_target), or `target` ("short" | "long").
        refresh_fallbacks (explainer): shots that fell to a headline text card (e.g. the script AI was unreachable) go down the
        visual ladder again (graphics -> simulation -> illustration -> headline), and caption emoji that weren't picked are picked
        again, before the explainer is rendered."""
        j = self.job(jid); s = j.state
        target = target or ("long" if s.get("edit_target") == "long" or refresh_fallbacks else "")
        st = "assemble" if (target == "long" and s.get("output")) or not s.get("short_output") else "short_render"
        if refresh_fallbacks and st == "assemble": j.save(refresh_fallbacks=True)
        if st == "assemble":
            for p in (j.dir / "build").glob("sec_*.mp4"): p.unlink(missing_ok=True)
        d = [x for x in j.state.get("done", []) if x != st]
        shutil.rmtree(j.dir / "edit" / "history", ignore_errors=True)   # step-by-step undo can't cross a full re-render
        if editor_owned:
            j.save(editor_owned=True)
        j.save(done=d, status="queued"); j.log("Full re-render requested"); self._enqueue(jid)

    def resume(self, jid):
        j = self.job(jid); self.cancel.discard(jid)
        was = j.state.get("pause") if j.state.get("status") == "paused" else None
        j.save(status="queued", error="", pause=None, pause_req=False, cancel_req=False, cancelled=False); j.log("Resumed"); self._enqueue(jid)
        if was: debug.trace(j.dir, {"ev": "resume", "from": was.get("label", "")})

    def request_pause(self, jid):
        """'Pause now': stop at the next safe point (never inside a render or a generation)."""
        j = self.job(jid)
        if j.state.get("status") not in ("running", "queued"): return False
        j.save(pause_req=True); j.log("Pause requested: stopping at the next safe point"); return True

    def set_debug(self, jid, on=None, bps=None, bps_off=None):
        j = self.job(jid); d = j.state.get("debug") or {"on": False, "bps": [], "bps_off": False, "checked": [], "chat": []}
        s = j.state; p = s.get("pause") or {}
        where = f"Beat {p['n']}" if p.get("n") else (s.get("stage") or "")
        if on is not None and bool(on) != bool(d.get("on")):
            d["on"] = bool(on); j.save(debug=d)
            if on and not s.get("trace"): j.save(trace=True)
            debug.trace(j.dir, {"ev": "debug " + ("on" if on else "off"), "at": where, "status": s.get("status")}, force=bool(on))
            j.log(f"Debug mode {'on' if on else 'off'} for the rest of this run")
        if bps is not None:
            d["bps"] = list(bps); j.save(debug=d); debug.trace(j.dir, {"ev": "breakpoints", "list": "; ".join(bps) or "none"})
        if bps_off is not None:
            d["bps_off"] = bool(bps_off); j.save(debug=d); debug.trace(j.dir, {"ev": "breakpoints " + ("disabled" if bps_off else "enabled"), "at": where})
        debug.render_md(j.dir)
        return j.state.get("debug")

    def abort(self, jid):
        j = self.job(jid)
        if j.state.get("status") in ("running", "queued"): self.stop(jid); return
        j.save(status="stopped", pause=None, pause_req=False); j.log("Aborted"); debug.trace(j.dir, {"ev": "abort"}); debug.render_md(j.dir)
    def stop(self, jid): self.cancel.add(jid); self.job(jid).log("Stop requested")   # hard stop (Abort): interrupts WanGP / Remotion

    def cancel_job(self, jid):
        """'Stop video': cancel at the next safe point (before a stage, between AI stills, after a beat - never inside a render or
        a generation). State stays on disk; the job ends as "stopped" (cancelled) and Resume continues from where it stopped."""
        j = self.job(jid); st = j.state.get("status")
        if st == "running":
            j.save(pause_req=True, cancel_req=True); j.log("Stop video: stopping at the next safe point (never inside a render or a generation)")
            return "stopping"
        if st in ("queued", "paused", "awaiting_visuals", "awaiting_review"):
            j.save(status="stopped", pause=None, pause_req=False, cancel_req=False, cancelled=True); j.log("Cancelled (Stop video). Resume continues from here.")
            return "stopped"
        return st or "unknown"

    def _worker(self):
        while True:
            jid = self.q.get()
            try: self._run(jid)
            except Exception as e:
                j = self.job(jid); j.log("ERROR: " + str(e)); j.log(traceback.format_exc()[-1500:])
                n = int(j.state.get("auto_retries", 0))
                rendering = j.state.get("stage") in ("charts", "voice", "captions", "presenter", "motion", "stills", "assemble", "broll", "short_stock", "short_voice", "short_fallback", "short_review", "short_render")
                if jid in self.cancel and "cancelled" in str(e):   # hard stop (Abort) interrupted a step: stopped, not an error
                    self.cancel.discard(jid); j.save(status="stopped", cancelled=True); j.log("Stopped")
                elif rendering and n < 3 and jid not in self.cancel:
                    j.save(status="queued", error="", auto_retries=n + 1)
                    j.log(f"Retrying automatically in 60s (attempt {n + 1} of 3); finished work is kept")
                    threading.Timer(60, lambda jid=jid: self._enqueue(jid)).start()
                else:
                    j.save(status="error", error=str(e)[:500])
            finally:
                self.current = None
                try:   # a job never leaves an on-demand WanGP holding VRAM (error, cancel or success)
                    from . import wangp as _wangp; _wangp.release(print, "job ended")
                except Exception: pass
                try:
                    gpu_lock.release()
                except Exception:
                    pass

    # ---- YouTube transcripts without hammering YouTube: reuse what we have, respect a cooldown after a block
    YT_COOLDOWN = 30 * 60

    def _yt_block_file(self): return self.jobs_dir() / "_youtube_blocked.json"

    def _youtube_transcript(self, j, s, log):
        src = j.dir / "src"; src.mkdir(exist_ok=True)
        man, tf, mf = src / "transcript_manual.txt", src / "transcript.txt", src / "meta.json"
        vid = transcript.video_id(s["url"])
        def meta_from_elsewhere():
            if mf.exists():
                m = json.loads(mf.read_text(encoding="utf-8"))
                if m.get("title") and m.get("title") != "Pasted transcript": return m
            for d in self.jobs_dir().iterdir():   # another job of the same video
                o = d / "src" / "meta.json"
                if d != j.dir and o.exists():
                    try:
                        m = json.loads(o.read_text(encoding="utf-8"))
                        if vid and m.get("id") == vid: return m
                    except Exception: pass
            return None
        # 1) a pasted transcript always wins; metadata from an earlier attempt / another job, else one light YouTube call
        if man.exists():
            text = man.read_text(encoding="utf-8"); meta = meta_from_elsewhere()
            if not meta:
                try: meta = transcript.meta_only(s["url"], src)
                except Exception as e:
                    log(f"  (couldn't get the video's title from YouTube: {str(e)[:100]}); using a placeholder")
                    meta = {"id": vid, "title": "Pasted transcript", "webpage_url": s.get("url", "")}
            mf.write_text(json.dumps(meta, indent=1), encoding="utf-8"); tf.write_text(text, encoding="utf-8")
            log(f"Transcript: {len(text.split())} words (pasted)"); return meta, text
        # 2) already fetched in an earlier attempt of this job
        if tf.exists() and len(tf.read_text(encoding="utf-8").split()) > 100 and meta_from_elsewhere():
            text = tf.read_text(encoding="utf-8"); log(f"Transcript: reusing the one already fetched ({len(text.split())} words)")
            return meta_from_elsewhere(), text
        # 3) another job already has this video's transcript
        if vid:
            for d in sorted(self.jobs_dir().iterdir(), key=lambda x: ((x / "src" / "source_cues.json").exists(), x.name), reverse=True):   # jobs with timed cues first
                o, om = d / "src" / "transcript.txt", d / "src" / "meta.json"
                if d == j.dir or not (o.exists() and om.exists()): continue
                try: m = json.loads(om.read_text(encoding="utf-8"))
                except Exception: continue
                if m.get("id") == vid and len(o.read_text(encoding="utf-8").split()) > 100:
                    text = o.read_text(encoding="utf-8"); tf.write_text(text, encoding="utf-8"); mf.write_text(json.dumps(m, indent=1), encoding="utf-8")
                    if (d / "src" / "source_cues.json").exists():   # the timed captions too: the Source Clip rung needs them
                        shutil.copy2(d / "src" / "source_cues.json", tf.parent / "source_cues.json")
                    log(f"Transcript: reusing the transcript of the same video from job {d.name} ({len(text.split())} words); YouTube not contacted")
                    return m, text
        # 4) YouTube recently blocked this PC: don't ask again yet
        bf = self._yt_block_file()
        if bf.exists():
            b = json.loads(bf.read_text(encoding="utf-8"))
            left = b.get("until", 0) - time.time()
            if left > 0:
                at = datetime.datetime.fromtimestamp(b["until"]).strftime("%H:%M")
                raise RuntimeError(f"YouTube blocked this PC recently, so it wasn't asked again. Try again after {at} (about {int(left // 60) + 1} min), "
                                   f"or paste the transcript into this job (Paste transcript, below) and it continues without YouTube.")
        # 5) fetch; a block starts the cooldown
        try: return transcript.fetch(s["url"], src, log)
        except RuntimeError as e:
            if "blocking or rate-limiting" in str(e):
                until = time.time() + self.YT_COOLDOWN
                bf.write_text(json.dumps({"until": until, "why": str(e)[:200]}), encoding="utf-8")
                at = datetime.datetime.fromtimestamp(until).strftime("%H:%M")
                raise RuntimeError(f"YouTube blocked this PC ({str(e).split('(')[1].split(')')[0] if '(' in str(e) else 'rate limit'}). "
                                   f"Try again after {at} (about {self.YT_COOLDOWN // 60} min), or paste the transcript into this job (Paste transcript, below).")
            raise

    def set_transcript(self, jid, text):
        j = self.job(jid); (j.dir / "src").mkdir(exist_ok=True)
        (j.dir / "src" / "transcript_manual.txt").write_text(text, encoding="utf-8")
        j.log(f"Transcript pasted ({len(text.split())} words)")
        if j.state.get("status") in ("error", "stopped"): self.resume(jid)

    def _run(self, jid):
        j = self.job(jid); s = j.state; cfg = config.load()
        if s.get("tts_engine") in ("kokoro", "wanGP"): cfg["tts_engine"] = s["tts_engine"]   # the job's own narration choice
        if s.get("audience") in writer.AUDIENCE: cfg["audience"] = s["audience"]; cfg["_audience_from"] = "job"   # the job's own audience (script prompts)
        if s.get("cancelled") and s.get("status") == "stopped": return   # cancelled while it waited in the queue
        self.current = jid
        stop = lambda: jid in self.cancel
        wg = WanGP(cfg); log = j.log
        j.save(status="running", error="")
        dbg = debug.Debugger(j, log)
        try: self._stages(j, s, cfg, wg, log, stop, dbg, jid)
        except debug.Paused as p:
            info = p.info
            if j.state.get("cancel_req"):   # Stop video reached its safe point
                where = f"Beat {info['n']}" if info.get("n") else (info.get("where") or j.state.get("stage") or "")
                j.save(status="stopped", pause=None, pause_req=False, cancel_req=False, cancelled=True)
                log(f"Cancelled at a safe point ({where}). Finished work is kept; Resume continues from here.")
                debug.trace(j.dir, {"ev": "cancel", "at": where}); return
            if info.get("stage") is None: info["stage"] = j.state.get("stage")
            sd = j.dir / "short"
            if (sd / "timings.json").exists() and (sd / "stock" / "pick.json").exists() and j.short_plan():
                beats = [info["beat"]] if info.get("beat") else list(debug.chains(j.dir))
                if beats:
                    try:
                        from . import review
                        review.collect(j.dir, j.short_plan(), cfg, log, s.get("visual_review", "auto"), debug_beats=beats)
                    except Exception as e: log(f"  couldn't gather this beat's treatments ({str(e)[:150]})")
            j.save(status="paused", pause=info, pause_req=False)
            log(info["label"] + (f" at Beat {info['n']}" if info.get("n") else f" before {info.get('where')}") + ". Press Continue to go on.")
            debug.trace(j.dir, {"ev": "pause", "label": info["label"], "beat": info.get("n"), "where": info.get("where")}, force=True)
            debug.render_md(j.dir)

    def _stages(self, j, s, cfg, wg, log, stop, dbg, jid):
        mode = s.get("mode", "long")
        gpu_held = False

        def release_gpu():
            nonlocal gpu_held
            if gpu_held:
                gpu_lock.release()
                gpu_held = False

        for st in stages_for(mode):
            if st in j.state.get("done", []): continue

            if gpu_held and st not in GPU_STAGES:
                release_gpu()

            if stop():
                release_gpu()
                j.save(status="stopped"); log("Stopped"); self.cancel.discard(jid); return

            if st in GPU_STAGES:
                if self.live and not j.state.get("editor_owned"):
                    if self._wait_editor_reservation(j, s, log, jid):
                        release_gpu()
                        return
                if not gpu_held:
                    gpu_lock.acquire(desc=f"job:{jid}:{st}")
                    gpu_held = True

            dbg.manual(st)
            j.save(prog={"out": output_of(st), "stage": st, "n": 0, "of": 0})
            j.save(stage=st); log(f"== {st} ==")
            if st == "transcript":
                man = j.dir / "src" / "transcript_manual.txt"
                if not s.get("url"):
                    up = j.dir / "src" / s["upload"] if s.get("upload") else None
                    meta, text = sources.load(j.dir / "src", up, s.get("src_title", ""), s.get("src_credit", ""), log)
                else:
                    meta, text = self._youtube_transcript(j, s, log)
                j.save(title=meta.get("title", ""))
            elif st == "script":
                if s.get("provider"): cfg["script_provider"] = s["provider"]
                prov = cfg.get("script_provider", "claude")
                if prov == "claude" and not cfg.get("anthropic_api_key"): raise RuntimeError("Add your Anthropic API key in Settings (or pick another Script AI).")
                if prov in ("zai", "deepseek") and not cfg.get(prov + "_api_key"): raise RuntimeError(f"Add your {prov} API key in Settings (or pick another Script AI).")
                meta = json.loads((j.dir / "src" / "meta.json").read_text(encoding="utf-8"))
                text = (j.dir / "src" / "transcript.txt").read_text(encoding="utf-8")
                plan = writer.write_plan(cfg, meta, text, s["minutes"], log, stop, j.dir / "src")
                plan = short.verify_quotes(plan, text, log); j.save_plan(plan)
            elif st == "short_script":
                if s.get("provider"): cfg["script_provider"] = s["provider"]
                meta = json.loads((j.dir / "src" / "meta.json").read_text(encoding="utf-8"))
                text = (j.dir / "src" / "transcript.txt").read_text(encoding="utf-8")
                lp = j.plan()
                sp = short.write_short(cfg, meta, text, s.get("short_secs", 165), mode, lp["title"] if lp else "", log, stop, j.dir / "src",
                                       smoke=bool(s.get("smoke")))
                j.save_short_plan(sp)
                if not lp: j.save(title=sp["title"])
            elif st == "short_review":
                from . import review
                vm = s.get("visual_review", "auto")
                rv, pause = review.collect(j.dir, j.short_plan(), cfg, log, vm)
                if pause:
                    j.save(status="awaiting_visuals")
                    debug.trace(j.dir, {"ev": "pause", "label": "Paused: uncertain about this beat",
                                        "beats": ", ".join(f"Beat {int(b[1:]) + 1}" for b, x in rv["beats"].items() if x.get("uncertain") and not x.get("decision"))})
                    debug.render_md(j.dir)
                    release_gpu()
                    log("Visual review: choose a treatment for each beat on the job page (or Approve all remaining)." if vm == "every" else
                        "Visual review: some beats are uncertain; check them on the job page (or Approve all remaining)."); return
                if rv: review.close(j.dir)
            elif st in ("short_stock", "short_voice", "short_fallback", "short_render"):
                sp = j.short_plan()
                if st == "short_stock":
                    from . import tts
                    kok = tts.engine(cfg) == "kokoro"
                    if "short_voice" not in j.state.get("done", []) and (kok or wg.alive()):
                        # footage (network + DeepSeek + a little GPU) and narration (GPU) run side by side
                        errs = []
                        def _stock():
                            try: short.do_stock(j.dir, sp, cfg, log, stop)
                            except Exception as e: errs.append(e)
                        th = threading.Thread(target=_stock, daemon=True); th.start()
                        log("Footage and narration run in parallel")
                        try: short.do_voice(j.dir, sp, cfg, wg, log, stop)
                        finally: th.join()   # never leave footage running into a retry
                        d = j.state.get("done", []); d.append("short_voice"); j.save(done=d)
                        if errs: raise errs[0]
                    else: short.do_stock(j.dir, sp, cfg, log, stop)
                elif st == "short_voice": _need_tts(wg, cfg); short.do_voice(j.dir, sp, cfg, wg, log, stop)
                elif st == "short_fallback":
                    from . import talkinghead
                    if s.get("presenter") and talkinghead.enabled(cfg): talkinghead.early(j.dir, cfg, log)   # first claim on HF GPU time
                    if not wg.alive(): log("WanGP is not running: fallback beats get map/headline graphics instead of AI stills")
                    short.do_fallback(j.dir, sp, cfg, wg, log, stop, full=s.get("visual_review") == "every", dbg=dbg)
                else:
                    meta = json.loads((j.dir / "src" / "meta.json").read_text(encoding="utf-8"))
                    out = short.do_render(j.dir, sp, cfg, meta, log, stop); j.save(short_output=str(out))
                    from . import music
                    if not s.get("smoke") or cfg.get("music_in_smoke", False): music.mix(out, cfg, log, music.hook_secs_short(j.dir), seed=jid, text=sp.get("title", "") + ": " + " ".join(x["vo"] for x in sp["sections"]))   # hook cue + ducked bed (your tracks)
                    from . import talkinghead
                    if s.get("presenter") and talkinghead.enabled(cfg):   # talking head over the hook (Hugging Face; optional, never fails the job)
                        out = talkinghead.overlay_short(j.dir, sp, cfg, out, log)
                    from . import capcut
                    if capcut.enabled(cfg) and capcut.pending(j.dir):   # ladder v2 rung 7: one CapCut session per video (off by default)
                        out = capcut.run(cfg, j.dir, out, sp, log)
                        try:
                            if json.loads((j.dir / "short" / "capcut" / "capcut.json").read_text(encoding="utf-8")).get("ok"):
                                from . import edit; edit.ensure_keyframes(j.dir, log)   # the replaced file needs its beat keyframes again
                        except Exception as e: log(f"  couldn't prepare the CapCut version for editing ({str(e)[:120]})")
                    _length_check(j, out, sp.get("target_secs") or s.get("short_secs"), "Short", log)
                    from . import thumb916, review
                    try: j.save(thumbnail=str(thumb916.make(j.dir, sp, cfg, log)))
                    except Exception as e: log(f"  thumbnail failed ({str(e)[:200]})")
                    try: review.prune(j.dir, log, full=False)
                    except Exception as e: log(f"  pruning failed ({str(e)[:120]})")
            elif st == "review":
                qs = [q for p in (j.plan(), j.short_plan()) if p for q in p.get("questions", [])]
                if not s.get("auto_approve", True):
                    release_gpu()
                    j.save(status="awaiting_review"); log("Script ready for review. Edit if you like, then press Approve."); return
                if qs and cfg.get("pause_on_questions", False):
                    release_gpu()
                    j.save(status="awaiting_review"); log(f"Fact-check raised {len(qs)} question(s); paused for review (setting: pause on fact-check questions)."); return
                if qs: log(f"Fact-check raised {len(qs)} question(s); continuing (review is skipped by default):")
                for q in qs[:8]: log("  ? " + q[:200])
            else:
                plan = j.plan()
                if st == "charts": render.do_charts(j.dir, plan, cfg, log)
                elif st == "voice": _need_tts(wg, cfg); render.do_voice(j.dir, plan, cfg, wg, log, stop)
                elif st == "captions":
                    if s.get("captions", True):
                        from . import captions as C
                        for sec in plan["sections"]:
                            if stop(): raise RuntimeError("cancelled")
                            caps = C.build_section(cfg, j.dir, sec["id"], sec["vo"], log)
                            log(f"Captions {sec['id']}: {len(caps)} lines, {sum(1 for c in caps if c.get('emoji_png'))} icons")
                elif st == "presenter":
                    if s.get("presenter", False):
                        # optional feature: a WanGP outage (or any presenter failure) skips the presenter, never the job
                        try:
                            _need_wangp(wg); render.do_presenter(j.dir, plan, cfg, wg, log, stop)
                        except Exception as e:
                            if str(e) == "cancelled" or type(e).__name__ == "Paused": raise
                            log(f"On-screen presenter skipped ({type(e).__name__}: {' '.join(str(e).split())[:300]}); "
                                "the explainer continues without it")
                            s["presenter"] = False; j.save(presenter=False)
                elif st == "broll":
                    if not cfg.get("long_broll", True):
                        from . import source_visuals
                        source_visuals.apply_long(j.dir, plan, cfg, log); j.save_plan(plan)
                    if cfg.get("long_broll", True):
                        from . import footage
                        footage.long_broll(j.dir, plan, cfg, log, stop); j.save_plan(plan)
                elif st == "motion":
                    if any(v["type"] == "motion" and not v.get("stock") for x in plan["sections"] for v in x["visuals"]): _want_wangp(wg, cfg, log)
                    render.do_motion(j.dir, plan, cfg, wg, log, stop); j.save_plan(plan)
                elif st == "stills":
                    if any(v["type"] == "still" and not v.get("stock") for x in plan["sections"] for v in x["visuals"]): _want_wangp(wg, cfg, log)
                    render.do_stills(j.dir, plan, cfg, wg, log, stop); j.save_plan(plan)   # illustrations turn stills into motion clips
                elif st == "assemble":
                    if j.state.get("refresh_fallbacks"):   # Full re-render with "rebuild text-card fallbacks"
                        render.refresh_fallbacks(j.dir, plan, cfg, log, stop); j.save_plan(plan); j.save(refresh_fallbacks=False)
                    meta = json.loads((j.dir / "src" / "meta.json").read_text(encoding="utf-8"))
                    if s.get("presenter", False) or cfg.get("long_renderer", "remotion") == "ffmpeg":   # the old stitcher (presenter PIP lives there)
                        parts = assemble.build(j.dir, plan, log, stop, use_presenter=s.get("presenter", False), use_captions=s.get("captions", True)); final = assemble.finalize(j.dir, plan, parts, meta, log)
                    else:   # one timeline from the narration, rendered like the Short (explainer.py)
                        from . import explainer
                        final = explainer.render(j.dir, plan, cfg, meta, log, stop)
                    if cfg.get("music_long", True):
                        from . import music
                        music.mix(final, cfg, log, float(cfg.get("music_long_hook_secs", 8)), seed=jid, text=plan.get("title", "") + ": " + " ".join(x["vo"] for x in plan["sections"])[:3000])
                    j.save(output=str(final)); _length_check(j, final, (s.get("minutes") or 0) * 60, "Long video", log)
            if stop():
                release_gpu()
                j.save(status="stopped"); log("Stopped"); self.cancel.discard(jid); return
            d = j.state.get("done", []); d.append(st); j.save(done=d)
        if cfg.get("qc_on", False) and not gpu_held:   # frame QC uses the GPU (vision model): keep/take the lock (Claude)
            gpu_lock.acquire(desc=f"job:{jid}:qc"); gpu_held = True
        if cfg.get("qc_on", False):   # (off until calibrated: the first run flagged most news frames) owner, 2026-10-24: frame QC on every video (fingers, smudges, sideways, blur, giant faces)
            try:
                from . import qc
                if qc.available(cfg):
                    for mp4 in sorted((j.dir / "output").glob("*.mp4")):
                        if stop(): break
                        vert = "short" in mp4.stem.lower() or "9_16" in mp4.stem
                        log(f"Quality check: {mp4.name}")
                        fix = str(cfg.get("qc_mode", "report")).strip().lower() == "fix"
                        # fix: qc.py only marks (report mode); qc_repair replaces each marked span from the ladder (MSG 007)
                        qc.qc_part(mp4, dict(cfg, qc_mode="report") if fix else cfg, log, every=4.0 if vert else 6.0, label=mp4.stem[:30], kind="short" if vert else "documentary")
                        if fix:
                            from . import qc_repair
                            qc_repair.repair(mp4, cfg, j.dir, log, stop, vert=vert)
                        qc.qc_final(mp4, cfg, j.dir / "qc", log, every=10.0 if vert else 30.0)
                else: log("Quality check skipped (the local vision model isn't running)")
            except Exception as e:
                if str(e) == "cancelled" or type(e).__name__ == "Paused": raise
                log(f"Quality check skipped ({type(e).__name__}: {str(e)[:200]})")
        release_gpu()
        j.save(status="finished", stage="done"); log("Finished.")
        if j.state.get("trace"):
            debug.trace(j.dir, {"ev": "finished"}); p = debug.render_md(j.dir)
            if p: log(f"Debug trace: {p}")

def _need_tts(wg, cfg):
    """Narration needs WanGP only when the engine is WanGP (tts_engine, the default); Kokoro runs on its own."""
    from . import tts
    if tts.engine(cfg) == "kokoro":
        why = tts.available(cfg)
        if not why: return
        if not cfg.get("tts_fallback", True): raise RuntimeError(f"Narration engine is Kokoro but {why}. Install it, or set tts_engine back to wanGP.")
        cfg["tts_engine"] = "wanGP"   # fallback: this job narrates with WanGP
    _need_wangp(wg)

def _want_wangp(wg, cfg, log):
    """Long-video motion / stills: with ladder v2 a missing WanGP is not fatal - each visual drops down its ladder
    (still, graphics, physics, illustration, headline). Without v2 WanGP is required, as before."""
    try: ok = wg.alive()
    except Exception: ok = False
    if ok: return
    if cfg.get("ladder_v2"): log("WanGP is not reachable: these visuals drop to the next rung (graphics / illustration / headline)"); return
    raise RuntimeError("WanGP is not running. Start Wan2GP in Pinokio, then press Resume.")

def _need_wangp(wg):
    """True when WanGP is running or can be started on demand (it is NOT started here: the first generation starts it)."""
    if not wg.alive(): raise RuntimeError("WanGP is not running and can't be started on demand (wangp_dir). Start Wan2GP in Pinokio, then press Resume.")
