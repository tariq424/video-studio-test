"""Story QC (Nov 7): every background shot of the finished video is checked against the narration; the source's own clips
are skipped and flagged shots become repair spans."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from studio import storyqc  # noqa: E402

TL = {"beats": [
    {"id": "b0", "start": 0.0, "dur": 20.0, "words": [["Weiss", 0, 1], ["speaks", 1, 2]],
     "bgs": [{"src": "media/stock/a.mp4", "from": 0.0, "tag": "ILLUSTRATIVE"},
             {"src": "media/fb/src.mp4", "from": 8.0, "tag": "SOURCE · Piers Morgan Uncensored"},
             {"src": "media/stock/b.mp4", "from": 12.0, "tag": "ILLUSTRATIVE"}]},
    {"id": "b1", "start": 20.0, "dur": 5.0, "cta": True, "bgs": [{"src": "x", "from": 0.0}]},
]}


def test_shots_skip_source_and_cta():
    sh = storyqc.shots(TL)
    assert [(s["a"], s["b"]) for s in sh] == [(0.0, 8.0), (12.0, 20.0)]
    assert all(s["vo"] == "Weiss speaks" for s in sh)
    assert all(s["a"] < s["t"] < s["b"] for s in sh)


def test_marks_merge_touching_spans():
    m = storyqc.marks([{"a": 26.8, "b": 35.0}, {"a": 35.0, "b": 43.1}, {"a": 159.1, "b": 168.5}])
    assert m == [(26.8, 43.1, ["off_story"]), (159.1, 168.5, ["off_story"])]


def test_off_switch(tmp_path):
    assert storyqc.check(tmp_path / "x.mp4", {"story_qc_on": False}, tmp_path, print) == []


def test_repair_marks_timeline(tmp_path):
    import json
    from studio import qc_repair
    pub = tmp_path / "short" / "public"; pub.mkdir(parents=True)
    (pub / "teaser.json").write_text(json.dumps(TL), encoding="utf-8")
    assert qc_repair.mark_timeline(tmp_path, True, 0.0, 8.0, "ai_image", "AI image (cloudflare) -> image-to-video") == 1
    bgs = json.loads((pub / "teaser.json").read_text(encoding="utf-8"))["beats"][0]["bgs"]
    assert bgs[0]["tag"] == "GENERATED · CLOUDFLARE" and bgs[0]["qc_repair"]["rung"] == "ai_image"
    assert "qc_repair" not in bgs[1] and "qc_repair" not in bgs[2]


def test_long_shots_get_a_second_frame():
    sh = storyqc.shots(TL)
    assert all(len(s["ts"]) == 2 and s["a"] < s["ts"][0] < s["ts"][1] < s["b"] for s in sh)
    short = storyqc.shots({"beats": [{"id": "b0", "start": 0, "dur": 3.0, "bgs": [{"src": "a", "from": 0}]}]})
    assert short[0]["ts"] == [short[0]["t"]]


def test_verify_pass_checks_only_repaired_spans(tmp_path, monkeypatch):
    from studio import footage, media
    import studio.llm as llm_mod
    monkeypatch.setattr(storyqc, "_timeline", lambda *a: TL)
    calls = []
    def ff(*a, **k):
        from pathlib import Path as P
        P(a[-1]).write_bytes(b"x")
    monkeypatch.setattr(media, "ff", ff)
    monkeypatch.setattr(footage, "_vision", lambda cfg, img, p: calls.append(img) or '{"shows": "a desert road"}')
    monkeypatch.setattr(footage, "unload_vet_model", lambda cfg: None)
    class L:
        name = "fake"
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def chat_json(self, *a, **k): return {"contradicts": False, "why": "ok"}
    monkeypatch.setattr(llm_mod, "LLM", L)
    assert storyqc.check(tmp_path / "v.mp4", {}, tmp_path, print, only=[(12.0, 20.0)]) == []
    assert len(calls) == 2   # one shot (12-20 s), two frames
    assert (tmp_path / "qc" / "v.story_verify.json").exists() and not (tmp_path / "qc" / "v.story.json").exists()
