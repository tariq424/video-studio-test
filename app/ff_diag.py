import sys, json, subprocess, time
sys.path.insert(0, ".")
from pathlib import Path
from studio import assemble, media
J = Path(r"F:\videos\explainer_studio\jobs\20260929_222317")
cap = {}
def fake(*a, **k):
    if "-filter_complex" in a: cap["a"] = a; cap["k"] = k; raise SystemExit
    return media_ff(*a, **k)
media_ff = media.ff; media.ff = fake
plan = json.loads((J / "plan.json").read_text(encoding="utf-8"))
b = J / "build"; out = b / "sec_s0.mp4"
try: assemble.build(J, {"sections": plan["sections"][:1]}, print, use_presenter=False, use_captions=True)
except SystemExit: pass
a = list(map(str, cap["a"])); a[-1] = str(b / "t_full.mp4")
cmd = [media._bin("ffmpeg"), "-y", "-nostdin", "-v", "verbose", "-stats_period", "5", *a]
print("CMDLEN", len(" ".join(cmd)))
t = time.time()
try:
    r = subprocess.run(cmd, cwd=cap["k"].get("cwd"), capture_output=True, text=True, timeout=120)
    print("RC", r.returncode, f"{time.time()-t:.0f}s"); print("\n".join(r.stderr.splitlines()[-25:]))
except subprocess.TimeoutExpired as e:
    err = e.stderr.decode("utf8", "ignore") if isinstance(e.stderr, bytes) else (e.stderr or "")
    print("TIMEOUT"); print("\n".join(err.splitlines()[-40:]))
