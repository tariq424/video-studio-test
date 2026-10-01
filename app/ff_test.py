import imageio_ffmpeg, subprocess, time, json, sys
exe = imageio_ffmpeg.get_ffmpeg_exe(); print("FFMPEG", exe)
v = subprocess.run([exe, "-version"], capture_output=True, text=True).stdout.splitlines()[0]; print(v)
f = subprocess.run([exe, "-hide_banner", "-filters"], capture_output=True, text=True).stdout
print("HAS_ASS", any(l.split()[1:2] == ["ass"] for l in f.splitlines() if l.strip()))
