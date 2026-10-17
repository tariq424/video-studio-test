"""/make: describe a video in plain English -> a job spec -> the real New-video form, filled in the page for you to check and
start. The spec is internal (never shown); a plain-English summary of it is.

Parsing: a small local model through Ollama (phi4-mini, else gemma3:4b) plus deterministic rules. Links, file paths and numbers
always come from the rules (a small model can garble a URL); the model decides the rest. Only options that really exist are in
the spec: research, TLDR and a verification switch are not pipeline steps, so they are reported as "not available" instead."""
import json, re, threading, time, subprocess, sys, os, shutil
from pathlib import Path
import requests
from . import config
from .writer import AUDIENCE

DEFAULT = {"input": {"type": "youtube", "source": "", "title": "", "credit": "", "transcript": ""},
           "output": {"mode": "short", "short_length": 165, "long_minutes": 15},
           "pipeline": {"script_review": False, "visuals": "never", "captions": True, "presenter": False, "script_ai": "", "audience": ""}}
MODES = {"short", "explainer", "both"}   # "smoke" is set only by the rules ("smoke test")
AIS = {"": "Settings default", "deepseek": "DeepSeek", "zai": "z.ai GLM", "claude": "Claude", "local": "Local AI (Ollama)"}

PROMPT = """Turn the user's request for a video into JSON. Fields:
- "input_type": "youtube" (a YouTube link), "local_file" (a file on their PC: audio such as a NotebookLM recording, or a pdf/docx/txt/md),
  or "text" (they pasted the text itself).
- "mode": "short" (a vertical YouTube Short), "explainer" (a long explainer video), or "both".
- "short_seconds": length of the Short in seconds (120-176), or null if not said. "2:45" means 165.
- "long_minutes": length of the explainer in minutes (3-20), or null if not said.
- "script_review": true only if they want to read or approve the SCRIPT before rendering.
- "visuals_review": true if they want to review/choose the visuals of every beat ("review mode", "review every beat", "let me pick visuals").
- "visuals_mode": "never" if they want no pauses at all ("never pause", "decide everything", "no stops", "end to end", "make the best call"),
  "auto" only if they explicitly want it to pause when unsure, "review" for review mode, or null if not said.
- "captions": false only if they say no captions. "presenter": true only if they ask for an on-screen presenter.
- "script_ai": "deepseek", "zai", "claude", "local", or "" if not named.
- "audience": "beginner" for zero-background viewers who need terms explained in depth, "common" for general viewers,
  "informed" for some technical familiarity, "expert" for specialists, or "" if not specified.
- "title" and "credit": the source's title and author if they give them (for files/text), else "".
Reply with ONLY the JSON object.

Request: \"\"\"{text}\"\"\""""

NEVER = (r"never[- ]?pause|no (pauses|stops|stopping)|don'?t (pause|stop|ask)|without (pausing|stopping)|decide everything|"
         r"end[- ]to[- ]end|make the best call|best call when unsure|just (run|fire|go)|no review pauses|never stop")

UNSUPPORTED = [(r"\bresearch", "research (there is no research step yet; the script is written from the source only)"),
               (r"\btl;?dr\b", "a TLDR (not an option yet)"),
               (r"\bverif", "a verification switch (quotes and visuals are always checked)"),
               (r"fact[- ]?check", "a fact-check switch (the fact-check always runs)"),
               (r"\bthumbnail", "a thumbnail switch (Shorts always get a 9:16 thumbnail)"),
               (r"\bchannel\b", "a per-video channel (the channel name is in Settings)")]

def _rules(text):
    """Facts read straight from the text. -> partial spec, notes"""
    t = text or ""; low = t.lower(); out = {"input": {}, "output": {}, "pipeline": {}}
    for audience in AUDIENCE:
        instruction = low.split('transcript:')[0].split('text:')[0]
        if re.search(r'\b(?:for (?:a |an )?' + audience + r's?|audience\s*[:=]?\s*' + audience +
                     r'|' + audience + r'(?:[- ]friendly| (?:audience|level|viewers|short|explainer|video)))\b', instruction):
            out['pipeline']['audience'] = audience
            break
    m = re.search(r"https?://(?:www\.|m\.)?(?:youtube\.com/(?:watch\?v=|shorts/|live/)|youtu\.be/)[\w\-?=&%.]+", t)
    if m: out["input"].update(type="youtube", source=m.group(0).rstrip(".,)"))
    p = re.search(r"(?:\"([A-Za-z]:\\[^\"]+)\"|([A-Za-z]:\\[^\s,;\"']+(?: [^\s,;\"'\\]+)*\.[A-Za-z0-9]{2,4}))", t)
    if p and not m: out["input"].update(type="local_file", source=(p.group(1) or p.group(2)).strip())
    tm = re.search(r"(?:text|notes|article|transcript)\s*:\s*(.{40,})", t, re.S | re.I)
    if tm and not m and not p: out["input"].update(type="text", source=tm.group(1).strip())
    if re.search(r"notebook ?lm", low) and not m and "type" not in out["input"]: out["input"]["type"] = "local_file"
    SHORTISH = r"\bshorts?\b|vertical (clip|video|cut)|\breels?\b|tiktok|9:16"
    LONGISH = r"\bexplainer\b|long[- ]?form|long video|full(-length)? video|16:9"
    WORDS = {"three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twelve": 12, "fifteen": 15, "twenty": 20}
    mins = [int(x) for x in re.findall(r"\b(\d{1,2})[- ]?(?:min|mins|minutes?)\b", low)] + \
           [WORDS[w] for w in re.findall(r"\b(" + "|".join(WORDS) + r")[- ]?(?:min|mins|minutes?)\b", low)]
    longish = bool(re.search(LONGISH, low)) or any(m >= 3 for m in mins)   # "a 2 minute Short" is still a Short
    if mins and any(m >= 3 for m in mins): out["output"]["long_minutes"] = max(m for m in mins if m >= 3)
    if any(m < 3 for m in mins): out["output"]["short_length"] = min(m for m in mins if m < 3) * 60   # "a 2 minute Short"
    if re.search(r"\bboth\b", low) or (re.search(SHORTISH, low) and longish): out["output"]["mode"] = "both"
    elif longish: out["output"]["mode"] = "explainer"
    elif re.search(SHORTISH, low): out["output"]["mode"] = "short"
    mm = re.search(r"\b(\d):([0-5]\d)\b", t)
    if mm: out["output"]["short_length"] = int(mm.group(1)) * 60 + int(mm.group(2))
    sm = re.search(r"\b(\d{2,3})\s*(?:s|sec|secs|seconds)\b", low)
    if sm: out["output"]["short_length"] = int(sm.group(1))
    if re.search(r"\bsmoke[- ]?test", low): out["output"].update(mode="smoke", short_length=30)
    if re.search(r"pause (only )?when (it'?s |you'?re )?unsure|\bauto(matic)? (mode|visuals)\b", low): out["pipeline"]["visuals"] = "auto"
    if re.search(NEVER, low): out["pipeline"]["visuals"] = "never"   # wins over "auto"; review mode wins over both (below)
    if re.search(r"review (mode|every beat|each beat|the visuals|visuals)|(pick|choose|approve|check) (the )?(visuals|footage|images|pictures)", low): out["pipeline"]["visuals"] = "review"
    if re.search(r"(review|read|check|approve|see|edit) (the |my )?script|script review", low): out["pipeline"]["script_review"] = True
    if re.search(r"(skip|no) script review|don'?t (need to )?review the script", low): out["pipeline"]["script_review"] = False
    if re.search(r"no captions|without captions", low): out["pipeline"]["captions"] = False
    if re.search(r"\bpresenter\b", low) and not re.search(r"no presenter|without (a )?presenter", low): out["pipeline"]["presenter"] = True
    for k, rx in (("deepseek", r"deepseek"), ("zai", r"z\.?ai|\bglm\b"), ("claude", r"\bclaude\b"), ("local", r"local ai|ollama")):
        if re.search(rx, low): out["pipeline"]["script_ai"] = k
    notes = [msg for rx, msg in UNSUPPORTED if re.search(rx, low)]
    return out, notes

def _ollama(cfg): return cfg.get("ollama_url", "http://127.0.0.1:11434").rstrip("/")

_pull = {"state": "", "model": ""}

def model_status(cfg):
    want = [cfg.get("make_model", "phi4-mini"), cfg.get("make_model_fallback", "gemma3:4b")]
    try: tags = [m.get("name", "") for m in requests.get(_ollama(cfg) + "/api/tags", timeout=4).json().get("models", [])]
    except Exception: return None, "Ollama isn't running"
    for w in want:
        if any(t == w or t.startswith(w + ":") for t in tags): return w, ""
    return None, f"{want[0]} isn't installed in Ollama yet"

def ensure_model(cfg):
    """Download phi4-mini once (about 2.5 GB) in the background."""
    if _pull["state"] == "pulling": return
    name = cfg.get("make_model", "phi4-mini"); _pull.update(state="pulling", model=name)
    def run():
        try:
            r = requests.post(_ollama(cfg) + "/api/pull", json={"model": name, "stream": False}, timeout=7200)
            _pull["state"] = "done" if r.status_code == 200 else f"failed: {r.text[:120]}"
        except Exception as e: _pull["state"] = f"failed: {str(e)[:120]}"
    threading.Thread(target=run, daemon=True).start()

def _llm(cfg, text):
    model, why = model_status(cfg)
    if not model:
        if "isn't installed" in why: ensure_model(cfg)
        return None, why + ("; downloading it now (about 2.5 GB), rules used meanwhile" if _pull["state"] == "pulling" else "")
    try:
        r = requests.post(_ollama(cfg) + "/api/chat", timeout=180, json={"model": model, "stream": False, "format": "json", "keep_alive": 0,
                          "options": {"temperature": 0}, "messages": [{"role": "user", "content": PROMPT.replace("{text}", text[:4000])}]})
        if r.status_code != 200: return None, f"{model} error {r.status_code}"
        return json.loads(r.json()["message"]["content"]), model
    except Exception as e: return None, f"{model} failed ({str(e)[:80]})"

def _deep(a, b):
    for k, v in b.items():
        if isinstance(v, dict): _deep(a.setdefault(k, {}), v)
        else: a[k] = v
    return a

def parse(text, cfg, audience=None):
    """-> {"spec", "summary", "notes", "parsed_by"}"""
    spec = json.loads(json.dumps(DEFAULT))
    j, who = _llm(cfg, text)
    if isinstance(j, dict):
        it = j.get("input_type")
        if it in ("youtube", "local_file", "text"): spec["input"]["type"] = it
        md = j.get("mode")
        if md in MODES: spec["output"]["mode"] = md
        for k, lo, hi, dst in (("short_seconds", 120, 176, "short_length"), ("long_minutes", 3, 20, "long_minutes")):
            try:
                if j.get(k) is not None: spec["output"][dst] = max(lo, min(hi, int(float(j[k]))))
            except (TypeError, ValueError): pass
        low = text.lower()   # a small model invents switches: only take one when the text talks about that topic
        topic = {"script_review": r"script", "captions": r"caption|subtitle", "presenter": r"presenter|host|avatar"}
        for k in ("script_review", "captions", "presenter"):
            if isinstance(j.get(k), bool) and re.search(topic[k], low): spec["pipeline"][k] = j[k]
        if j.get("visuals_mode") in ("never", "auto", "review") and re.search(r"visual|beat|footage|image|picture|review|pause|stop|unsure|decide|end to end|end-to-end", low):
            spec["pipeline"]["visuals"] = j["visuals_mode"]
        elif j.get("visuals_review") is True and re.search(r"visual|beat|footage|image|picture|review", low):
            spec["pipeline"]["visuals"] = "review"
        if j.get("script_ai") in AIS: spec["pipeline"]["script_ai"] = j["script_ai"]
        if j.get('audience') in AUDIENCE: spec['pipeline']['audience'] = j['audience']
        for k in ("title", "credit"):
            if isinstance(j.get(k), str): spec["input"][k] = j[k][:120]
        parsed_by = who
    else: parsed_by = f"rules only ({who})"
    rules, notes = _rules(text)
    _deep(spec, rules)   # links, paths, numbers and explicit keywords win
    if audience:
        if audience not in AUDIENCE: raise ValueError('Unknown audience: ' + str(audience))
        spec['pipeline']['audience'] = audience
    o = spec["output"]; o["short_length"] = 30 if o["mode"] == "smoke" else max(120, min(176, int(o["short_length"]))); o["long_minutes"] = max(3, min(20, int(o["long_minutes"])))
    if o["mode"] == "smoke" and not spec["input"]["source"] and cfg.get("smoke_source"):   # no source given: the standard smoke-test video
        spec["input"].update(type="youtube", source=cfg["smoke_source"]); notes.append("no source given: using the standard smoke-test video")
    if spec["input"]["type"] == "youtube" and not spec["input"]["source"]: notes.append("no YouTube link found in your description: paste it into the form")
    if spec["input"]["type"] == "local_file" and not spec["input"]["source"]: notes.append("no file path found: type the path or pick the file in the form")
    return {"spec": spec, "summary": summary(spec), "notes": notes, "parsed_by": parsed_by}

def summary(spec):
    i, o, p = spec["input"], spec["output"], spec["pipeline"]
    src = {"youtube": "YouTube link", "local_file": "File on this PC", "text": "Pasted text"}[i["type"]]
    show = (i["source"][:90] + ("…" if len(i["source"]) > 90 else "")) if i["source"] else "(not given)"
    mode = {"short": f"Short only, {o['short_length'] // 60}:{o['short_length'] % 60:02d}", "explainer": f"Explainer only, {o['long_minutes']} min",
            "both": f"Explainer ({o['long_minutes']} min) + Short ({o['short_length'] // 60}:{o['short_length'] % 60:02d})",
            "smoke": "Smoke test: 30-second Short (about 75 words; pipeline check)"}[o["mode"]]
    lines = [f"Source: {src} — {show}", f"Make: {mode}",
             "Script review: " + ("pause so you can read and edit the script" if p["script_review"] else "skipped (renders straight away)"),
             "Visuals: " + {"review": "Review every beat", "auto": "Auto (pauses only when unsure)"}.get(p["visuals"], "Decide everything (never pauses)") if o["mode"] != "explainer" else "Visuals: (explainer: automatic)",
             f"Script AI: {AIS.get(p['script_ai'], p['script_ai'])}",
             'Audience: ' + (p.get('audience') or 'Settings default').capitalize()]
    if o["mode"] in ("explainer", "both"): lines.append("Captions: " + ("on" if p["captions"] else "off") + " · Presenter: " + ("on" if p["presenter"] else "off"))
    if i.get("title"): lines.append(f"Source title: {i['title']}" + (f" — {i['credit']}" if i.get("credit") else ""))
    return lines

# ---------------------------------------------------------------- saved specs
def _saved_file(): return config.ROOT / "make_saved.json"

def saved():
    f = _saved_file()
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []

def save(name, spec, description=""):
    s = [x for x in saved() if x["name"] != name]
    s.insert(0, {"name": name[:60], "spec": spec, "description": description[:2000], "saved": time.strftime("%Y-%m-%d %H:%M")})
    _saved_file().write_text(json.dumps(s[:50], indent=1), encoding="utf-8"); return s

def delete(name):
    s = [x for x in saved() if x["name"] != name]; _saved_file().write_text(json.dumps(s, indent=1), encoding="utf-8"); return s

# ---------------------------------------------------------------- the Playwright runner (subprocess)
_run = {"proc": None, "dir": None}

def shots_root(): d = config.ROOT / "screenshots"; d.mkdir(exist_ok=True); return d

def runner_start(spec, click_make=False, edit=None, port=None):
    if _run["proc"] and _run["proc"].poll() is None: return None, "The runner is already running; cancel it first."
    ts = time.strftime("%Y%m%d_%H%M%S"); d = shots_root() / ts; d.mkdir(parents=True)
    (d / "spec.json").write_text(json.dumps({"spec": spec, "click_make": bool(click_make), "edit": edit}, indent=1), encoding="utf-8")
    cmd = [sys.executable, str(config.ROOT / "app" / "vs_runner.py"), "--job", str(d / "spec.json"), "--out", str(d),
           "--url", f"http://127.0.0.1:{port or os.environ.get('PORT') or 42020}"]
    log = open(d / "runner.log", "w", encoding="utf-8")
    _run["proc"] = subprocess.Popen(cmd, cwd=str(config.ROOT), stdout=log, stderr=subprocess.STDOUT,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    _run["dir"] = d
    return ts, ""

def runner_status(ts=None):
    d = shots_root() / ts if ts else _run["dir"]
    if not d or not Path(d).exists(): return {"running": False, "steps": []}
    steps = []
    sf = Path(d) / "steps.jsonl"
    if sf.exists():
        for line in sf.read_text(encoding="utf-8").splitlines():
            try: steps.append(json.loads(line))
            except Exception: pass
    running = bool(_run["proc"] and _run["proc"].poll() is None and Path(_run["dir"]) == Path(d))
    lg = (Path(d) / "runner.log"); tail = lg.read_text(encoding="utf-8", errors="replace").splitlines()[-15:] if lg.exists() else []
    return {"id": Path(d).name, "running": running, "steps": steps, "log": tail}

def runner_cancel():
    p = _run["proc"]
    if p and p.poll() is None:
        p.kill()
        try:
            with open(Path(_run["dir"]) / "steps.jsonl", "a", encoding="utf-8") as f: f.write(json.dumps({"t": time.strftime("%H:%M:%S"), "step": "cancelled", "ok": False}) + "\n")
        except Exception: pass
        return True
    return False
