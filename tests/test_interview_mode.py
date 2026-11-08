"""Interview mode (owner, 2026-11-08): your own interview footage where the real conversation leads - a preview of later
moments, background lines, then your questions and the answers in order, commentary where the guest gets specific."""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from studio import config, interview, pipeline  # noqa: E402


def _segs(n, sec=10.0):
    return [{"i": i, "start": i * sec, "end": i * sec + sec - 1.0, "text": f"Sentence {i}.", "words": []} for i in range(n)]


def test_preview_then_title_then_background_then_the_conversation():
    segs = _segs(12)
    tri = {"preview": [[8, 8], [10, 10]], "background": ["Nea Dixon is a Bermudian artist.", "We met at Dockyard."],
           "drop": [[3, 3, "small talk"]], "facts": [{"after": 6, "note": 0, "text": "A fact."}], "chapters": [{"at": 0, "title": "Start"}]}
    its = interview.augment_items(tri, segs)
    assert [x.get("bite") for x in its[:2]] == [[8, 8], [10, 10]] and all(x.get("preview") for x in its[:2])
    assert its[1].get("title_after") and not its[0].get("title_after")   # the title card comes after the last teaser
    assert [x.get("narr") for x in its[2:4]] == tri["background"] and all(x.get("background") for x in its[2:4])
    convo = [i for x in its[4:] if "bite" in x for i in range(x["bite"][0], x["bite"][1] + 1)]
    assert convo == [0, 1, 2, 4, 5, 6, 7, 8, 9, 10, 11]   # the whole conversation in order; teasers are played again in place
    assert any("insert" in x for x in its[4:])


def test_no_preview_keeps_the_old_shape():
    its = interview.augment_items({"chapters": [{"at": 0, "title": "Start"}]}, _segs(4))
    assert "bite" in its[0] and not its[0].get("preview") and not any(x.get("background") for x in its)


class _LLM:
    plan = None
    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def chat_json(self, system, user, max_tokens=0, check=None):
        _LLM.prompt = user
        if check: check(_LLM.plan)
        return _LLM.plan


def test_triage_asks_for_questions_kept_and_checks_the_preview(tmp_path, monkeypatch):
    import studio.llm
    monkeypatch.setattr(studio.llm, "LLM", _LLM)
    segs = _segs(10)
    _LLM.plan = {"chapters": [{"at": 0, "title": "A"}], "preview": [[2, 4]]}   # 29 s: too long for a teaser
    with pytest.raises(ValueError, match="teaser"):
        interview.triage({}, segs, "ctx", [], tmp_path / "a")
    assert "questions in front of the" in _LLM.prompt and "Never drop a question whose answer stays" in _LLM.prompt
    _LLM.plan = {"chapters": [{"at": 0, "title": "A"}], "preview": [[5, 5]], "background": ["Who and where."], "guest": "Nea Dixon"}
    (tmp_path / "b").mkdir()
    assert interview.triage({}, segs, "ctx", [], tmp_path / "b")["guest"] == "Nea Dixon"


def test_no_old_guest_baked_in():
    src = Path(interview.__file__).read_text(encoding="utf-8")
    assert "Thank you, Mr. Clinton" not in src and "Islamic Center of Bermuda\"" not in src and "\"A conversation in Bermuda\"" not in src
    assert "keep his narrative" not in interview.TRIAGE and "man holding the camera" not in interview.TRIAGE


def test_create_interview_job_checks_the_file_and_queues(tmp_path):
    clip = tmp_path / "talk.MOV"; clip.write_bytes(b"x")
    with tempfile.TemporaryDirectory() as temp, patch.object(config, "load", return_value={**config.DEFAULTS, "jobs_dir": temp}), \
            patch("threading.Thread.start"):
        st = pipeline.Studio()
        with pytest.raises(ValueError, match="not found"): st.create_interview(tmp_path / "missing.mov")
        with pytest.raises(ValueError, match="video file"): st.create_interview(__file__)
        jid = st.create_interview(clip, "Nea at Dockyard", ["", str(clip)], "Thank you, Nea")
        s = st.job(jid).state
        assert s["kind"] == "interview" and s["status"] == "queued" and s["interview"]["context"] == "Nea at Dockyard"
        assert s["interview"]["extras"] == [str(clip)] and s["interview"]["thanks"] == "Thank you, Nea"


def test_adopt_links_outputs_and_writes_manifests(tmp_path):
    from studio import interview_edit, media
    out = tmp_path / "work" / "x_short.mp4"; out.parent.mkdir(); out.write_bytes(b"v")
    part = tmp_path / "work" / "p0.mp4"; part.write_bytes(b"p")
    mp = tmp_path / "work" / "x_short_parts.json"
    mp.write_text(json.dumps({"out": str(out), "title": "T", "sources": [], "parts": [{"file": str(part), "m": {"type": "card"}}]}), encoding="utf-8")
    with patch.object(media, "dur", return_value=3.0):
        outs = interview_edit.adopt(tmp_path / "job", {"short": mp, "long": tmp_path / "work" / "missing.json"}, log=lambda m: None)
    assert list(outs) == ["short"] and Path(outs["short"]).read_bytes() == b"v"
    m = json.loads((tmp_path / "job" / "iedit" / "short.json").read_text(encoding="utf-8"))
    assert m["parts"][0]["dur"] == 3.0 and m["parts"][0]["check"] is False


def test_topic_notes_research_what_the_guest_mentions(tmp_path, monkeypatch):
    import studio.llm
    from studio import websearch

    class L(_LLM):
        def chat_json(self, system, user, max_tokens=0, check=None):
            if "SPECIFIC things" in user:
                j = {"topics": [{"seg": 3, "topic": "three passports", "query": "Bermudian status citizenship"},
                                {"seg": 7, "topic": "sailing", "query": "Caribbean sailing"}]}
                if check: check(j)
                return j
            assert "Bermudian status:" in user
            return {"facts": ["Bermudian status is a legal status that gives the right to live and work in Bermuda.", ""]}
    monkeypatch.setattr(studio.llm, "LLM", L)
    monkeypatch.setattr(websearch, "_wikipedia", lambda cfg, q: [f"Bermudian status: about {q}"] if "Bermudian" in q else [])
    monkeypatch.setattr(websearch, "search", lambda cfg, q, log=None: ([], ""))
    res = interview.topic_notes({}, _segs(10), "ctx", tmp_path, log=lambda m: None)
    assert res == [{"fact": "Bermudian status is a legal status that gives the right to live and work in Bermuda.",
                    "source": "https://en.wikipedia.org/wiki/Bermudian_status", "topic": "three passports", "seg": 3, "kind": "topic"}]
    assert "(about what is said at segment 3: three passports)" in interview.note_lines(res + [{"fact": "Dockyard.", "kind": "place"}])
    assert "[1] (place) Dockyard." in interview.note_lines(res + [{"fact": "Dockyard.", "kind": "place"}])


def test_a_fact_on_what_was_said_goes_where_it_was_said(tmp_path, monkeypatch):
    import studio.llm
    monkeypatch.setattr(studio.llm, "LLM", _LLM)
    _LLM.plan = {"chapters": [{"at": 0, "title": "A"}], "facts": [{"after": 1, "note": 0, "text": "Status."}, {"after": 8, "note": 1, "text": "Dockyard."}]}
    notes = [{"fact": "Status.", "seg": 6, "kind": "topic", "topic": "passports"}, {"fact": "Dockyard.", "kind": "place"}]
    j = interview.triage({}, _segs(10), "ctx", notes, tmp_path)
    assert [f["after"] for f in j["facts"]] == [7, 8]   # moved to the answer about it; the place note stays where it was put
    assert "Spell people's and places' names the way the creator's note" in _LLM.prompt


def test_topic_note_source_is_the_snippet_the_fact_came_from(tmp_path, monkeypatch):
    import studio.llm
    from studio import websearch

    class L(_LLM):
        def chat_json(self, system, user, max_tokens=0, check=None):
            if "SPECIFIC things" in user: return {"topics": [{"seg": 2, "topic": "citizenship", "query": "British citizenship Bermuda"}]}
            return {"facts": ["A British Overseas Territories citizen holds a category of British nationality."]}
    monkeypatch.setattr(studio.llm, "LLM", L)
    monkeypatch.setattr(websearch, "_wikipedia", lambda cfg, q: ["Bermuda: an island territory in the Atlantic.",
                                                                 "British Overseas Territories citizen: a category of British nationality."])
    res = interview.topic_notes({}, _segs(5), "ctx", tmp_path, log=lambda m: None)
    assert res[0]["source"] == "https://en.wikipedia.org/wiki/British_Overseas_Territories_citizen"
