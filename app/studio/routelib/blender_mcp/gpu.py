"""GPU discipline for the Blender route: shared lock, free-VRAM gate, Blender start/close.

Load on demand, unload at the end:
  * the GPU lock is Video Studio's own studio/gpu_lock.py (same file, same OS byte lock),
    loaded by path so the POC doesn't import the rest of Video Studio;
  * Blender is started only when needed and closed when the frames are done;
  * the planner model is unloaded by planner.py (keep_alive=0).
"""
import contextlib
import importlib.util
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

MCP_PORT = int(os.environ.get("BLENDER_MCP_PORT", "9876"))
NEED_MB = {"preview": int(os.environ.get("BLENDER_VRAM_PREVIEW_MB", "6000")),
           "final": int(os.environ.get("BLENDER_VRAM_FINAL_MB", "10000"))}
_GPU_LOCK_FILE = Path(__file__).resolve().parents[2] / "app" / "studio" / "gpu_lock.py"


def _load_gpu_lock():
    if not _GPU_LOCK_FILE.is_file():
        return None
    spec = importlib.util.spec_from_file_location("vs_gpu_lock", _GPU_LOCK_FILE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@contextlib.contextmanager
def gpu_lock(desc, log):
    mod = _load_gpu_lock()
    if mod is None:
        log("GPU lock: studio/gpu_lock.py not found next to media-poc - running without the shared lock")
        yield
        return

    def waiting(meta):
        log(f"GPU busy (held by pid {meta.get('pid', '?')}: {meta.get('desc', 'unknown')}) - waiting")
    mod.acquire(desc=desc, on_wait=waiting)
    log(f"GPU lock taken ({mod.lock_path()})")
    try:
        yield
    finally:
        mod.release()
        log("GPU lock released")


def vram():
    """(used_mb, free_mb, total_mb) of the first NVIDIA GPU, or None."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--query-gpu=memory.used,memory.free,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10).stdout.strip().splitlines()[0]
        used, free, total = (int(x.strip()) for x in out.split(","))
        return used, free, total
    except Exception:
        return None


def wait_for_vram(quality, log, max_wait_s=600):
    need = NEED_MB.get(quality, NEED_MB["preview"])
    t0 = time.time()
    told = False
    while True:
        v = vram()
        if v is None:
            log("VRAM: nvidia-smi unavailable - skipping the free-memory check")
            return None
        if v[1] >= need:
            log(f"VRAM: {v[1]} MB free of {v[2]} MB (need {need} MB for {quality})")
            return v
        if not told:
            log(f"VRAM: only {v[1]} MB free, need {need} MB - waiting for the GPU (up to {max_wait_s // 60} min)")
            told = True
        if time.time() - t0 > max_wait_s:
            raise RuntimeError(f"GPU busy: {v[1]} MB free, {need} MB needed for a {quality} render")
        time.sleep(10)


def port_open(port=MCP_PORT, host="127.0.0.1"):
    with socket.socket() as s:
        s.settimeout(0.8)
        return s.connect_ex((host, port)) == 0


def find_blender():
    env = os.environ.get("BLENDER_EXE")
    if env and Path(env).is_file():
        return env
    found = []
    for base in (Path(os.path.expandvars(r"%LOCALAPPDATA%\Programs\Blender Foundation")),
                 Path(r"C:\Program Files\Blender Foundation")):
        if base.is_dir():
            found += list(base.glob("*/blender.exe"))

    def ver(p):
        import re
        m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", str(p.parent.name))
        return tuple(int(x or 0) for x in m.groups()) if m else (0, 0, 0)
    found.sort(key=ver, reverse=True)
    return str(found[0]) if found else (shutil.which("blender") or None)


def start_blender(log, timeout_s=180):
    """Start Blender WITH its window (the MCP add-on cannot serve in background mode) and wait
    for the add-on's auto-started MCP bridge. Returns the Popen."""
    exe = find_blender()
    if not exe:
        raise FileNotFoundError("Blender not installed")
    log(f"Starting Blender: {exe}")
    proc = subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if proc.poll() is not None:
            raise RuntimeError(f"Blender exited early (code {proc.returncode})")
        if port_open():
            time.sleep(1.5)
            log(f"Blender MCP add-on listening on {MCP_PORT} after {time.time() - t0:.0f} s")
            return proc
        time.sleep(1.0)
    close_blender(proc, log)
    raise RuntimeError(f"Blender started but the MCP add-on never opened port {MCP_PORT} "
                       "(enable 'Auto-Start Server' in the MCP panel)")


def close_blender(proc, log, grace_s=5):
    """Close a Blender WE started. MCP's quit_blender is blocked by safe mode, so this happens from
    outside: a polite close first, then a force close. Blender usually still shows its quit prompt
    (unsaved Render Result image), so the force close is the normal path - it loses nothing, because
    the frames are on disk and scene.blend was saved just before."""
    if proc is None or proc.poll() is not None:
        return
    t0 = time.time()
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid)], capture_output=True)
    else:
        proc.terminate()
    try:
        proc.wait(timeout=grace_s)
        log(f"Blender closed ({time.time() - t0:.1f} s)")
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)
        log(f"Blender closed (forced after {grace_s} s; frames and scene.blend already saved)")
    for _ in range(20):  # the port should go away with it
        if not port_open():
            break
        time.sleep(0.5)
