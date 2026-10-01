"""One text interface over three script engines: Claude API, z.ai (GLM) API, or local Qwen3-8B on the GPU."""
import base64, io, json, os, re, subprocess, time
from pathlib import Path
import requests

APP = Path(__file__).resolve().parent.parent

class LocalServer:
    """Local model via Ollama (http://127.0.0.1:11434). Unloads the model afterwards to free the GPU for WanGP."""
    def __init__(self, cfg, log):
        self.cfg, self.log = cfg, log
        self.url = cfg.get("ollama_url", "http://127.0.0.1:11434").rstrip("/")
        self.model = cfg.get("ollama_model", "qwen3:14b")
    def start(self):
        try: tags = requests.get(self.url + "/api/tags", timeout=5).json()
        except Exception: raise RuntimeError("Local AI needs Ollama running (https://ollama.com). Install it, or pick z.ai/Claude in Settings.")
        if not any(m.get("name", "").startswith(self.model) for m in tags.get("models", [])):
            self.log(f"  downloading {self.model} into Ollama (one time, several GB)...")
            r = requests.post(self.url + "/api/pull", json={"model": self.model, "stream": False}, timeout=7200)
            if r.status_code != 200: raise RuntimeError(f"Ollama pull failed: {r.text[:300]}")
        self.log(f"  local model {self.model} ready")
    def chat(self, system, user, max_tokens):
        msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": user}]
        r = requests.post(self.url + "/api/chat", timeout=3600, json={"model": self.model, "messages": msgs, "stream": False,
            "think": False, "keep_alive": "10m", "options": {"num_ctx": 16384, "num_predict": max_tokens, "temperature": 0.6}})
        if r.status_code != 200: raise RuntimeError(f"Ollama error {r.status_code}: {r.text[:300]}")
        t = r.json()["message"]["content"]
        t = re.sub(r"<think>.*?</think>", "", t, flags=re.S).strip()
        if not t: raise RuntimeError("empty answer from local model")
        return t
    def stop(self):
        try: requests.post(self.url + "/api/generate", json={"model": self.model, "keep_alive": 0}, timeout=30)
        except Exception: pass

class LLM:
    def __init__(self, cfg, log, stop=None):
        self.cfg, self.log, self.stop_evt = cfg, log, stop
        self.provider = cfg.get("script_provider", "claude")
        self.local = LocalServer(cfg, log) if self.provider == "local" else None
        self.tokens_in = self.tokens_out = 0
    def __enter__(self):
        if self.local: self.local.start()
        return self
    def __exit__(self, *a):
        if self.local: self.local.stop()
    @property
    def chunk_words(self):  # transcript words per map chunk
        return 5000 if self.provider == "local" else 7000
    @property
    def name(self):
        return {"claude": self.cfg["script_model"], "zai": self.cfg["zai_model"], "deepseek": self.cfg["deepseek_model"], "local": self.cfg.get("ollama_model", "qwen3:14b") + " (local)"}[self.provider]

    def chat(self, system, user, max_tokens=4000):
        for attempt in range(4):
            try: return self._chat(system, user, max_tokens)
            except Exception as e:
                if attempt == 3: raise
                self.log(f"  model call failed ({str(e)[:120]}), retrying"); time.sleep(10 * (attempt + 1))

    def _chat(self, system, user, max_tokens):
        if self.provider == "local":
            return self.local.chat(system, user, max_tokens)
        import anthropic
        if self.provider in ("zai", "deepseek"):
            p = self.provider
            c = anthropic.Anthropic(api_key=self.cfg[p + "_api_key"], base_url=self.cfg[p + "_base_url"])
            model = self.cfg[p + "_model"]
        else:
            c = anthropic.Anthropic(api_key=self.cfg["anthropic_api_key"]); model = self.cfg["script_model"]
        kw = {}
        if self.provider in ("zai", "deepseek"):
            kw["thinking"] = {"type": "disabled"}   # reasoning would eat max_tokens and leave the answer empty
        with c.messages.stream(model=model, max_tokens=max_tokens, system=system,
                               messages=[{"role": "user", "content": user}], **kw) as st:
            m = st.get_final_message()
        try: self.tokens_in += m.usage.input_tokens; self.tokens_out += m.usage.output_tokens
        except Exception: pass
        text = "".join(b.text for b in m.content if getattr(b, "type", "") == "text").strip()
        if not text:
            kinds = ",".join(getattr(b, "type", "?") for b in m.content)
            raise RuntimeError(f"empty answer from {model} (blocks: {kinds or 'none'}, stop: {getattr(m, 'stop_reason', '?')})")
        return text

    def chat_json(self, system, user, max_tokens=4000, check=None):
        """Ask for JSON, parse leniently, re-ask with the error if it doesn't parse or fails check()."""
        msg = user
        for attempt in range(3):
            t = self.chat(system, msg, max_tokens)
            try:
                j = parse_json(t)
                if check: check(j)
                return j
            except Exception as e:
                self.log(f"  output not usable ({str(e)[:100]}), asking again")
                msg = user + f"\n\nYour previous answer could not be used ({str(e)[:200]}). Reply with ONLY valid JSON in the required format."
        raise RuntimeError("Model did not return valid JSON after 3 tries")

def parse_json(t):
    t = re.sub(r"^```(json)?|```$", "", t.strip(), flags=re.M).strip()
    i = min([x for x in (t.find("{"), t.find("[")) if x >= 0], default=-1)
    if i < 0: raise ValueError("no JSON found")
    t = t[i:]
    try: return json.loads(t)
    except Exception:
        from json_repair import repair_json
        return json.loads(repair_json(t))

# ---------- image QA ----------
def _jpeg_b64(path):
    from PIL import Image
    im = Image.open(path).convert("RGB"); im.thumbnail((1280, 1280))
    b = io.BytesIO(); im.save(b, "JPEG", quality=85); return base64.b64encode(b.getvalue()).decode()

def qa_available(cfg):
    p = cfg.get("qa_provider", "claude")
    if not cfg.get("image_qa") or p == "off": return False
    return bool(cfg.get({"claude": "anthropic_api_key", "zai": "zai_api_key", "deepseek": "deepseek_api_key"}.get(p, "-")))

def vision(cfg, image_path, text):
    p = cfg.get("qa_provider", "claude"); b64 = _jpeg_b64(image_path)
    if p == "zai":
        r = requests.post(cfg["zai_openai_url"].rstrip("/") + "/chat/completions", timeout=180,
            headers={"Authorization": "Bearer " + cfg["zai_api_key"], "Content-Type": "application/json"},
            json={"model": cfg["zai_vision_model"], "max_tokens": 300, "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}},
                {"type": "text", "text": text}]}]})
        r.raise_for_status(); c = r.json()["choices"][0]["message"]["content"]
        return c if isinstance(c, str) else " ".join(x.get("text", "") for x in c)
    import anthropic
    if p == "deepseek": c = anthropic.Anthropic(api_key=cfg["deepseek_api_key"], base_url=cfg["deepseek_base_url"]); mdl = cfg["deepseek_model"]
    else: c = anthropic.Anthropic(api_key=cfg["anthropic_api_key"]); mdl = cfg["qa_model"]
    kw = {"thinking": {"type": "disabled"}} if p == "deepseek" else {}
    m = c.messages.create(model=mdl, max_tokens=400, **kw, messages=[{"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
        {"type": "text", "text": text}]}])
    return "".join(x.text for x in m.content if getattr(x, "type", "") == "text")
