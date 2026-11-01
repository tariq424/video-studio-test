"""Z002: the narration-fit gate loosens wording-level rejections only.

A first match=no now gets a second, independent subject check: same subject
(wording/naming/attribute quibble) -> accepted; different subject (or an
unusable second verdict) -> still rejected. Match=yes verdicts are untouched
(no second call), and unavailable/malformed first verdicts keep their behavior.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from studio import imagegen


def _vision_responses(responses):
    """_local_fit_vision mock returning the given responses in order."""
    calls = []

    def fake(cfg, image, prompt):
        calls.append(prompt)
        return responses[len(calls) - 1] if isinstance(responses, list) else responses

    return fake, calls


def _run(monkeypatch, responses, vo="narration about the Bermuda Arts Centre's glass-doored studios"):
    fake, calls = _vision_responses(responses)
    monkeypatch.setattr(imagegen, "_local_fit_vision", fake)
    verdict, reason = imagegen._fit_check_now({}, "img.jpg", {"vo": vo}, lambda m: None)
    return verdict, reason, calls


def test_wording_level_rejection_is_accepted(monkeypatch):
    verdict, reason, calls = _run(monkeypatch, [
        json.dumps({"match": "no", "reason": "glass doors vs glass-doored studios"}),
        json.dumps({"same_subject": "yes", "reason": "same venue"}),
    ])
    assert verdict == "accepted"
    assert "wording-level" in reason
    assert len(calls) == 2                      # the second (subject) call happened


def test_true_subject_mismatch_still_rejects(monkeypatch):
    verdict, reason, calls = _run(monkeypatch, [
        json.dumps({"match": "no", "reason": "mosque, not an arts venue"}),
        json.dumps({"same_subject": "no", "reason": "place of worship"}),
    ])
    assert verdict == "rejected"
    assert "subject mismatch" in reason
    assert len(calls) == 2


def test_match_yes_is_untouched_and_makes_one_call(monkeypatch):
    verdict, reason, calls = _run(monkeypatch, json.dumps({"match": "yes", "reason": "fits"}))
    assert verdict == "accepted"
    assert len(calls) == 1                      # no subject check on a first-stage match


def test_malformed_first_verdict_still_unavailable(monkeypatch):
    verdict, _, calls = _run(monkeypatch, "not json at all")
    assert verdict == "unavailable"
    assert len(calls) == 1                      # no second call on malformed


def test_subject_check_failure_fails_closed(monkeypatch):
    def boom(cfg, image, prompt):
        if "same_subject" in prompt:
            raise RuntimeError("ollama down")
        return json.dumps({"match": "no", "reason": "wording"})
    monkeypatch.setattr(imagegen, "_local_fit_vision", boom)
    verdict, reason = imagegen._fit_check_now({}, "img.jpg", {"vo": "x"}, lambda m: None)
    assert verdict == "rejected"                # conservative: keep the first verdict


def test_old_style_second_verdict_without_same_subject_stays_rejected(monkeypatch):
    """Mocks that answer the old schema ({"match": "no"}) must not flip to accepted."""
    verdict, _, _ = _run(monkeypatch, [
        json.dumps({"match": "no", "reason": "r"}),
        json.dumps({"match": "no", "reason": "old schema"}),
    ])
    assert verdict == "rejected"


def test_no_narration_is_unavailable(monkeypatch):
    fake, calls = _vision_responses("x")
    monkeypatch.setattr(imagegen, "_local_fit_vision", fake)
    verdict, reason = imagegen._fit_check_now({}, "img.jpg", {"vo": "  "}, lambda m: None)
    assert verdict == "unavailable"
    assert calls == []
