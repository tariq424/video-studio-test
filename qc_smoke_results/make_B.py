"""specimen_B = specimen_A with 4 injected 10 s faults (QC smoke test, 2026-10-26). Run with the Video Studio python."""
import subprocess, sys, time
sys.path.insert(0, r"F:\code\video-studio-test\app")
from studio import media
D = r"F:\code\patches\qc_smoke"
FC = ("[0:v]split=4[base][r][u][bl];"
      "[r]transpose=1,scale=-2:1920,crop=1080:1920,setsar=1[rv];"
      "[u]hflip,vflip[uv];"
      "[bl]boxblur=20:2[bv];"
      "[base][rv]overlay=enable='between(t,10,20)'[o1];"
      "[o1][uv]overlay=enable='between(t,30,40)'[o2];"
      "[o2]drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill:enable='between(t,50,60)'[o3];"
      "[o3][bv]overlay=enable='between(t,70,80)'[o4]")
t = time.time()
r = subprocess.run([media._bin("ffmpeg"), "-v", "error", "-y", "-nostdin", "-i", D + r"\specimen_A.mp4", "-filter_complex", FC,
                    "-map", "[o4]", "-map", "0:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                    "-profile:v", "high", "-c:a", "copy", "-movflags", "+faststart", D + r"\specimen_B.mp4"], capture_output=True, text=True)
print("ffmpeg", media._bin("ffmpeg"), "exit", r.returncode, "secs", round(time.time() - t), r.stderr[-1500:])
# full decode check (video + audio, end to end)
r2 = subprocess.run([media._bin("ffmpeg"), "-v", "error", "-nostdin", "-i", D + r"\specimen_B.mp4", "-f", "null", "-"], capture_output=True, text=True)
print("decode check exit", r2.returncode, "errors:", r2.stderr[-1500:] or "none")
print("DONE")
