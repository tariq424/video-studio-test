"""Visual ladder v2, rung 7: the CapCut fallback (label CAPCUT). Off unless BOTH "ladder_v2" and "capcut_fallback" are true.

When: a beat whose Remotion graphics HARD-failed (crash, no output, timeout - graphics.make() hard=True) and for which no physics
module fit. Soft failures (a clip exists but looks wrong) never come here; they're fixed in the post-render chat.
short.do_fallback records those beats in short/fallback/capcut.json and still gives them a provisional visual from rungs 8-10
(parallax / illustration / headline), so the Short always renders.

Per video, not per beat: after the Short is rendered (pipeline short_render), ONE CapCut session:
  1. VectCutAPI (github.com/sun-guannan/VectCutAPI, HTTP on "capcut_api_url", default :9001; chosen over capcut-mcp-full / mcp-cut:
     most used, maintained, and most other CapCut MCP servers wrap it) writes a draft: the rendered Short as the base track, and
     for each pending beat a CapCut-native text card (the beat's headline on a solid panel) over that beat's time, plus a CAPCUT label.
  2. The draft folder is copied into CapCut's drafts directory ("capcut_drafts_dir").
  3. Computer use (Anthropic API, "capcut_cu_model", pyautogui for the clicks) opens the draft in CapCut and clicks Export to
     short/capcut/. Budget: "capcut_max_actions" actions and "capcut_timeout" seconds. It stops (does not work around) on a
     sign-in, CAPTCHA, upgrade / payment prompt, or anything unexpected.
  4. Success = an MP4 actually appears in short/capcut/ with about the Short's length (the model's word is never enough). The
     Short's output is then replaced by it (the original kept as <name>_pre_capcut.mp4).
Any failure (API down, draft rejected, UI changed, CAPTCHA, timeout, wrong length) -> the Short keeps its provisional visuals,
i.e. those beats fall through to rung 8+. Logged in short/capcut/capcut.json and the beat chains."""
import base64, io, json, os, shutil, subprocess, time
from pathlib import Path
from . import media

TASK = """You are operating the CapCut desktop video editor on Windows to export one existing draft. Nothing else.
1. In CapCut's home screen, open the draft named "{name}" (it is in the drafts / projects list; scroll or search the list if needed).
2. When the editor has loaded, click the Export button (top right).
3. In the export dialog: set the file name to "{stem}" and the export location / folder to: {folder}
   Keep resolution {res}, 30 fps. Turn OFF any "export audio only", "upload" or "share" options. Then click Export.
4. Wait until the export finishes (progress reaches 100% / a "done" screen), then reply exactly: DONE
Stop immediately and reply "STOP: <reason>" (do not try to get around it) if you see: a sign-in or login request, a CAPTCHA or
"verify you are human", an upgrade / Pro / payment / subscription prompt, a terms or consent dialog, an update installer, or
anything you don't expect. Never type passwords, never click purchase or upgrade buttons, never close other applications."""


def enabled(cfg): return bool(cfg.get("ladder_v2")) and bool(cfg.get("capcut_fallback"))


def pending(job):
    f = Path(job) / "short" / "fallback" / "capcut.json"
    try: return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except Exception: return {}


def mark(sd, bid, why=None):
    """Record (why given) or clear (why None) a beat's pending CapCut fallback."""
    f = Path(sd) / "fallback" / "capcut.json"
    d = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    if why is None:
        if bid not in d: return
        d.pop(bid)
    else: d[bid] = {"why": why}
    f.parent.mkdir(parents=True, exist_ok=True); f.write_text(json.dumps(d, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- 1. the draft (VectCutAPI)
def _api(cfg, path, body, timeout=120):
    import requests
    r = requests.post(cfg.get("capcut_api_url", "http://127.0.0.1:9001").rstrip("/") + "/" + path, json=body, timeout=timeout)
    r.raise_for_status()
    j = r.json()
    if isinstance(j, dict) and j.get("success") is False: raise RuntimeError(f"{path}: {str(j.get('error') or j)[:200]}")
    return j


def _find(j, key):
    """VectCutAPI wraps results differently across versions ({"output": {...}} or flat): find `key` anywhere."""
    if isinstance(j, dict):
        if key in j: return j[key]
        for v in j.values():
            x = _find(v, key)
            if x is not None: return x
    return None


def build_draft(cfg, job, base_mp4, beats, log):
    """-> (draft_id, local draft folder). beats: [{"id","start","dur","text"}] (seconds in the Short)."""
    from .review import files_url
    sd = Path(job) / "short"; cd = sd / "capcut"; cd.mkdir(parents=True, exist_ok=True)
    w, h = (1080, 1920)
    j = _api(cfg, "create_draft", {"width": w, "height": h}); did = _find(j, "draft_id")
    if not did: raise RuntimeError(f"create_draft returned no draft_id ({str(j)[:160]})")
    dur = media.dur(base_mp4)
    url = files_url(sd) + "/" + str(Path(base_mp4).relative_to(sd)).replace("\\", "/")
    _api(cfg, "add_video", {"draft_id": did, "video_url": url, "start": 0, "end": round(dur, 3), "target_start": 0, "volume": 1.0}, timeout=600)
    for b in beats:   # the CapCut-native fallback for each failed beat: a text card over the provisional visual
        _api(cfg, "add_text", {"draft_id": did, "text": b["text"][:80], "start": round(b["start"], 3), "end": round(b["start"] + b["dur"], 3),
                               "font_size": 12, "font_color": "#FFFFFF", "background_color": "#0B0F17", "background_alpha": 0.92,
                               "shadow_enabled": True, "track_name": "capcut_cards", "transform_y": 0.05})
        _api(cfg, "add_text", {"draft_id": did, "text": "CAPCUT", "start": round(b["start"], 3), "end": round(b["start"] + b["dur"], 3),
                               "font_size": 5, "font_color": "#111111", "background_color": "#FFC83D", "background_alpha": 0.95,
                               "track_name": "capcut_label", "transform_x": -0.72, "transform_y": 0.74})
    j = _api(cfg, "save_draft", {"draft_id": did}, timeout=600)
    folder = _find(j, "draft_folder") or _find(j, "draft_path")
    cand = Path(folder) if folder else None
    if not cand or not cand.exists():   # VectCutAPI writes a dfd_<id> folder next to capcut_server.py
        api_dir = Path(cfg.get("capcut_api_dir") or ".")
        hits = sorted(api_dir.glob(f"*{did}*"), key=lambda p: p.stat().st_mtime) or sorted(api_dir.glob("dfd_*"), key=lambda p: p.stat().st_mtime)
        cand = hits[-1] if hits else None
    if not cand or not cand.exists(): raise RuntimeError("saved draft folder not found (set capcut_api_dir to VectCutAPI's folder)")
    drafts = Path(cfg.get("capcut_drafts_dir") or os.path.expandvars(r"%LOCALAPPDATA%\CapCut\User Data\Projects\com.lveditor.draft"))
    if not drafts.exists(): raise RuntimeError(f"CapCut drafts folder not found: {drafts}")
    dst = drafts / cand.name
    if dst.exists(): shutil.rmtree(dst)
    shutil.copytree(cand, dst)
    log(f"  CapCut: draft {cand.name} written ({len(beats)} beat(s) with a CapCut card)")
    return did, dst


# ---------------------------------------------------------------- 2. export (computer use)
def _shot(maxw=1366):
    from PIL import ImageGrab
    im = ImageGrab.grab(); W, H = im.size; k = min(1.0, maxw / W)
    if k < 1: im = im.resize((int(W * k), int(H * k)))
    buf = io.BytesIO(); im.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode(), k, im.size


def _act(a, k):
    import pyautogui
    pyautogui.FAILSAFE = True
    act = a.get("action"); xy = a.get("coordinate")
    X = (lambda c: (int(c[0] / k), int(c[1] / k)))
    if act in ("left_click", "double_click", "right_click", "mouse_move") and xy:
        x, y = X(xy)
        if act == "left_click": pyautogui.click(x, y)
        elif act == "double_click": pyautogui.doubleClick(x, y)
        elif act == "right_click": pyautogui.rightClick(x, y)
        else: pyautogui.moveTo(x, y)
    elif act == "type": pyautogui.write(str(a.get("text", "")), interval=0.02)
    elif act == "key":
        keys = str(a.get("text", "")).lower().replace("return", "enter").split("+")
        pyautogui.hotkey(*keys) if len(keys) > 1 else pyautogui.press(keys[0])
    elif act == "scroll" and xy:
        x, y = X(xy); n = int(a.get("scroll_amount") or 3)
        pyautogui.scroll(n * 120 * (1 if a.get("scroll_direction") == "up" else -1), x=x, y=y)
    elif act == "wait": time.sleep(min(10, float(a.get("duration") or 2)))
    # "screenshot" needs no action: every result carries a fresh one


def export(cfg, name, folder, stem, log, res="1080P"):
    """Drive CapCut's Export with computer use. -> (ok, why). Success is decided by the caller (the file must exist)."""
    try:
        import anthropic, pyautogui  # noqa: F401
    except Exception as e: return False, f"computer use unavailable ({str(e)[:80]}; pip install pyautogui)"
    if not cfg.get("anthropic_api_key"): return False, "computer use needs the Anthropic API key"
    exe = cfg.get("capcut_exe") or os.path.expandvars(r"%LOCALAPPDATA%\CapCut\Apps\CapCut.exe")
    if not Path(exe).exists(): return False, f"CapCut not found at {exe}"
    subprocess.Popen([exe]); time.sleep(12)
    c = anthropic.Anthropic(api_key=cfg["anthropic_api_key"])
    b64, k, size = _shot()
    tool = {"type": cfg.get("capcut_cu_tool", "computer_20250124"), "name": "computer", "display_width_px": size[0], "display_height_px": size[1]}
    msgs = [{"role": "user", "content": [{"type": "text", "text": TASK.format(name=name, stem=stem, folder=folder, res=res)},
                                         {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}}]}]
    t0, n = time.time(), 0
    while n < int(cfg.get("capcut_max_actions", 30)) and time.time() - t0 < int(cfg.get("capcut_timeout", 600)):
        m = c.beta.messages.create(model=cfg.get("capcut_cu_model", "claude-sonnet-5"), max_tokens=1500, tools=[tool], messages=msgs,
                                   betas=[cfg.get("capcut_cu_beta", "computer-use-2025-01-24")])
        msgs.append({"role": "assistant", "content": m.content})
        uses = [b for b in m.content if getattr(b, "type", "") == "tool_use"]
        text = " ".join(getattr(b, "text", "") for b in m.content if getattr(b, "type", "") == "text").strip()
        if not uses:
            if text.upper().startswith("DONE"): return True, "export reported done"
            return False, (text[:200] or "computer use stopped without finishing")
        out = []
        for u in uses:
            n += 1
            try: _act(u.input or {}, k); time.sleep(1.0)
            except Exception as e: return False, f"action failed ({str(e)[:100]})"
            b64, k, _ = _shot()
            out.append({"type": "tool_result", "tool_use_id": u.id, "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}}]})
        msgs.append({"role": "user", "content": out})
        if len(msgs) > 14: msgs = msgs[:1] + msgs[-12:]   # keep the task + the last few screens (bounded tokens)
    return False, "timeout / action budget used up"


# ---------------------------------------------------------------- the whole rung, once per video
def run(cfg, job, out_mp4, plan, log):
    """After the Short render. -> the path to use as the Short (the CapCut export, or out_mp4 unchanged)."""
    job = Path(job); sd = job / "short"; cd = sd / "capcut"; cd.mkdir(parents=True, exist_ok=True)
    pend = pending(job); rec = {"beats": pend, "t": time.strftime("%Y-%m-%d %H:%M:%S")}
    def done(ok, why, path=out_mp4):
        rec.update(ok=ok, why=why); (cd / "capcut.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
        log(f"  CapCut: {'used' if ok else 'not used'} - {why}" + ("" if ok else " (those beats keep their parallax / illustration / headline visuals)"))
        return path
    if not pend: return out_mp4
    if not enabled(cfg): return done(False, "capcut_fallback is off")
    try:
        tl = json.loads((sd / "public" / "teaser.json").read_text(encoding="utf-8"))
        secs = {s["id"]: s for s in plan["sections"]}
        from . import review
        rv = review.load(job) or {}
        beats = []
        for b in tl["beats"]:
            if (rv.get("beats", {}).get(b["id"]) or {}).get("decision") == "chosen": continue   # the reviewer picked a visual: leave it
            if b["id"] in pend:
                bd = (secs.get(b["id"]) or {}).get("backdrop") or {}
                text = bd.get("text") if bd.get("kind") == "headline" and bd.get("text") else " ".join(((secs.get(b["id"]) or {}).get("vo") or "").split()[:10])
                beats.append({"id": b["id"], "start": b["start"], "dur": b["dur"], "text": text})
        if not beats: return done(False, "no pending beat is in the timeline")
        base = cd / "base.mp4"; shutil.copy2(out_mp4, base)
        log(f"CapCut fallback: {len(beats)} beat(s) - one CapCut session for the video")
        did, draft = build_draft(cfg, job, base, beats, log)
        stem = f"capcut_{int(time.time())}"
        before = set(cd.glob("*.mp4"))
        ok, why = export(cfg, draft.name, str(cd), stem, log)
        new = [p for p in cd.glob("*.mp4") if p not in before and p.name != "base.mp4"]
        got = max(new, key=lambda p: p.stat().st_mtime) if new else None
        if not got: return done(False, f"export failed ({why})")
        time.sleep(3)
        if not media.ok(got) or abs(media.dur(got) - media.dur(out_mp4)) > 1.5:
            return done(False, f"exported file unusable or wrong length ({got.name})")
        keep = Path(out_mp4).with_name(Path(out_mp4).stem + "_pre_capcut.mp4")
        shutil.copy2(out_mp4, keep); shutil.copy2(got, out_mp4)
        return done(True, f"exported {got.name}; original kept as {keep.name}")
    except Exception as e:
        return done(False, f"{str(e)[:200]}")
