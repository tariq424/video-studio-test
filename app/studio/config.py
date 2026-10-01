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
    "wangp_mcp": "http://127.0.0.1:42004/mcp/",
    "ffmpeg_dir": "C:/pinokio/api/wan.git/app/ffmpeg_bins",
    "jobs_dir": r"F:\videos\video_studio\jobs",   # outputs stay on F:\videos
    "vet_provider": "local",          # stock-clip vetting: local (Ollama vision) | zai | claude | off
    "vet_model": "qwen2.5vl:7b",
    "short_concurrency": "75%",       # 100% measured no faster (Oct 2026)
    "long_broll": True,               # long videos: use real stock footage first, AI stills/motion only where nothing fits
    "voice_ref_wav": str(ROOT / "assets" / "voice_ref_baritone.wav"),
    "voice_ref_text": "Every few months, someone announces that artificial intelligence is about to change everything. Some say it will end work as we know it. Others say it is mostly hype. Stanford economist Chad Jones has spent years building models to answer a simpler question.",
    "presenter_image": str(ROOT / "assets" / "presenter.jpg"),
    "presenter_prompt": "A documentary TV presenter in his mid 40s is talking to the camera, speaking clearly and animatedly, his mouth opening and closing with every word, lips and teeth visible as he talks, natural head nods and eyebrow movement, modern studio, static camera",
    "wpm": 155,
    "voice_wpm": 142,                 # real speaking pace of the cloned narrator (used to size Shorts so they land under 3:00)
    "seconds_per_visual": 7,
    "motion_share": 0.10,
    "still_model": "flux2_klein_9b",
    "video_model": "ltx2_distilled",
    "tts_model": "qwen3_tts_base",
    "image_qa": True,
}

SECRETS = ("anthropic_api_key", "zai_api_key", "deepseek_api_key")

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
