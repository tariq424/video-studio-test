"""Local LLM server for Explainer Studio. Runs inside WanGP's Python env (torch+cu128, mmgp, transformers)
and serves Qwen3-8B (the int8 copy WanGP already downloaded) on http://127.0.0.1:<port>.
POST /chat {"system": str, "user": str, "max_tokens": int} -> {"text": str, "tok_s": float}"""
import json, os, sys, time, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import torch
from transformers import AutoTokenizer, Qwen3ForCausalLM
from mmgp import offload

MODEL_DIR = sys.argv[2] if len(sys.argv) > 2 else r"C:\pinokio\api\wan.git\app\ckpts\qwen3_8b"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 7899
t0 = time.time()
tok = AutoTokenizer.from_pretrained(MODEL_DIR)
model = offload.fast_load_transformers_model(os.path.join(MODEL_DIR, "qwen3_8b_quanto_bf16_int8.safetensors"),
        modelClass=Qwen3ForCausalLM, defaultConfigPath=os.path.join(MODEL_DIR, "config.json"), writable_tensors=False)
model = model.to("cuda").eval()
print(f"LOCAL_LLM_READY port={PORT} load={time.time()-t0:.0f}s vram={torch.cuda.memory_allocated()/2**30:.1f}GB", flush=True)
lock = threading.Lock()

def chat(system, user, max_tokens=2048):
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": user}]
    ids = tok.apply_chat_template(msgs, add_generation_prompt=True, return_tensors="pt", enable_thinking=False).to("cuda")
    mask = torch.ones_like(ids)
    t = time.time()
    with torch.inference_mode():
        out = model.generate(ids, attention_mask=mask, max_new_tokens=max_tokens, do_sample=True, temperature=0.7, top_p=0.8, top_k=20,
                             repetition_penalty=1.05, pad_token_id=tok.eos_token_id)
    new = out[0, ids.shape[1]:]
    text = tok.decode(new, skip_special_tokens=True)
    text = text.split("</think>")[-1].strip()
    del out; torch.cuda.empty_cache()
    return text, len(new) / max(0.1, time.time() - t), ids.shape[1]

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, obj):
        b = json.dumps(obj).encode(); self.send_response(code)
        self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)
    def do_GET(self): self._send(200, {"ok": True})
    def do_POST(self):
        if self.path == "/quit":
            self._send(200, {"ok": True}); threading.Thread(target=lambda: (time.sleep(0.5), os._exit(0))).start(); return
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        try:
            with lock: text, tps, n_in = chat(req.get("system", ""), req["user"], int(req.get("max_tokens", 2048)))
            print(f"chat: in={n_in} tok, {tps:.1f} tok/s", flush=True)
            self._send(200, {"text": text, "tok_s": tps, "in_tokens": n_in})
        except Exception as e:
            torch.cuda.empty_cache(); self._send(500, {"error": repr(e)[:500]})

ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
