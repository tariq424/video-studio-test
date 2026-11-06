"""Music follows the narration's word timings: low under speech, smooth fades into and out of every pause."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from studio import music  # noqa: E402

CFG = {"music_under_voice_db": -18, "music_fade_up": 1.2, "music_fade_down": 1.0, "music_pause_min": 1.0}


def gain(expr, t):
    py = expr.replace("clip(", "_clip(")
    return eval(py, {"_clip": lambda x, a, b: max(a, min(b, x)), "min": min, "t": t})


def test_speech_spans_merge_words_into_spans():
    tl = {"beats": [{"start": 0.0, "words": [["a", 0.5, 1.0], ["b", 1.02, 1.5]]}, {"start": 4.0, "words": [["c", 0.0, 2.0]]}]}
    p = Path(tempfile.mkdtemp()) / "teaser.json"; p.write_text(json.dumps(tl))
    assert music.speech_spans(p) == [(0.5, 1.5), (4.0, 6.0)]
    assert music.speech_spans(Path(tempfile.mkdtemp()) / "missing.json") is None


def test_curve_is_low_under_speech_up_in_pauses_and_smooth():
    spans = [(0.5, 10.0), (13.0, 20.0)]
    expr, pauses = music.fade_curve(spans, 22.0, CFG)
    assert pauses == [(10.0, 13.0), (20.0, 27.0)]   # the 0.5 s before the first word is too short to count
    duck = 10 ** (-18 / 20)
    assert abs(gain(expr, 5.0) - duck) < 1e-3                 # under speech
    assert abs(gain(expr, 11.5) - 1.0) < 1e-3                 # middle of the pause: full level
    assert duck < gain(expr, 10.6) < 1.0                       # fading up, not a jump
    assert duck < gain(expr, 12.5) < 1.0                       # fading down before the next word
    assert abs(gain(expr, 13.0) - duck) < 1e-3                 # already low when the voice returns
    assert abs(gain(expr, 21.5) - 1.0) < 1e-3                 # after the last word the music comes up to the end
