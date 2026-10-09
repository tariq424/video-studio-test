"""One-off test: Beat 1 of job 20261008_210038 with the new six-slot image-prompt instruction.
DeepSeek writes the image prompt -> WanGP (same model, steps, size, seed 5100 + two more seeds, now with the negative prompt) ->
the same vision check. Results in F:/code/video-studio/_tests/prompt_test/."""
import json, sys, shutil
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from studio import config, short, render, ladder
from studio.llm import LLM
from studio.wangp import WanGP
cfg = config.load(); log = lambda m: print(m, flush=True)
job = Path(cfg["jobs_dir"]) / "20261008_210038"
sec = json.loads((job / "short" / "plan.json").read_text(encoding="utf-8"))["sections"][0]
out = config.ROOT / "_tests" / "prompt_test2"; out.mkdir(parents=True, exist_ok=True)
rules = '- "still_prompt":' + short.SHORT.split('- "still_prompt":', 1)[1].split('- "motion":', 1)[0]
rules = rules.replace("{examples}", short.still_examples()).replace("{{", "{").replace("}}", "}")
subj = sec.get("subject") or {}
prompt = (f'You are writing ONE field of a vertical news Short script.\nBeat narration: "{sec["vo"]}"\n'
          f'Subject of the beat: {subj.get("name", "none")} (describe it by type, shape and colours only: a white twin-engine single-aisle '
          f'airliner with a plain dark blue tail; never the airline name)\n\nField rules:\n{rules}\nReply with ONLY JSON: {{"still_prompt": "..."}}')
c = dict(cfg); c["script_provider"] = "deepseek"
def chk(j):
    if len(str(j.get("still_prompt", "")).split()) < 35: raise ValueError("still_prompt must be 45-75 words with all six slots")
with LLM(c, log, lambda: False) as llm:
    sp = llm.chat_json("You write image-model prompts for a news video. Reply with JSON only.", prompt, max_tokens=800, check=chk)["still_prompt"]
log("NEW PROMPT: " + sp)
res = {"narration": sec["vo"], "old_prompt": sec["still_prompt"] + render.STYLE, "new_prompt": sp + render.STYLE, "negative": render.negative("air"), "images": []}
shutil.copy2(job / "short" / "fallback" / "b0_0.jpg", out / "old_seed5100.jpg")
res["images"].append({"file": "old_seed5100.jpg"})
wg = WanGP(cfg)
for seed in (5100, 5101, 5102):
    g = wg.gen({"model_type": cfg["still_model"], "prompt": sp + render.STYLE, "negative_prompt": render.negative(ladder._phase(sec)), "resolution": "1088x1920",
                "num_inference_steps": 4, "seed": seed}, log, f"test still {seed}")
    if not g["ok"]: res["images"].append({"file": None, "seed": seed, "err": g.get("err")}); continue
    f = out / f"new_seed{seed}.jpg"; shutil.copy(g["file"], f)
    res["images"].append({"file": f.name, "seed": seed})
from studio import footage
footage.ensure_vet_model(cfg, log)
for f in ("new_seed5100.jpg", "new_seed5101.jpg", "new_seed5102.jpg"):   # round 1 images, re-judged by the new check
    src = config.ROOT / "_tests" / "prompt_test" / f
    if src.exists(): shutil.copy2(src, out / f"round1_{f}"); res["images"].append({"file": f"round1_{f}"})
for im in res["images"]:
    if im.get("file"):
        ok, why = ladder.check(cfg, out / im["file"], sec["vo"], sec.get("subject")); im["check_ok"], im["check"] = ok, why
footage.unload_vet_model(cfg)
(out / "result.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
log("DONE " + json.dumps(res["images"]))
