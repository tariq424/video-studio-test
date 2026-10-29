"""Machine-wide GPU barrier for Video Studio (design: DeepSeek round 1-2 via ai-exchange, fixes by Claude).

One GPU user at a time across every process (live 42021, test copies, QC scripts). Byte-range lock on a file
(msvcrt on Windows, fcntl elsewhere): the OS frees it when the holder process exits, so a crash never leaves a stale
lock. Metadata (holder pid/desc/since) is display-only; the OS lock is the truth.
Claude fixes over the DeepSeek draft: Windows LK_LOCK gives up after ~10 s, so acquire() polls LK_NBLCK; re-entrant
per thread with a count (nested holders no longer deadlock or release early); force-release never deletes the file.
CLI (for the WanGP watchdog):  python -m studio.gpu_lock status | force-release
"""
import argparse, contextlib, json, os, threading, time
from pathlib import Path

if os.name == "nt":
    import msvcrt
else:
    import fcntl

_rl = threading.RLock()          # in-process: one owning thread at a time, re-entrant
_fh = None; _owner = None; _depth = 0; _desc = ""; _since = 0.0


def lock_path():
    p = os.environ.get("GPU_LOCK_FILE")
    if not p:
        try:
            from . import config
            p = config.load().get("gpu_lock_file")
        except Exception:
            p = None
    return Path(p or r"F:\code\gpu.lock")


def meta_path():
    p = lock_path(); return p.with_name(p.name + ".json")


def _write_meta(d):
    p = meta_path(); p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(d, indent=1), encoding="utf-8")
    for _ in range(40):
        try: os.replace(tmp, p); return
        except PermissionError: time.sleep(0.05)


def _read_meta():
    try: return json.loads(meta_path().read_text(encoding="utf-8")) or {}
    except Exception: return {}


def _open():
    p = lock_path(); p.parent.mkdir(parents=True, exist_ok=True)
    fh = open(p, "a+b")
    fh.seek(0, os.SEEK_END)
    if fh.tell() == 0: fh.write(b"\0"); fh.flush()
    return fh


def _try_lock(fh):
    fh.seek(0)
    try:
        if os.name == "nt": msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else: fcntl.lockf(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB, 1, 0)
        return True
    except OSError:
        return False


def _unlock(fh):
    fh.seek(0)
    try:
        if os.name == "nt": msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else: fcntl.lockf(fh.fileno(), fcntl.LOCK_UN, 1, 0)
    except OSError:
        pass


def acquire(desc="gpu", timeout=None, poll=0.5, on_wait=None):
    """Take the GPU. Blocks (polling) until free, or returns False after `timeout` seconds.
    on_wait(holder_meta) is called once when we first have to wait (for 'Waiting: GPU busy' messages)."""
    global _fh, _owner, _depth, _desc, _since
    t0 = time.time()
    if not _rl.acquire(timeout=-1 if timeout is None else timeout): return False
    try:
        if _owner == threading.get_ident():
            _depth += 1; return True
        fh = _open(); told = False
        while not _try_lock(fh):
            if not told and on_wait:
                try: on_wait(_read_meta())
                except Exception: pass
                told = True
            if timeout is not None and time.time() - t0 >= timeout:
                fh.close(); _rl.release(); return False
            time.sleep(poll)
        _fh, _owner, _depth, _desc, _since = fh, threading.get_ident(), 1, desc, time.time()
        _write_meta({"pid": os.getpid(), "desc": desc, "t": _since})
        return True
    except Exception:
        _rl.release(); raise


def release():
    """Release one level; the OS lock is dropped when the outermost holder releases. Only the owner thread may."""
    global _fh, _owner, _depth, _desc, _since
    if _owner != threading.get_ident(): return False
    _depth -= 1
    if _depth <= 0:
        fh = _fh
        _fh, _owner, _depth, _desc, _since = None, None, 0, "", 0.0
        try:
            _write_meta({})
            _unlock(fh)
        finally:
            fh.close()
    _rl.release()
    return True


def held_by_me():
    return _owner == threading.get_ident()


def status():
    """{held, pid, desc, age, file}. Never trusts the metadata alone: probes the OS lock."""
    p = lock_path()
    if _fh is not None:
        return {"held": True, "pid": os.getpid(), "desc": _desc, "age": round(time.time() - _since, 1), "file": str(p), "mine": True}
    if not p.exists(): return {"held": False, "file": str(p)}
    fh = open(p, "a+b")
    try:
        if _try_lock(fh):
            _unlock(fh); return {"held": False, "file": str(p)}
    finally:
        fh.close()
    m = _read_meta()
    return {"held": True, "pid": m.get("pid", "?"), "desc": m.get("desc", "unknown"),
            "age": round(time.time() - float(m.get("t", time.time())), 1), "file": str(p)}


def force_release(reason="manual force-release"):
    """Manual escape hatch for a hung-but-alive holder. An OS byte lock belongs to its process and cannot be taken
    from outside, so this only marks the metadata; the real lock frees when that process is stopped. Never deletes
    the lock file (deleting it would let two holders lock two different files)."""
    st = status()
    if st.get("held") and not st.get("mine"):
        _write_meta(dict(_read_meta(), forced_release_requested=time.time(), reason=reason))
        st["note"] = f"held by pid {st.get('pid')}; stop that process to free the GPU"
    return st


@contextlib.contextmanager
def holder(desc="gpu", on_wait=None):
    acquire(desc=desc, on_wait=on_wait)
    try: yield
    finally: release()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Video Studio GPU barrier")
    ap.add_argument("cmd", choices=["status", "force-release"])
    a = ap.parse_args(argv)
    print(json.dumps(status() if a.cmd == "status" else force_release(), indent=1))


if __name__ == "__main__":
    main()
