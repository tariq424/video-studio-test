"""Hugging Face talking head for Shorts: endpoint picked from the Space's API, result video found, round PIP laid over the
hook beat, and any failure leaves the Short unchanged."""
import json, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from studio import talkinghead  # noqa: E402


class FakeClient:
    def view_api(self, **kw):
        return {"named_endpoints": {
            "/lambda": {"parameters": [{"component": "Textbox", "parameter_name": "x"}]},
            "/generate": {"parameters": [
                {"component": "Image", "parameter_name": "image"}, {"component": "Audio", "parameter_name": "audio"},
                {"component": "Slider", "parameter_name": "steps", "parameter_has_default": True, "parameter_default": 25}]}}}


def ff(*a): subprocess.run(["ffmpeg", "-v", "error", "-y", *map(str, a)], check=True)


def test_endpoint_and_result():
    api, params = talkinghead.endpoint(FakeClient())
    assert api == "/generate" and [talkinghead._kind(p) for p in params] == ["image", "audio", None]
    tmp = Path(tempfile.mkdtemp()); v = tmp / "o.mp4"; v.write_bytes(b"x")
    assert talkinghead._video_in(({"video": str(v), "subtitles": None}, "log")) == str(v)
    assert talkinghead._video_in(["not a file.mp4", 3]) is None


def _short(tmp):
    job = tmp / "J"; (job / "short" / "public").mkdir(parents=True); (job / "output").mkdir()
    (job / "short" / "public" / "teaser.json").write_text(json.dumps({"beats": [{"start": 0, "dur": 3}, {"start": 3, "dur": 3}]}))
    mp4 = job / "output" / "T_short.mp4"
    ff("-f", "lavfi", "-i", "color=c=blue:s=540x960:d=6:r=30", "-f", "lavfi", "-i", "sine=f=300:d=6", "-shortest",
       "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", mp4)
    return job, mp4


def test_overlay_and_failure(monkeypatch):
    tmp = Path(tempfile.mkdtemp()); job, mp4 = _short(tmp)
    def fake_make(img, audio, out, cfg, log):
        assert Path(audio).exists()
        ff("-f", "lavfi", "-i", "color=c=red:s=512x512:d=3:r=25", "-c:v", "libx264", "-pix_fmt", "yuv420p", out); return out, "test/space"
    monkeypatch.setattr(talkinghead, "make", fake_make)
    monkeypatch.setattr(talkinghead, "presenter_photo", lambda cfg, log: tmp / "p.jpg")
    monkeypatch.setattr("studio.edit.ensure_keyframes", lambda *a, **k: None)
    logs = []
    talkinghead.overlay_short(job, {}, {}, mp4, logs.append)
    rec = json.loads((job / "short" / "talkinghead" / "talkinghead.json").read_text())
    assert rec["ok"] and rec["space"] == "test/space", logs
    # the PIP is red at its centre during the hook, gone afterwards; the audio is kept
    def px(t):
        return subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", mp4, "-frames:v", "1", "-vf", "crop=2:2:228:448", "-f", "rawvideo",
                               "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout[:3]
    assert px(1)[0] > 150 and px(1)[2] < 100 and px(5)[2] > 150
    assert "audio" in subprocess.run(["ffprobe", "-v", "error", "-show_streams", mp4], capture_output=True, text=True).stdout
    before = mp4.read_bytes()
    (job / "short" / "talkinghead" / "head.mp4").unlink()   # a head made earlier would be reused; this checks a failure
    monkeypatch.setattr(talkinghead, "make", lambda *a: (_ for _ in ()).throw(RuntimeError("quota")))
    talkinghead.overlay_short(job, {}, {}, mp4, logs.append)
    assert mp4.read_bytes() == before and not json.loads((job / "short" / "talkinghead" / "talkinghead.json").read_text())["ok"]


def test_wangp_engine_falls_back_to_spaces(tmp_path, monkeypatch):
    from studio import talkinghead as T
    calls = []
    def bad(*a, **k): calls.append("wangp"); raise RuntimeError("WanGP is not installed or reachable on this computer")
    def space(sp, img, audio, out, cfg, log, timeout=None): calls.append(sp); Path(out).write_bytes(b"x"); return out
    monkeypatch.setattr(T, "wangp_clip", bad); monkeypatch.setattr(T, "call", space)
    out, eng = T.make("p.jpg", "a.wav", tmp_path / "o.mp4", {"talking_head": "wangp", "talking_head_spaces": ["a/b"]}, lambda m: None)
    assert calls == ["wangp", "a/b"] and eng == "a/b"
    assert T.enabled({"talking_head": "wangp"}) and T.enabled({}) and not T.enabled({"talking_head": "off"})


def test_reason_lines():
    from studio import talkinghead as T
    assert "used up" in T.reason(RuntimeError("You have exceeded your free ZeroGPU quota (90s requested vs. 0s left)"))
    assert "down or gone" in T.reason(RuntimeError("fffiloni/sonic: 404 Client Error. Repository Not Found"))
