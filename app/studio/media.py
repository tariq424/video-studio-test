"""ffmpeg helpers + presenter mouth-motion score."""
import subprocess, os, re, json
import numpy as np
from . import config
def _bin(n):
    if n == "ffmpeg":   # newer ffmpeg 7.1 (the WanGP-bundled build hangs on some filter graphs)
        try:
            import imageio_ffmpeg; return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception: pass
    d = config.load()["ffmpeg_dir"]; p = os.path.join(d, n + (".exe" if os.name == "nt" else ""))
    return p if os.path.exists(p) else n
def ff(*a, check=True, timeout=900, cwd=None):
    cmd = [_bin("ffmpeg"), "-v", "error", "-y", "-nostdin", *map(str, a)]
    for attempt in range(2):   # a stuck ffmpeg is killed and retried once
        try: return subprocess.run(cmd, check=check, capture_output=True, text=True, timeout=timeout, cwd=cwd)
        except subprocess.TimeoutExpired:
            if attempt == 1: raise RuntimeError("ffmpeg timed out twice: " + " ".join(cmd[-3:]))
def dur(p, tries=4):
    import time
    for i in range(tries):   # a just-written file can be briefly unreadable
        o = subprocess.run([_bin("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)], capture_output=True, text=True).stdout.strip()
        try: return float(o)
        except ValueError: time.sleep(3)
    raise RuntimeError(f"can't read duration of {p}")
def ok(p, mind=0.5):
    try: return os.path.exists(p) and dur(p) >= mind
    except Exception: return False
def silences(wav, noise="-35dB", d=0.25):
    e = subprocess.run([_bin("ffmpeg"), "-hide_banner", "-i", str(wav), "-af", f"silencedetect=n={noise}:d={d}", "-f", "null", "-"], capture_output=True, text=True).stderr
    st = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", e)]; en = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", e)]
    return list(zip(st, en))
def mouth_score(video):
    W, H = 832, 448
    raw = subprocess.run([_bin("ffmpeg"), "-v", "error", "-i", str(video), "-vf", f"scale={W}:{H},format=gray", "-f", "rawvideo", "-"], capture_output=True).stdout
    v = np.frombuffer(raw, np.uint8).reshape(-1, H, W).astype(np.float32)
    if len(v) < 3: return 0.0
    m = v[:, int(H * .50):int(H * .66), int(W * .40):int(W * .60)]
    return float(np.abs(np.diff(m, axis=0)).mean())
def frames_strip(video, out, n=3):
    d = dur(video); ts = [d * (i + 1) / (n + 1) for i in range(n)]
    parts = []
    for i, t in enumerate(ts):
        p = f"{out}.{i}.jpg"; ff("-ss", f"{t:.2f}", "-i", video, "-frames:v", 1, "-vf", "scale=640:-2", p); parts.append(p)
    args = sum([["-i", p] for p in parts], [])
    ff(*args, "-filter_complex", "".join(f"[{i}]" for i in range(n)) + f"hstack=inputs={n}", out)
    for p in parts: os.remove(p)
