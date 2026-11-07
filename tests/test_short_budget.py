"""Short length budget (Nov 7): a 120 s Short came out at 224 s because the punch-up jokes and the musical pauses were never
counted. The script budget now sets them aside, so the finished narration fits the requested length."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from studio import short  # noqa: E402

CFG = {"music_on": True, "breathers": True, "breather_hook_secs": 3.0, "breather_secs": 3.0, "breather_every": 1, "punch_up": True}
WPM = 150


def spoken(cfg, secs):
    """Seconds the finished Short runs when the script hits its budget exactly and every beat gets its joke."""
    nb, total, words, wmax = short.plan_length(cfg, secs, WPM)
    return (total + 16) / WPM * 60 + short.GAP * (nb + 1) + short._pauses(cfg, nb, secs) + short.TAIL


def test_finished_length_matches_request():
    for secs in (60, 90, 120, 150, 180):
        assert abs(spoken(CFG, secs) - secs) < 3, secs


def test_jokes_are_set_aside():
    nb, total, words, wmax = short.plan_length(CFG, 120, WPM)
    assert total - words == short.JOKE_WORDS * nb
    assert words < 200 and wmax < 240          # the Nov 6 run wrote 335 words, then grew to 515
    assert words / nb >= 30


def test_pauses_capped_at_15_percent():
    for secs in (60, 120, 180):
        nb = short.plan_length(CFG, secs, WPM)[0]
        assert short._pauses(CFG, nb, secs) <= 0.15 * secs + 0.01


def test_no_music_no_pauses():
    cfg = dict(CFG, music_on=False)
    assert short._pauses(cfg, 6, 120) == 0
    assert short.plan_length(cfg, 120, WPM)[1] > short.plan_length(CFG, 120, WPM)[1]
