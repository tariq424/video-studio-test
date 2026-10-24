"""Interview edit: cold-open hook located from an exact quote; filters build."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from studio import interview as I  # noqa: E402

SEGS = [{"i": 0, "text": "hello there", "words": [["hello", 0, 0.5], ["there", 0.5, 1]]},
        {"i": 1, "text": "They took her property, and they took her land. Wow.",
         "words": [["They", 10, 10.2], ["took", 10.2, 10.4], ["her", 10.4, 10.5], ["property,", 10.5, 11], ["and", 11, 11.1],
                   ["they", 11.1, 11.2], ["took", 11.2, 11.4], ["her", 11.4, 11.5], ["land.", 11.5, 12], ["Wow.", 12.2, 12.5]]}]


class FakeLLM:
    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def chat_json(self, system, user, max_tokens=0, check=None):
        j = {"seg": 1, "quote": "They took her property, and they took her land.", "text": "They took her land"}
        if check: check(j)
        return j


def test_hook(tmp_path, monkeypatch):
    import studio.llm
    monkeypatch.setattr(studio.llm, "LLM", FakeLLM)
    h = I.hook({}, SEGS, "ctx", "short", tmp_path, lambda m: None)
    assert h and abs(h["t0"] - 9.85) < 0.01 and abs(h["t1"] - 12.35) < 0.01 and h["text"] == "They took her land"
    assert (tmp_path / "hook_short.json").exists()


def test_filters():
    assert I._vf("short", 0.3, 1.12).startswith("hflip,crop=")
    assert "hflip" not in I._vf("documentary", None, 1.0, flip=False)
