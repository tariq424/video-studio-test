"""Music under the narration (your own tracks; none = unchanged) and 1-3 random jokes per Short beat within the word budget."""
import json, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from studio import music, writer  # noqa: E402


def ff(*a): subprocess.run(["ffmpeg", "-v", "error", "-y", *map(str, a)], check=True)


def test_music_mix_and_no_tracks():
    tmp = Path(tempfile.mkdtemp()); mp4 = tmp / "v.mp4"
    ff("-f", "lavfi", "-i", "color=s=320x568:d=12:r=25", "-f", "lavfi", "-i", "sine=f=400:d=12", "-shortest", "-c:v", "libx264", "-c:a", "aac", mp4)
    cfg = {"jobs_dir": str(tmp / "jobs"), "music_generate": False}; logs = []
    before = mp4.read_bytes()
    assert not music.mix(mp4, cfg, logs.append) and mp4.read_bytes() == before   # no tracks: unchanged
    (tmp / "music" / "hook").mkdir(parents=True); (tmp / "music" / "bed").mkdir()
    ff("-f", "lavfi", "-i", "sine=f=110:d=4", tmp / "music" / "hook" / "tense.mp3")
    ff("-f", "lavfi", "-i", "sine=f=220:d=3", tmp / "music" / "bed" / "lofi.mp3")   # shorter than the video: looped
    assert music.mix(mp4, cfg, logs.append, hook_secs=3), logs
    d = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", mp4], capture_output=True, text=True).stdout)
    assert abs(d - 12) < 0.3
    rec = json.loads((tmp / "v_music.json").read_text()); assert rec["hook"].endswith("tense.mp3") and rec["bed"].endswith("lofi.mp3")


class FakeLLM:
    def __init__(self, *a): self.name = "fake"
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def trace(self, *_): return self
    def chat_json(self, system, user, max_tokens=0, check=None):
        k = int(user.split("Write ")[1].split(" ")[0]); j = {"asides": [f"Aside number {i} lands here." for i in range(k)]}
        check(j); return j


def test_extra_jokes_random_and_budget(monkeypatch):
    monkeypatch.setattr("studio.llm.LLM", FakeLLM)
    vo = "First fact here. Second fact here. Third fact here. Fourth fact here."
    plan = {"title": "T", "sections": [{"id": f"b{i}", "vo": vo, "punchline": "End joke."} for i in range(6)] + [{"id": "c", "vo": "x", "cta": True}]}
    writer.extra_jokes({"jokes_per_beat": [0, 0, 1]}, plan, lambda m: None)   # always 3 jokes: 2 asides inside each beat
    assert all(s["vo"].count("Aside number") == 2 and s["vo"].startswith("First fact here.") for s in plan["sections"][:6])
    assert "asides" not in plan["sections"][6]
    plan2 = {"title": "T", "sections": [{"id": f"b{i}", "vo": vo} for i in range(3)]}
    n0 = sum(len(s["vo"].split()) for s in plan2["sections"])
    writer.extra_jokes({"jokes_per_beat": [0, 0, 1]}, plan2, lambda m: None, budget=n0 + 5)   # no room: nothing added
    assert sum(len(s["vo"].split()) for s in plan2["sections"]) == n0
    plan3 = {"title": "T", "sections": [{"id": "b0", "vo": vo}]}
    writer.extra_jokes({"jokes_per_beat": [1, 0, 0]}, plan3, lambda m: None)   # one joke only: unchanged
    assert plan3["sections"][0]["vo"] == vo


def test_library_mood_choice_and_generation_cap(monkeypatch):
    import random
    from studio import music_gen
    tmp = Path(tempfile.mkdtemp()); cfg = {"jobs_dir": str(tmp / "jobs"), "music_generate_per_day": 1}
    (tmp / "music" / "bed").mkdir(parents=True)
    ff("-f", "lavfi", "-i", "sine=f=220:d=6", tmp / "music" / "bed" / "mine.mp3")
    ff("-f", "lavfi", "-i", "sine=f=330:d=6", tmp / "music" / "bed" / "classical_1.mp3")
    music.add_to_library(cfg, tmp / "music" / "bed" / "classical_1.mp3", "bed", "classical", "string quartet")
    lib = music.library(cfg)
    assert {x["file"]: x["mood"] for x in lib} == {"bed/classical_1.mp3": "classical", "bed/mine.mp3": "any"}
    rng = random.Random(1)
    assert music.choose(cfg, "bed", "classical", rng, print).name == "classical_1.mp3"   # fits: reused, nothing generated
    made = []
    def fake_gen(cfg_, desc, out, log, **kw):
        music_gen._count(cfg_); made.append(desc); ff("-f", "lavfi", "-i", "sine=f=440:d=6", out); return out
    monkeypatch.setattr(music_gen, "generate", fake_gen)
    f = music.choose(cfg, "bed", "cheerful", rng, print)   # nothing cheerful: one new track, added to the library
    assert made and "cheerful" in f.name and any(x["mood"] == "cheerful" for x in music.library(cfg))
    g = music.choose(cfg, "bed", "somber", rng, print)    # today's cap (1) reached: an existing track instead
    assert len(made) == 1 and g.parent.name == "bed" and "somber" not in g.name
