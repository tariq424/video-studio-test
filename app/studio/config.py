"""Settings stored in <studio>/settings.json (local only)."""
import json
from pathlib import Path
APP = Path(__file__).resolve().parent.parent
ROOT = APP.parent
CFG = ROOT / "settings.json"
DEFAULTS = {
    "script_provider": "deepseek",
    "qa_provider": "off",
    "anthropic_api_key": "",
    "zai_api_key": "",
    "zai_base_url": "https://api.z.ai/api/anthropic",
    "zai_model": "glm-5.2",
    "zai_openai_url": "https://api.z.ai/api/coding/paas/v4",
    "zai_vision_model": "glm-4.6v-flash",
    "deepseek_api_key": "",
    "deepseek_base_url": "https://api.deepseek.com/anthropic",
    "deepseek_model": "deepseek-v4-pro",
    "ollama_url": "http://127.0.0.1:11434",
    "ollama_model": "qwen3:14b",
    "script_model": "claude-opus-5-5",
    "qa_model": "claude-sonnet-5",
    "wangp_mcp": "",                 # blank = find WanGP automatically (Pinokio picks its MCP port at start-up)
    "wangp_dir": "C:/pinokio/api/wan.git",
    "ffmpeg_dir": "C:/pinokio/api/wan.git/app/ffmpeg_bins",
    "jobs_dir": r"F:\videos\video_studio\jobs",   # outputs stay on F:\videos
    "vet_provider": "local",          # stock-clip vetting: local (Ollama vision) | zai | claude | off
    "vet_model": "qwen2.5vl:7b",
    "short_concurrency": "75%",       # 100% measured no faster (Oct 2026)
    "visual_review_default": "never",  # jobs that don't say: never pause for unsure beats, decide on my own (auto | every | never)
    "pause_on_questions": False,     # skip review by default; True = pause only when the fact-check raised questions
    "long_broll": True,               # long videos: use real stock footage first, AI stills/motion only where nothing fits
    "voice_ref_wav": str(ROOT / "assets" / "voice_ref_baritone.wav"),
    "voice_ref_text": "Every few months, someone announces that artificial intelligence is about to change everything. Some say it will end work as we know it. Others say it is mostly hype. Stanford economist Chad Jones has spent years building models to answer a simpler question.",
    "presenter_image": str(ROOT / "assets" / "presenter.jpg"),
    "presenter_prompt": "A documentary TV presenter in his mid 40s is talking to the camera, speaking clearly and animatedly, his mouth opening and closing with every word, lips and teeth visible as he talks, natural head nods and eyebrow movement, modern studio, static camera",
    "wpm": 155,
    "voice_wpm": 155,                 # real speaking pace of the cloned narrator, measured over 16 Shorts (146-165, median ~155); sizes Shorts to their target length
    "seconds_per_visual": 7,
    "motion_share": 0.10,
    "still_model": "flux2_klein_9b",
    "long_renderer": "remotion",      # explainer: remotion (one timeline, the Short's captions) | ffmpeg (old stitcher; used when the presenter is on)
    "cloud_on": True,                 # visual ladder: cloud stills before WanGP (only if a provider is listed below)
    "cloud_providers": [],            # provider names from cloudgen.PROVIDERS, tried in order; [] = none (straight to WanGP)
    "cloud_timeout": 60,              # seconds per provider attempt
    "cloud_max_per_job": 8,           # cap on cloud attempts per video (expected use: 2-5)
    "video_model": "ltx2_distilled",
    "channel_name": "",
    "smoke_source": "https://youtu.be/xcQ7MhOMLrg",   # "smoke test" with no link: this video (its transcript is cached, so YouTube isn't contacted)
    "make_model": "phi4-mini",          # /make: the small local model that reads your description (Ollama)
    "make_model_fallback": "gemma3:4b",              # shown on the Short's 9:16 thumbnail when set
    "short_i2v": True,                # Short visual ladder step 3: animate the AI still with WanGP image-to-video
    "short_i2v_model": "ltx2_distilled",
    "short_i2v_steps": 8,
    "short_i2v_frames": 169,          # ~7 s at 24 fps
    "tts_model": "qwen3_tts_base",
    "tts_engine": "kokoro",           # narration: kokoro (preset voice, seconds; studio/tts.py) | wanGP (cloned voice, ~10-15 min per job)
    "tts_fallback": True,             # Kokoro unavailable or failing -> narrate with WanGP instead of stopping the job
    "kokoro_voice": "am_michael",     # Kokoro preset voice (only used when tts_engine is kokoro)
    "own_clips": False,
    "post_edit_v2": False,            # timeline editor: Remotion explainers editable slot by slot, Short/Explainer switch, open a job by ID,
                                      # chat "supply" / "card" actions (studio/edit.py); off = the editor as before               # job form "Provide clips": your footage matched to beats (studio/clips.py)
    "audience": "common",             # common (default) | beginner (more explanation) | informed | expert (writer.AUDIENCE)
    "kokoro_speed": 1.0,
    "kokoro_wpm": 140,                # Kokoro's pace for sizing Shorts (am_michael at speed 1.0: 139.5-139.7 wpm, measured 2026-10-12)
    "kokoro_online": False,           # False: the worker runs with HF_HUB_OFFLINE=1 (model cached by install_kokoro.js)
    "kokoro_python": "",              # "" = app/kenv (pinokio/install_kokoro.js)
    "kokoro_device": "",              # "" = cuda when available
    "image_qa": True,
    # ---- visual ladder v2 (Oct 2026). Everything below is OFF by default: with ladder_v2 False the old ladder runs unchanged.
    # v2 order: 1 stock -> 2 real photos -> 3 cloud still -> 4 WanGP still (atmospheric only) -> 5 Remotion graphics (GRAPHICS)
    # -> 6 physics module (SIMULATION) -> 7 CapCut (CAPCUT) -> 8 parallax -> 9 illustration / silhouette -> 10 headline card.
    # The 3D reconstruction rung (incl. the generic "object" spinning top) is not part of v2.
    "ladder_v2": False,               # master switch for the v2 order (Shorts: short.do_fallback; explainers: render.do_stills / do_motion)
    "graphics_secs": 8,               # length of a rendered GRAPHICS clip (6-10 s)
    "graphics_claude": True,          # v2: when no template fits, Claude writes a Remotion composition for the beat
    "graphics_claude_model": "",      # "" = script_model with the Anthropic key; falls back to the script provider without one
    "graphics_claude_max_per_video": 3,   # cost cap: Claude-written compositions per video (one write + one repair each)
    "graphics_timeout": 300,          # seconds per GRAPHICS render before it counts as a hard failure
    "physics_auto": True,             # v2: physics modules join the ladder (only when the beat's subject matches a module)
    "capcut_fallback": False,         # rung 7: CapCut assembles the failed beats (needs VectCutAPI + computer use); separate switch
    "capcut_api_url": "http://127.0.0.1:9001",   # VectCutAPI server (github.com/sun-guannan/VectCutAPI)
    "capcut_api_dir": "",             # VectCutAPI's folder (where it writes dfd_<id> draft folders)
    "capcut_drafts_dir": "",          # CapCut's draft folder; "" = %LOCALAPPDATA%/CapCut/User Data/Projects/com.lveditor.draft
    "capcut_exe": "",                 # "" = %LOCALAPPDATA%/CapCut/Apps/CapCut.exe
    "capcut_cu_model": "claude-sonnet-5",   # model that drives the CapCut Export clicks (computer use, Anthropic key)
    "capcut_cu_tool": "computer_20250124",   # computer-use tool version / beta header for that model
    "capcut_cu_beta": "computer-use-2025-01-24",
    "capcut_max_actions": 30,         # computer-use budget per video (screenshots + clicks)
    "capcut_timeout": 600,            # seconds for the whole CapCut session (draft + export)
    "aisstream_api_key": "",          # optional (aisstream.io, free): live AIS position for ship_route when the narration gives an MMSI
}

SECRETS = ("anthropic_api_key", "zai_api_key", "deepseek_api_key", "aisstream_api_key")

VAULT = "ExplainerStudio"   # shared with Explainer Studio so saved keys carry over

def _kr():
    try:
        import keyring; return keyring
    except Exception: return None

def _vault_get(name):
    kr = _kr()
    try: return (kr.get_password(VAULT, name) or "") if kr else ""
    except Exception: return ""

def _vault_set(name, value):
    kr = _kr()
    if not kr: raise RuntimeError("Windows Credential Manager not available (keyring missing)")
    if value: kr.set_password(VAULT, name, value)
    else:
        try: kr.delete_password(VAULT, name)
        except Exception: pass

def _raw():
    if CFG.exists():
        try: return json.loads(CFG.read_text(encoding="utf-8"))
        except Exception: pass
    return {}

def _migrate():
    """Move any plain-text keys from settings.json into the Windows vault."""
    raw = _raw(); changed = False
    for k in SECRETS:
        v = raw.get(k, "")
        if v and v != "vault":
            _vault_set(k, v); raw[k] = "vault"; changed = True
    if changed: CFG.write_text(json.dumps(raw, indent=1), encoding="utf-8")

def load():
    d = dict(DEFAULTS)
    try: _migrate()
    except Exception: pass
    d.update(_raw())
    for k in SECRETS: d[k] = _vault_get(k)
    return d

def save(upd):
    raw = _raw()
    for k, v in upd.items():
        if k in DEFAULTS and v is not None:
            if k in SECRETS:
                v = v.strip()
                if v == "" or v.startswith("••"): continue
                if v == "delete": v = ""
                _vault_set(k, v); raw[k] = "vault" if v else ""
            else: raw[k] = v
    CFG.write_text(json.dumps(raw, indent=1), encoding="utf-8")
    return load()

def public(d=None):
    d = dict(d or load())
    for s in SECRETS:
        k = d.get(s, ""); d[s] = ("••••" + k[-4:]) if k else ""
    return d
