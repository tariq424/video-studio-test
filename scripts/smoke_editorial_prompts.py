"""Live DeepSeek examples using the actual writer, fact check, and jargon review."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
assert ROOT == Path(r"F:\code\video-studio-test")
sys.path.insert(0, str(ROOT / "app"))
from studio import config, short, writer
from studio.llm import LLM

out = Path(r"F:\videos_test\evidence\editorial_source_features")
out.mkdir(parents=True, exist_ok=True)
text = (ROOT / "tests/fixtures/e2e/provided-script.txt").read_text(encoding="utf-8")
for audience in ("common", "beginner"):
    src = out / audience / "src"
    src.mkdir(parents=True, exist_ok=True)
    cfg = {**config.load(), "script_provider": "deepseek", "audience": audience, "graphics_claude": False}
    meta = {"title": "Synthetic ship tracking is an illustration, not observation", "channel": "Labeled test fixture"}
    if "--recheck" in sys.argv:
        plan = json.loads((src.parent / "plan.json").read_text(encoding="utf-8"))
        closing = [s for s in plan["sections"] if s.get("cta")]
        plan["sections"] = [s for s in plan["sections"] if not s.get("cta")]
        with LLM(cfg, print, lambda: False) as llm:
            llm.trace_dir = src.parent / "prompts"
            writer.editorial_review(llm, plan, meta, text, cfg, print)
        plan["sections"].extend(closing)
    else:
        plan = short.write_short(cfg, meta, text, 30, "short", "", print,
                                 lambda: False, src, smoke=True)
    for s in plan["sections"]:
        if not s.get("cta"):
            assert all(phrase in s["vo"] for phrase in s["editorial"].values())
    (src.parent / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    for section in plan["sections"]:
        print(audience, section["id"], section["vo"], flush=True)
