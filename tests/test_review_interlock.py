"""Nov 7: the beat chat was refused with "Another job is using the GPU" although the GPU interlock (691935f) gives the
editor priority. A running job no longer refuses a beat action; the WanGP step waits on gpu_lock instead."""
import sys, threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from studio import review  # noqa: E402


class FakeStudio:
    current = "20261107_070754"   # a job is running
    def job(self, jid):
        class J: dir = Path("."); log = staticmethod(lambda *a: None)
        return J()


def test_running_job_does_not_refuse_beat_actions(monkeypatch):
    ran = threading.Event()
    monkeypatch.setattr(review, "_busy", lambda *a: None)
    monkeypatch.setattr(review, "refine", lambda *a: ran.set())
    monkeypatch.setattr(review, "expand", lambda *a: ran.set())
    for kind in ("refine", "expand"):
        ran.clear()
        assert review.start(FakeStudio(), "j", "b5", kind, {"text": "x"}, ws=Path(".")) == ""
        assert ran.wait(10)
        for _ in range(100):
            if review._gpu.acquire(blocking=False): review._gpu.release(); break
            threading.Event().wait(0.05)
