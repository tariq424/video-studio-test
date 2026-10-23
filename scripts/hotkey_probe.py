"""Press a hotkey (default Ctrl+Alt+W) and record what opens: the new foreground window's title, process, exe and full command
line, plus a screenshot. Windows only; changes nothing. Report: F:\\videos_test\\smoke\\hotkey_probe.json and .png
    app\\env\\Scripts\\python.exe scripts\\hotkey_probe.py"""
import ctypes
import json
import subprocess
import time
from ctypes import wintypes
from pathlib import Path

OUT = Path(r"F:\videos_test\smoke")
u32 = ctypes.windll.user32
VK = {"ctrl": 0x11, "alt": 0x12, "w": 0x57}


def press(keys):
    for k in keys: u32.keybd_event(VK[k], 0, 0, 0); time.sleep(0.03)
    for k in reversed(keys): u32.keybd_event(VK[k], 0, 2, 0); time.sleep(0.03)


def windows():
    out = []
    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _):
        if u32.IsWindowVisible(h):
            n = u32.GetWindowTextLengthW(h)
            if n:
                b = ctypes.create_unicode_buffer(n + 1); u32.GetWindowTextW(h, b, n + 1)
                pid = wintypes.DWORD(); u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
                out.append({"hwnd": int(h), "title": b.value, "pid": pid.value})
        return True
    u32.EnumWindows(cb, 0)
    return out


def proc(pid):
    ps = (f"$p = Get-CimInstance Win32_Process -Filter 'ProcessId={pid}'; "
          "[pscustomobject]@{name=$p.Name; exe=$p.ExecutablePath; cmd=$p.CommandLine; parent=$p.ParentProcessId} | ConvertTo-Json")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=30)
    try: return json.loads(r.stdout)
    except Exception: return {"raw": r.stdout[:500], "err": r.stderr[:300]}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    before = {w["hwnd"] for w in windows()}
    press(["ctrl", "alt", "w"])
    time.sleep(4)
    fg = u32.GetForegroundWindow()
    after = windows()
    new = [w for w in after if w["hwnd"] not in before]
    cands = new or [w for w in after if w["hwnd"] == fg]
    res = {"foreground": next((w for w in after if w["hwnd"] == fg), None), "new_windows": new, "details": []}
    for w in cands[:5]:
        d = dict(w, process=proc(w["pid"]))
        par = (d["process"] or {}).get("parent")
        if par: d["parent_process"] = proc(par)
        res["details"].append(d)
    try:
        from PIL import ImageGrab
        ImageGrab.grab().save(OUT / "hotkey_probe.png")
    except Exception as e: res["screenshot_error"] = str(e)
    (OUT / "hotkey_probe.json").write_text(json.dumps(res, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
