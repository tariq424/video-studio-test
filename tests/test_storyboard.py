"""Storyboard rung (Nov 7): ~4 s pieces, standalone prompts that restate one locked style, pictures from the image services."""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from studio import storyboard  # noqa: E402
import studio.llm as llm_mod  # noqa: E402

VO = ("Weiss doesn't hide the end game. The land belongs only to the people of Israel, she says. Her movement just moved "
      "families into a new settlement. Youssef asks what happens to two million people. She says they can leave.")


def test_pieces_are_about_four_seconds_and_cover_everything():
    p = storyboard.pieces(VO, 140)   # 140 wpm -> ~9 words per 4 s
    assert " ".join(p).split() == VO.split()
    assert len(p) >= 3 and all(5 <= len(x.split()) <= 16 for x in p)


def test_prompts_restate_the_locked_style(monkeypatch):
    class L:
        name = "fake"
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def chat_json(self, system, prompt, max_tokens=0, check=None):
            n = prompt.count('\n') and int(prompt.split("exactly ")[1].split(" ")[0])
            x = {"shots": [{"piece": i + 1, "prompt": "A dusty hilltop with new prefabricated homes at dawn, wide shot, families carrying boxes, "
                            "quiet determined mood, soft light", "motion": "slow push in"} for i in range(n)]}
            if check: check(x)
            return x
    monkeypatch.setattr(llm_mod, "LLM", L)
    parts = storyboard.pieces(VO, 140)
    prof = dict(storyboard.DEFAULT_STYLE, art_style="gritty handheld documentary")
    shots = storyboard.write_prompts({}, {"id": "b1", "vo": VO}, parts, prof, VO)
    assert len(shots) == len(parts) and all("gritty handheld documentary" in s["prompt"] for s in shots)


def test_beat_makes_tagged_options_and_never_raises(tmp_path, monkeypatch):
    from studio import imagegen
    sd = tmp_path / "short"; (sd / "imagegen").mkdir(parents=True)
    monkeypatch.setattr(storyboard, "style_profile", lambda cfg, sd, log: dict(storyboard.DEFAULT_STYLE, _from="default"))
    monkeypatch.setattr(storyboard, "write_prompts", lambda cfg, sec, parts, prof, story, log: [
        {"piece": i + 1, "text": p, "prompt": "x " * 20, "motion": "push"} for i, p in enumerate(parts)])
    made = []
    def gen(cfg, sd_, sec, key, log, aspect="9:16", **k):
        assert sec["described_prompt"].startswith("x ") and "gemini" not in cfg.get("imagegen_providers", [])
        f = sd / "imagegen" / f"{key}.jpg"; f.write_bytes(b"x"); made.append(key); return [(f, "p")]
    monkeypatch.setattr(imagegen, "generate_many", gen)
    monkeypatch.setattr(imagegen, "last_site", lambda: "cloudflare")
    items = storyboard.beat({"kokoro_wpm": 140, "tts_engine": "kokoro"}, sd, {"id": "b1", "vo": VO}, VO, print)
    assert items and all(i["tag"] == "GENERATED · CLOUDFLARE" and i["rung"] == "storyboard" for i in items)
    assert json.loads((sd / "storyboard" / "b1.json").read_text(encoding="utf-8"))["shots"]
    monkeypatch.setattr(storyboard, "write_prompts", lambda *a: (_ for _ in ()).throw(ValueError("bad answer")))
    assert storyboard.beat({}, sd, {"id": "b2", "vo": VO}, VO, print) == []


def test_check_first_then_generate_from_the_saved_plan(tmp_path, monkeypatch):
    from studio import imagegen
    sd = tmp_path / "short"; (sd / "imagegen").mkdir(parents=True)
    monkeypatch.setattr(storyboard, "style_profile", lambda cfg, sd, log: dict(storyboard.DEFAULT_STYLE))
    monkeypatch.setattr(storyboard, "write_prompts", lambda cfg, sec, parts, prof, story, log: [
        {"piece": i + 1, "text": p, "prompt": f"planned prompt {i}", "motion": ""} for i, p in enumerate(parts)])
    p = storyboard.plan({"kokoro_wpm": 140}, sd, {"id": "b3", "vo": VO}, VO, print)
    assert p["status"] == "planned" and storyboard.saved(sd, "b3")["shots"]
    monkeypatch.setattr(storyboard, "write_prompts", lambda *a: (_ for _ in ()).throw(AssertionError("must reuse the checked plan")))
    seen = []
    def gen(cfg, sd_, sec, key, log, aspect="9:16", **k):
        seen.append(sec["described_prompt"]); f = sd / "imagegen" / f"{key}.jpg"; f.write_bytes(b"x"); return [(f, "p")]
    monkeypatch.setattr(imagegen, "generate_many", gen); monkeypatch.setattr(imagegen, "last_site", lambda: "cloudflare")
    items = storyboard.beat({}, sd, {"id": "b3", "vo": VO}, VO, print, use_saved=True)
    assert len(items) == len(p["shots"]) and seen[0] == "planned prompt 0"
    assert storyboard.saved(sd, "b3")["status"] == "generated"
