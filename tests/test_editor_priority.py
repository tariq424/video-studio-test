import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
for p in (str(APP), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from studio import editor_session
from studio.pipeline import _StudioQueue


@pytest.fixture
def res_env(tmp_path, monkeypatch):
    monkeypatch.setattr(editor_session, "_settings", lambda: {})
    monkeypatch.setattr(editor_session, "IDLE_LIMIT", 0.05)
    monkeypatch.setenv("GPU_RESERVATION_FILE", str(tmp_path / "reservation.json"))
    monkeypatch.setenv("GPU_LOCK_FILE", str(tmp_path / "gpu.lock"))

    p = editor_session.reservation_path()
    if p.exists():
        p.unlink()

    yield tmp_path

    p.unlink(missing_ok=True)


class FakeStudio:
    def __init__(self, prios):
        self.prios = prios

    def _prio(self, jid):
        return self.prios[jid]


def test_studio_queue_priority_order_and_fifo():
    prios = {
        "editor-first": 0,
        "newsroom-first": 1,
        "hand-first": 2,
        "newsroom-second": 1,
        "editor-second": 0,
        "hand-second": 2,
    }
    q = _StudioQueue(FakeStudio(prios))

    for jid in ["hand-first", "newsroom-first", "editor-first", "editor-second", "hand-second", "newsroom-second"]:
        q.put(jid)

    expected = [
        "editor-first",
        "editor-second",
        "newsroom-first",
        "newsroom-second",
        "hand-first",
        "hand-second",
    ]
    assert [q.get() for _ in range(6)] == expected


def test_editor_session_acquire_and_second_jid_waits(res_env):
    rv1 = editor_session.acquire("job1", pid=os.getpid(), port=42022, sid="sid-1")
    assert rv1["ok"] is True

    rv2 = editor_session.acquire("job2", pid=os.getpid(), port=42022, sid="sid-2")
    assert rv2["ok"] is False
    assert rv2["waiting"] is True
    assert rv2["holder_jid"] == "job1"


def test_idle_release_only_when_no_active_applies(res_env):
    assert editor_session.acquire("job1", pid=os.getpid(), port=42022).get("ok")
    time.sleep(0.08)
    assert editor_session.active() is None

    assert editor_session.acquire("job2", pid=os.getpid(), port=42022).get("ok")
    editor_session.apply_started("job2")
    time.sleep(0.08)
    assert editor_session.active() is not None

    editor_session.apply_finished("job2")
    time.sleep(0.08)
    assert editor_session.active() is None


def test_pid_alive_false_for_dead_pid(res_env):
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait(timeout=5)
    assert editor_session._pid_alive(p.pid) is False


def test_looking_at_a_job_reserves_nothing_an_edit_does(res_env, monkeypatch):
    """Owner, 2026-11-08: reviewing a finished job never holds up the pipeline; only a real edit takes the editor."""
    import contextlib, tempfile, threading
    from pathlib import Path
    from studio import config, edit, gpu_lock
    tmp = Path(tempfile.mkdtemp())
    monkeypatch.setattr(config, "load", lambda: {"jobs_dir": str(tmp / "jobs")})
    monkeypatch.setattr(threading.Thread, "start", lambda self: None)
    import server
    monkeypatch.setattr(server.studio, "job", lambda jid: type("J", (), {"dir": tmp, "log": staticmethod(lambda m: None)})())
    monkeypatch.setattr(edit, "open_beat", lambda *a, **k: {"beats": {}})
    monkeypatch.setattr(edit, "kind", lambda d: "short")
    monkeypatch.setattr(edit, "preview", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(gpu_lock, "holder", lambda desc="": contextlib.nullcontext())
    c = server.app.test_client()
    r = c.post("/api/jobs/jobA/edit/open/b01", json={"sid": "s1"})
    assert r.status_code == 200 and r.get_json()["editor"]["ok"] and editor_session.active() is None
    assert c.post("/api/jobs/jobA/edit/preview/b01", json={"sid": "s1"}).status_code == 200
    assert editor_session.active()["jid"] == "jobA"
    r = c.post("/api/jobs/jobB/edit/preview/b01", json={"sid": "s2"})
    assert r.status_code == 409 and "editor in use (jobA)" in r.get_json()["error"]
