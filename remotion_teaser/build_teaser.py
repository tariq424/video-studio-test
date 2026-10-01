"""Build public/teaser.json + public/voice.wav from the PC narration (voice/b*.wav + timings.json)."""
import json, re, subprocess, sys
from pathlib import Path

SRC = Path(sys.argv[1])            # folder with voice/ and timings.json
PUB = Path(__file__).parent / "public"
GAP, TAIL = 0.35, 2.2
tm = json.loads((SRC / "timings.json").read_text())

def at(bid, word, nth=0, default=0.3):
    ws = tm[bid]["words"]; n = 0
    for w, a, b in ws:
        if re.sub(r"[^a-z0-9]", "", w.lower()) == word.lower():
            if n == nth: return max(0.0, a - 0.15)
            n += 1
    return default

img = lambda s, fr=0.0: {"src": f"media/{s}", "type": "video" if s.endswith(".mp4") else "image", "from": fr, **({"fit": "frame"} if s.endswith(".mp4") else {})}

st = lambda n, fr=0.0: {"src": f"media/stock/{n}.mp4", "type": "video", "from": fr}   # real portrait stock (Pexels), full-frame
SCENES = {
 "b0": dict(bgs=[st("b0_4"), st("b0_10", 5.6)], graphics=[]),
 "b1": dict(bgs=[st("b1_8"), img("servers_l.mp4", 5.5), img("s0_6.jpg", 10.8)], graphics=[]),
 "b2": dict(bgs=[st("b2_1"), st("b2_5", 5.5), img("brain_l.mp4", 10.6)], graphics=[]),
 "b3": dict(bgs=[st("b3_0"), st("b3_10", 7.4)], graphics=[]),
 "b4": dict(bgs=[st("b4_9"), st("b4_3", 5.8)], graphics=[]),
 "b5": dict(bgs=[st("b5_4"), st("b5_6", 6.5)], graphics=[]),
 "b6": dict(bgs=[st("b6_7"), st("b6_3", 4.6)], graphics=[]),
 "b7": dict(bgs=[st("b7_0"), img("sunrise_l.mp4", 6.4), st("b7_6", 11.0)], graphics=[]),
 "b8": dict(bgs=[st("b8_4")], graphics=[]),
}
SCENES["b0"]["graphics"] = [(0.3, {"kind": "hook", "lines": ["IS AI ABOUT TO", "MAKE THE WORLD", "BETTER?"], "accent": 2})]
SCENES["b1"]["graphics"] = [(0.3, {"kind": "quote", "text": "Nothing will ever be able to police AI except other AI.", "who": "Dave Blundin"})]
# graphics that depend on word timings
SCENES["b2"]["graphics"] = [
  (0.3, {"kind": "quote", "text": "Language models are already a weak form of mind uploading.", "who": "Alex Wissner-Gross"}),
  (at("b2", "research"), {"kind": "compare", "badge": "≈", "note": "Research at Meta, using GPT-2",
     "left": {"icon": "🧠", "head": "Brain scans", "body": "People processing language"},
     "right": {"icon": "🤖", "head": "GPT-2", "body": "The model's inner patterns"}})]
SCENES["b3"]["graphics"] = [
  (0.3, {"kind": "stat", "value": 5, "suffix": "×", "label": "more productive", "sub": "…so why isn't your pay 5× higher?"}),
  (at("b3", "his"), {"kind": "compare", "badge": "→", "note": "Dave Blundin",
     "left": {"icon": "🧾", "head": "Payroll", "body": "Gets a little"},
     "right": {"icon": "💰", "head": "Owners", "body": "Get the AI gains"}})]
SCENES["b4"]["graphics"] = [
  (0.3, {"kind": "stat", "value": 100, "prefix": "~", "suffix": "%", "label": "odds of abundance", "sub": "— Salim Ismail"}),
  (at("b4", "catch"), {"kind": "icons", "title": "The catch: rebuild ~50 institutions", "items": [
     {"icon": "🎓", "label": "Education"}, {"icon": "💵", "label": "Money"}, {"icon": "⚖️", "label": "Law"}, {"icon": "🏥", "label": "Health"}]})]
SCENES["b5"]["graphics"] = [
  (0.3, {"kind": "compare", "badge": "vs", "note": "A security chief's warning",
     "left": {"icon": "🧑‍💻", "head": "$50,000", "body": "Human pen testers"},
     "right": {"icon": "🤖", "head": "10 minutes", "body": "Open model on a desk"}}),
  (at("b5", "his", 2, 7.0), {"kind": "hook", "lines": ["HOW DO YOU", "WARN THE BOARD?"], "accent": 1})]
SCENES["b6"]["graphics"] = [
  (0.3, {"kind": "timeline", "title": "Alex's narrow window", "steps": [
     {"when": "Now", "label": "AI steers humans"}, {"when": "≤ 10 yrs", "label": "Window closes"}, {"when": "Then", "label": "Merge?"}]})]
SCENES["b7"]["graphics"] = [
  (0.3, {"kind": "quote", "text": "The real danger isn't AI taking over. It's humans using AI.", "who": "Peter Diamandis"}),
  (at("b7", "get"), {"kind": "stat", "value": 99.9, "decimals": 1, "suffix": "%", "label": "optimistic", "sub": "if we get through the next few years"})]
SCENES["b8"]["graphics"] = [
  (0.2, {"kind": "cta", "thumb": "media/s3_5.jpg", "title": "AI's Wild Next Decade: Safety, Abundance & the Race to Scale", "line": "Watch it — linked below"})]

beats, t, parts = [], 0.0, []
ids = sorted(tm, key=lambda k: int(k[1:]))
for i, bid in enumerate(ids):
    d = tm[bid]["dur"] + (TAIL if i == len(ids) - 1 else GAP)
    sc = SCENES[bid]
    beats.append({"id": bid, "start": round(t, 3), "dur": round(d, 3), "words": tm[bid]["words"], "bgs": sc["bgs"],
                  "graphics": [{"at": round(a, 3), "g": g} for a, g in sorted(sc["graphics"], key=lambda x: x[0])]})
    parts.append((SRC / "voice" / f"{bid}.wav", d))
    t += d
# one narration track: each beat's audio padded to its slot
flt = "".join(f"[{i}:a]apad,atrim=duration={d:.3f}[a{i}];" for i, (_, d) in enumerate(parts)) + "".join(f"[a{i}]" for i in range(len(parts))) + f"concat=n={len(parts)}:v=0:a=1,loudnorm=I=-14:TP=-1.5[out]"
cmd = ["ffmpeg", "-v", "error", "-y"] + sum([["-i", str(p)] for p, _ in parts], []) + ["-filter_complex", flt, "-map", "[out]", "-ar", "48000", str(PUB / "voice.wav")]
subprocess.run(cmd, check=True)
json.dump({"audio": "voice.wav", "total": round(t, 3), "tag": "MOONSHOTS AMA #293 · CONDENSED", "beats": beats}, open(PUB / "teaser.json", "w"), indent=1, ensure_ascii=False)
print("total", round(t, 1), "s;", len(beats), "beats")
