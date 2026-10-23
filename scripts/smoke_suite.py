"""Quick smoke suite: three 30-second smoke Shorts, one per way of making a video, plus the Hugging Face talking head.
  text   a plain text description -> Short, with the presenter on (talking head from Hugging Face, no local GPU)
  nlm    a NotebookLM audio overview -> Short (first 3 minutes used; file: --nlm or the newest in F:\\videos_test\\smoke\\nlm)
  clip   a text description + an existing video (a CPU parallax clip made here from the Hugging Face test image)
On this PC it waits for the pipeline to be idle and holds the Newsroom while it runs (the hold is always released);
against the laptop (--vs http://<laptop>:42021 --token ...) nothing on the PC is touched.
    app\\env\\Scripts\\python.exe scripts\\smoke_suite.py [--only text,nlm,clip] [--nlm file] [--vs URL --token T]
Report: F:\\videos_test\\smoke\\<time>\\report.md (+ report.json and the three Shorts)."""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from studio.media import _bin  # noqa: E402  (the same ffmpeg / ffprobe Video Studio uses)
WIN = os.name == "nt"
BASE = Path(r"F:\videos_test\smoke") if WIN else Path.home() / "videos" / "smoke"
HOLD = Path(r"F:\videos\newsroom\hold")
IMG = Path(r"F:\videos_test\poc\hf_token_test.png") if WIN else Path.home() / "videos" / "poc" / "hf_token_test.png"
TEXT = ("The Old Man of the Mountain was a granite rock face on Cannon Mountain in Franconia Notch, New Hampshire. Seen from the "
        "north, five separate ledges of rock lined up to form the profile of an old man's face, about forty feet tall from chin to forehead. "
        "Surveyors first wrote about it in 1805, and by the late 1800s it had become the most famous landmark in the state. It later "
        "appeared on the New Hampshire state quarter in 2000, on highway route signs, and on the state's license plates. Freezing and thawing "
        "water slowly widened the cracks behind the ledges, so starting in the 1920s workers climbed up every summer to hold the stones "
        "together with steel cables, turnbuckles and waterproof epoxy. A caretaker family looked after it for decades. Even so, on the night of "
        "May 3, 2003 the formation collapsed, and in the morning the face was simply gone. People left flowers at the base. Today a "
        "memorial at Profile Lake uses tall steel 'profilers': visitors stand in a marked spot, look along the steel rods toward the cliff, "
        "and the shapes line up with the mountain to show exactly where the old face used to be.")
CLIP_TEXT = ("New Hampshire has more than fifty historic covered bridges, and most of them were built in the 1800s by local carpenters "
             "using timber cut nearby. The roof and walls were not decoration: they kept snow, rain and sun off the wooden deck and the big "
             "trusses that carry the load, so a covered bridge could last eighty years or more instead of about twenty for an open one. "
             "Farmers liked them because horses were calmer crossing a river when they could not see the water below. Many bridges were "
             "nearly lost to floods, fires and trucks too heavy for them, and towns have spent years restoring them with new beams and "
             "steel supports hidden inside. In autumn, when the maples turn red and gold, visitors drive the back roads around Conway, Bath "
             "and Cornish to photograph them, and some still carry cars every day. The Cornish-Windsor bridge over the Connecticut River, "
             "which links New Hampshire and Vermont, is the longest wooden covered bridge in the United States that still carries traffic, "
             "at about 450 feet. Bath has one of the oldest, and its red paint and stone piers make it one of the most photographed.")
for t in (TEXT, CLIP_TEXT): assert len(t.split()) >= 160, len(t.split())


class Suite:
    def __init__(self, a):
        self.vs, self.h = a.vs.rstrip("/"), ({"X-VS-Token": a.token} if a.token else {})
        self.local = self.vs.startswith(("http://127.0.0.1", "http://localhost"))
        self.out = BASE / time.strftime("%Y%m%d_%H%M%S"); self.out.mkdir(parents=True, exist_ok=True)
        self.a, self.results, self.held, self.t0 = a, [], False, time.time()

    def log(self, m):
        line = f"[{time.strftime('%H:%M:%S')}] {m}"; print(line, flush=True)
        with open(self.out / "suite.log", "a", encoding="utf-8") as f: f.write(line + "\n")

    def get(self, p, **kw): return requests.get(self.vs + p, headers=self.h, timeout=30, **kw)

    def ff(self, *args): subprocess.run([_bin("ffmpeg"), "-v", "error", "-y", "-nostdin", *map(str, args)], check=True, timeout=300)

    def dur(self, p):
        r = subprocess.run([_bin("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)], capture_output=True, text=True)
        try: return float(r.stdout.strip())
        except ValueError: return 0.0

    # ---- the pipeline must not be disturbed
    def wait_idle(self, max_min=360):   # Short + explainer jobs take ~2.5 h
        if self.local and WIN and not HOLD.exists():
            HOLD.write_text("smoke suite", encoding="utf-8"); self.held = True; self.log("Newsroom held (no new pipeline work while the suite runs)")
        for i in range(max_min * 2):
            st = self.get("/api/status").json()
            if not st.get("current"): return
            if i % 10 == 0: self.log(f"waiting for the running job {st.get('current')} to finish (it is not touched)")
            time.sleep(30)
        raise RuntimeError(f"Video Studio still busy after {max_min} min; suite not started")

    def restart_vs(self):
        """In the idle gap: restart the stack so Video Studio loads its newest code (the Newsroom stays held by the file)."""
        if not (self.local and WIN): return
        Path(r"F:\code\.restart-request").write_text("", encoding="utf-8")
        self.log("Video Studio idle: restarting it to load the newest code")
        time.sleep(20)
        for _ in range(60):
            try:
                if requests.get(self.vs + "/api/status", timeout=5).ok: self.log("Video Studio is back"); time.sleep(5); return
            except requests.RequestException: pass
            time.sleep(5)
        raise RuntimeError("Video Studio did not come back after the restart")

    def release(self):
        if self.local and WIN and HOLD.exists() and HOLD.read_text(encoding="utf-8").strip() == "smoke suite":
            HOLD.unlink(); self.log("Newsroom hold released")

    # ---- inputs
    def parallax_clip(self):
        dest = self.out / "parallax_clip.mp4"
        if not IMG.exists(): raise RuntimeError(f"test image not found: {IMG}")
        # CPU only: a slow push-in with a little drift (6 s, 1920x1080)
        self.ff("-loop", 1, "-i", IMG, "-t", 6, "-vf", "scale=3840:-2,zoompan=z='1+0.0009*on':x='iw/2-(iw/zoom/2)+on*0.6':y='ih/2-(ih/zoom/2)':d=180:s=1920x1080:fps=30,format=yuv420p",
                "-c:v", "libx264", "-crf", 18, dest)
        return dest

    def nlm_audio(self):
        src = Path(self.a.nlm) if self.a.nlm else None
        if not src:
            files = sorted((p for p in (BASE / "nlm").glob("*") if p.suffix.lower() in (".mp3", ".m4a", ".wav", ".ogg", ".aac", ".webm", ".mp4")),
                           key=lambda p: p.stat().st_mtime, reverse=True) if (BASE / "nlm").exists() else []
            src = files[0] if files else None
        if not src or not src.exists(): return None
        dest = self.out / "nlm_first3min.mp3"
        self.ff("-t", 180, "-i", src, "-vn", "-ac", 1, "-ar", 24000, "-b:a", "96k", dest)
        self.log(f"NotebookLM audio: {src.name} ({self.dur(src) / 60:.1f} min; the first 3 min are used)")
        return dest

    # ---- one job
    def run(self, name, form, files, checks):
        t0 = time.time(); r = {"test": name, "ok": False}
        try:
            fh = [(k, (Path(p).name, open(p, "rb"))) for k, p in files]
            try:
                resp = requests.post(self.vs + "/api/jobs", headers=self.h, data={"mode": "smoke", "auto_approve": "true", "visual_review": "never",
                                                                                   "captions": "true", **form}, files=fh or None, timeout=120)
            finally:
                for _, (_, f) in fh: f.close()
            if not resp.ok: raise RuntimeError(f"job not accepted: {resp.text[:300]}")
            jid = resp.json()["id"]; r["job"] = jid; self.log(f"{name}: job {jid} started")
            last = ""
            while True:
                s = self.get(f"/api/jobs/{jid}").json()
                st, stage = s.get("status"), s.get("stage")
                if f"{st}/{stage}" != last: self.log(f"  {name}: {st} / {stage}"); last = f"{st}/{stage}"
                if st in ("finished", "error", "stopped", "awaiting_review", "awaiting_visuals", "paused"): break
                if time.time() - t0 > self.a.job_minutes * 60:
                    requests.post(f"{self.vs}/api/jobs/{jid}/pause", headers=self.h, timeout=30)
                    raise RuntimeError(f"took longer than {self.a.job_minutes} min (paused, not killed)")
                time.sleep(10)
            if st != "finished": raise RuntimeError(f"ended as {st}: " + " / ".join((s.get("log") or [])[-4:])[:400])
            out = Path(s.get("short_output") or "")
            dest = self.out / f"{name}_{out.name or 'short.mp4'}"
            if self.local and out.exists(): shutil.copy(out, dest)
            else:
                rel = str(out).replace("\\", "/").split(f"/{jid}/", 1)[-1] if out.name else "output/short.mp4"
                with self.get(f"/files/{jid}/{rel}", stream=True) as g:
                    g.raise_for_status(); dest.write_bytes(g.content)
            d = self.dur(dest); r.update(file=str(dest), secs=round(d, 1))
            if not 15 <= d <= 60: raise RuntimeError(f"Short is {d:.1f}s (expected about 30)")
            r["checks"] = {k: f(jid) for k, f in checks.items()}
            r["ok"] = all(v.get("ok") for v in r["checks"].values()) if r["checks"] else True
        except Exception as e:
            r["error"] = " ".join(str(e).split())[:500]
        r["minutes"] = round((time.time() - t0) / 60, 1)
        self.log(f"{name}: {'PASS' if r['ok'] else 'FAIL'} in {r['minutes']} min {r.get('error', '')}")
        self.results.append(r); return r

    def jfile(self, jid, rel):
        g = self.get(f"/files/{jid}/{rel}")
        return g.json() if g.ok else None

    def check_head(self, jid):
        j = self.jfile(jid, "short/talkinghead/talkinghead.json") or {"ok": False, "error": "no talking-head record"}
        return {"ok": bool(j.get("ok")), "space": j.get("space"), "error": j.get("error")}

    def check_clip(self, jid):
        m = self.jfile(jid, "src/clips/match.json") or {}
        n = len(m.get("assign") or {})
        return {"ok": n > 0, "beats_covered": n}

    def main(self):
        only = set(self.a.only.split(","))
        self.log(f"Smoke suite against {self.vs} ({'this PC' if self.local else 'remote worker'}): {', '.join(sorted(only))}")
        own_before = None; mus_before = None
        try:
            self.wait_idle()
            if self.a.restart_first: self.restart_vs()
            if self.a.music:   # this run's smoke Shorts get music and musical pauses
                mus_before = self.get("/api/settings").json().get("music_in_smoke")
                requests.post(self.vs + "/api/settings", headers=self.h, json={"music_in_smoke": True}, timeout=30)
            if "text" in only:
                if self.a.text_file:   # your own text (a story, a script): a 30-second smoke Short from it, no presenter
                    t = Path(self.a.text_file).read_text(encoding="utf-8-sig")
                    self.run("text", {"transcript": t, "src_title": self.a.title or Path(self.a.text_file).stem}, [], {})
                else:
                    self.run("text", {"transcript": TEXT, "src_title": "The Old Man of the Mountain", "presenter": "true"}, [], {"talking_head": self.check_head})
            if "nlm" in only:
                au = self.nlm_audio()
                if au: self.run("nlm", {"src_title": "NotebookLM audio overview"}, [("file", au)], {})
                else: self.results.append({"test": "nlm", "ok": False, "error": f"no NotebookLM audio yet: put the file in {BASE / 'nlm'}"}); self.log("nlm: SKIPPED (no audio file)")
            if "clip" in only:
                clip = self.parallax_clip()
                own_before = self.get("/api/settings").json().get("own_clips")
                if not own_before: requests.post(self.vs + "/api/settings", headers=self.h, json={"own_clips": True}, timeout=30)
                self.run("clip", {"transcript": CLIP_TEXT, "src_title": "New Hampshire covered bridges", "clip_hints": "clip1=beat1"},
                         [("clips", clip)], {"own_clip": self.check_clip})
        finally:
            if mus_before is False:
                try: requests.post(self.vs + "/api/settings", headers=self.h, json={"music_in_smoke": False}, timeout=30)
                except Exception: pass
            if own_before is False:
                try: requests.post(self.vs + "/api/settings", headers=self.h, json={"own_clips": False}, timeout=30)
                except Exception: pass
            self.release()
            self.report()

    def report(self):
        tot = round((time.time() - self.t0) / 60, 1)
        (self.out / "report.json").write_text(json.dumps({"vs": self.vs, "minutes": tot, "results": self.results}, indent=1), encoding="utf-8")
        lines = [f"# Smoke suite {self.out.name}", f"Target {self.vs}; {tot} min in all.", "", "| Test | Result | Short | Minutes | Notes |", "|---|---|---|---|---|"]
        for r in self.results:
            notes = r.get("error") or "; ".join(f"{k}: {'ok' if v.get('ok') else 'FAILED'}" + (f" ({v.get('space') or v.get('beats_covered') or v.get('error')})" if v else "")
                                                for k, v in (r.get("checks") or {}).items())
            lines.append(f"| {r['test']} | {'PASS' if r['ok'] else 'FAIL'} | {r.get('secs', '')} s | {r.get('minutes', '')} | {notes} |")
        (self.out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.log("report: " + str(self.out / "report.md"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--vs", default="http://127.0.0.1:42021"); ap.add_argument("--token", default="")
    ap.add_argument("--only", default="text,nlm,clip"); ap.add_argument("--nlm", default="")
    ap.add_argument("--job-minutes", type=float, default=15)
    ap.add_argument("--text-file", default="", help="make the text test from this file instead of the built-in description")
    ap.add_argument("--title", default="")
    ap.add_argument("--music", action="store_true", help="smoke Shorts with music and musical pauses")
    ap.add_argument("--restart-first", action="store_true", help="restart the stack in the idle gap before the tests (loads new code)")
    Suite(ap.parse_args()).main()
