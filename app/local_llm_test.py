import os, sys, time, requests, torch
try: requests.post("http://127.0.0.1:7899/quit", timeout=3); print("killed old server"); time.sleep(5)
except Exception: pass
free, total = torch.cuda.mem_get_info(); print(f"GPU free before load: {free/2**30:.1f} / {total/2**30:.1f} GB", flush=True)
from transformers import AutoTokenizer, Qwen3ForCausalLM
from mmgp import offload
D = r"C:\pinokio\api\wan.git\app\ckpts\qwen3_8b"
tok = AutoTokenizer.from_pretrained(D)
m = offload.fast_load_transformers_model(os.path.join(D, "qwen3_8b_quanto_bf16_int8.safetensors"), modelClass=Qwen3ForCausalLM,
      defaultConfigPath=os.path.join(D, "config.json"), writable_tensors=False).to("cuda").eval()
free, total = torch.cuda.mem_get_info(); print(f"GPU free after load: {free/2**30:.1f} GB; attn={m.config._attn_implementation}", flush=True)
text = open(r"F:\videos\explainer_studio\jobs\20260929_064605\src\transcript.txt", encoding="utf-8").read().split()[:3500]
msgs = [{"role": "user", "content": "Summarize in 5 bullets:\n" + " ".join(text)}]
ids = tok.apply_chat_template(msgs, add_generation_prompt=True, return_tensors="pt", enable_thinking=False).to("cuda")
print("prompt tokens", ids.shape[1], flush=True)
with torch.inference_mode():
    t = time.time(); out = m(ids, use_cache=True); torch.cuda.synchronize(); print(f"prefill {time.time()-t:.1f}s", flush=True)
    t = time.time(); g = m.generate(ids, attention_mask=torch.ones_like(ids), max_new_tokens=100, do_sample=False, pad_token_id=tok.eos_token_id)
    n = g.shape[1]-ids.shape[1]; print(f"generate {n} tok in {time.time()-t:.1f}s", flush=True)
free, total = torch.cuda.mem_get_info(); print(f"GPU free at end: {free/2**30:.1f} GB", flush=True)
print(tok.decode(g[0, ids.shape[1]:], skip_special_tokens=True)[:400]); print("TEST_DONE")
