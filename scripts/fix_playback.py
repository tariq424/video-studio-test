"""Re-encode videos that won't play on phones/browsers (4:4:4 H.264) into standard 4:2:0, written next to the original as <name>_play.mp4.
Usage: python scripts/fix_playback.py <file-or-folder> [...]   (originals are kept)"""
import sys, json, subprocess, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "app"))
from studio import media
def pix(p):
    r = subprocess.run([media._bin("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=pix_fmt", "-of", "json", str(p)],
                       capture_output=True, text=True)
    try: return json.loads(r.stdout)["streams"][0]["pix_fmt"]
    except Exception: return "?"
files = []
for a in sys.argv[1:]:
    p = pathlib.Path(a)
    files += sorted(p.glob("*.mp4")) if p.is_dir() else [p]
for f in files:
    if f.stem.endswith("_play"): continue
    pf = pix(f)
    if pf == "yuv420p": print("ok      ", f.name, flush=True); continue
    out = f.with_name(f.stem + "_play.mp4")
    print(f"fixing  {f.name} ({pf}) -> {out.name}", flush=True)
    media.ff("-i", f, "-map", "0", "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p", "-profile:v", "high",
             "-movflags", "+faststart", "-c:a", "copy", out, timeout=7200)
    print("done    ", out.name, flush=True)
print("all done", flush=True)
