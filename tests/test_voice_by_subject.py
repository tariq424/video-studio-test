"""Nov 7: each job gets a Kokoro narrator that suits its subject; the Short's length budget uses that voice's own pace."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from studio import tts  # noqa: E402
import studio.llm as llm_mod  # noqa: E402


def fake_llm(answer):
    class L:
        name = "fake"
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def chat_json(self, *a, **k): return answer
    return L


def test_pace_follows_the_voice():
    cfg = {"tts_engine": "kokoro", "kokoro_wpm": 140}
    assert tts.wpm(dict(cfg, kokoro_voice="am_michael")) == 140
    assert round(tts.wpm(dict(cfg, kokoro_voice="am_fenrir"))) == 187   # a faster reader fits more words in the same seconds
    assert tts.wpm(dict(cfg, kokoro_voice="unknown_voice")) == 140


def test_pick_by_subject(monkeypatch):
    cfg = {"tts_engine": "kokoro"}
    monkeypatch.setattr(llm_mod, "LLM", fake_llm({"voice": "am_fenrir", "why": "a war story"}))
    assert tts.pick_voice(cfg, "Settlers want Gaza", "war and occupation", print) == "am_fenrir"
    monkeypatch.setattr(llm_mod, "LLM", fake_llm({"voice": "bm_george"}))   # not on the menu
    assert tts.pick_voice(cfg, "x", "y", print) == "am_michael"
    assert tts.pick_voice(dict(cfg, voice_by_subject=False, kokoro_voice="af_heart"), "x", "y", print) == "af_heart"
    assert tts.pick_voice({"tts_engine": "wanGP"}, "x", "y", print) == "am_michael"
