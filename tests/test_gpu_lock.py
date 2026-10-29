import json
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

from studio import gpu_lock


def _reset_lock():
    gpu_lock._fh = None
    gpu_lock._owner = None
    gpu_lock._depth = 0
    gpu_lock._desc = ""
    gpu_lock._since = 0.0


@pytest.fixture
def lock_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GPU_LOCK_FILE", str(tmp_path / "gpu.lock"))
    monkeypatch.setenv("GPU_RESERVATION_FILE", str(tmp_path / "gpu.reservation.json"))
    _reset_lock()
    yield tmp_path
    if gpu_lock.held_by_me():
        gpu_lock.release()
    _reset_lock()


def test_acquire_release(lock_env):
    assert gpu_lock.acquire("edit", timeout=1)
    assert gpu_lock.held_by_me()

    st = gpu_lock.status()
    assert st["held"] is True
    assert st["desc"] == "edit"

    assert gpu_lock.release()
    assert gpu_lock.status()["held"] is False


def test_second_process_cannot_acquire_while_held(lock_env):
    ready = lock_env / "ready.txt"

    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(APP), str(ROOT)]
        + [p for p in sys.path if p not in (str(APP), str(ROOT))]
    )
    env["GPU_LOCK_FILE"] = str(lock_env / "gpu.lock")

    holder_code = f"""
import time
from studio import gpu_lock

gpu_lock.acquire("holder", timeout=2)
open({str(ready)!r}, "w").write("ok")
time.sleep(1.2)
gpu_lock.release()
"""
    holder = subprocess.Popen([sys.executable, "-c", holder_code], env=env)

    try:
        for _ in range(80):
            if ready.exists():
                break
            time.sleep(0.05)
        else:
            holder.kill()
            raise AssertionError("holder did not become ready")

        probe = subprocess.run(
            [sys.executable, "-c", "from studio import gpu_lock; print(gpu_lock.acquire('probe', timeout=0.3))"],
            env=env,
            capture_output=True,
            text=True,
        )
        assert probe.returncode == 0
        assert probe.stdout.strip() == "False"
    finally:
        holder.wait(timeout=3)

    assert gpu_lock.acquire("after-holder-exit", timeout=1)
    gpu_lock.release()


def test_nested_acquire_release_keeps_lock_until_outer_release(lock_env):
    assert gpu_lock.acquire("outer")
    assert gpu_lock.acquire("inner")

    assert gpu_lock.release()
    assert gpu_lock.status()["held"] is True

    assert gpu_lock.release()
    assert gpu_lock.status()["held"] is False


def test_status_does_not_trust_stale_metadata(lock_env):
    lock_file = lock_env / "gpu.lock"
    lock_file.write_bytes(b"\0")

    stale = {
        "pid": os.getpid(),
        "desc": "stale-metadata",
        "t": time.time(),
    }
    gpu_lock.meta_path().write_text(json.dumps(stale), encoding="utf-8")

    st = gpu_lock.status()
    assert st["held"] is False
