"""Render chart / card specs to 1920x1080 PNGs (dark documentary style)."""
import textwrap
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

BG, FG, MUT = "#0d1117", "#eef1f5", "#8b949e"
PAL = ["#4ea1ff", "#f5a524", "#ff5c5c", "#3ecf8e", "#b58cff", "#ff8ad8"]
plt.rcParams.update({"font.family": "DejaVu Sans", "text.color": FG, "axes.labelcolor": FG, "xtick.color": MUT,
                     "ytick.color": MUT, "axes.edgecolor": "#30363d", "axes.facecolor": BG, "figure.facecolor": BG, "font.size": 22})

def _fig(): return plt.figure(figsize=(19.2, 10.8), dpi=100)
def _wrap(t, w): return "\n".join(textwrap.wrap(str(t or ""), w))
def _title(f, t, sub=None):
    f.text(0.06, 0.88, _wrap(t, 60), fontsize=44, weight="bold", va="top")
    if sub: f.text(0.06, 0.78, _wrap(sub, 95), fontsize=24, color=MUT, va="top")
def _note(f, t):
    if t: f.text(0.06, 0.04, _wrap(t, 150), fontsize=17, color=MUT, style="italic")
def _ax(f):
    a = f.add_axes((0.08, 0.14, 0.86, 0.58))
    for s in ("top", "right"): a.spines[s].set_visible(False)
    a.grid(axis="y", color="#21262d"); a.set_axisbelow(True); return a
def _box(f, x, y, w, h, col):
    f.patches.append(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.01,rounding_size=0.02",
                                    transform=f.transFigure, fc="#161b22", ec=col, lw=4))

def _fmt(v, unit):
    s = f"{v:,.2f}".rstrip("0").rstrip(".") if isinstance(v, (int, float)) else str(v)
    return f"{unit}{s}" if unit in ("$", "£", "€") else f"{s}{unit or ''}"

def render(spec, out):
    k = spec.get("kind", "cards"); f = _fig()
    try:
        if k == "title":
            t = str(spec.get("title") or ""); fs = 72 if len(t) <= 34 else 62 if len(t) <= 60 else 54
            f.text(0.5, 0.70, _wrap(t, 26 if fs >= 62 else 32), ha="center", va="center", fontsize=fs, weight="bold", linespacing=1.1)
            f.text(0.5, 0.50, _wrap(spec.get("subtitle"), 80), ha="center", va="center", fontsize=30, color=PAL[1])
            f.text(0.5, 0.40, _wrap(spec.get("credit"), 100), ha="center", fontsize=22, color=MUT)
        elif k == "end":
            f.text(0.5, 0.60, _wrap(spec.get("text"), 40), ha="center", va="center", fontsize=58, weight="bold", linespacing=1.3)
            f.text(0.5, 0.30, _wrap(spec.get("credit"), 110), ha="center", fontsize=22, color=MUT)
        elif k == "stat":
            f.text(0.5, 0.58, str(spec.get("big", "")), ha="center", va="center", fontsize=150, weight="bold", color=PAL[1])
            f.text(0.5, 0.33, _wrap(spec.get("caption"), 60), ha="center", va="center", fontsize=38)
            _note(f, spec.get("note"))
        elif k == "quote":
            f.text(0.5, 0.58, "“" + _wrap(spec.get("text"), 44) + "”", ha="center", va="center", fontsize=50, weight="bold", linespacing=1.3)
            f.text(0.5, 0.25, "— " + str(spec.get("who", "")), ha="center", fontsize=30, color=PAL[1])
        elif k == "bar":
            _title(f, spec.get("title"), spec.get("subtitle")); a = _ax(f)
            labels = [_wrap(l, 18) for l in spec.get("labels", [])]; vals = [float(v) for v in spec.get("values", [])]
            n = min(len(labels), len(vals)); labels, vals = labels[:n], vals[:n]
            a.bar(range(n), vals, color=[PAL[i % len(PAL)] for i in range(n)], width=0.55)
            a.set_xticks(range(n)); a.set_xticklabels(labels, fontsize=22)
            top = max(vals) if vals else 1; a.set_ylim(0, top * 1.22 if top > 0 else 1)
            for i, v in enumerate(vals): a.text(i, v + top * 0.03, _fmt(v, spec.get("unit", "")), ha="center", fontsize=30, weight="bold")
            _note(f, spec.get("note"))
        elif k == "line":
            _title(f, spec.get("title"), spec.get("subtitle")); a = _ax(f)
            x, y = spec.get("x", []), [float(v) for v in spec.get("y", [])]
            n = min(len(x), len(y)); a.plot(list(range(n)), y[:n], color=PAL[1], lw=6, marker="o", ms=12)
            a.set_xticks(range(n)); a.set_xticklabels([str(v) for v in x[:n]])
            a.set_xlabel(spec.get("xlabel", "")); a.set_ylabel(spec.get("ylabel", ""))
            _note(f, spec.get("note"))
        elif k == "compare":
            _title(f, spec.get("title"))
            for x, side, col in [(0.06, spec.get("left", {}), PAL[2]), (0.52, spec.get("right", {}), PAL[3])]:
                _box(f, x, 0.16, 0.42, 0.54, col)
                f.text(x + 0.21, 0.66, _wrap(side.get("head"), 24), ha="center", va="top", fontsize=34, weight="bold", color=col)
                f.text(x + 0.21, 0.40, _wrap(side.get("body"), 34), ha="center", va="center", fontsize=28, linespacing=1.4)
        elif k == "timeline":
            _title(f, spec.get("title")); ev = spec.get("events", [])[:6]; n = max(len(ev), 1)
            a = f.add_axes((0.06, 0.2, 0.88, 0.45)); a.axis("off"); a.set_xlim(-0.5, n - 0.5); a.set_ylim(-1, 1)
            a.plot([-0.4, n - 0.6], [0, 0], color="#30363d", lw=6)
            for i, e in enumerate(ev):
                c = PAL[i % len(PAL)]; a.plot(i, 0, "o", ms=26, color=c)
                a.text(i, 0.22 if i % 2 == 0 else -0.28, str(e.get("when", "")), ha="center", va="bottom" if i % 2 == 0 else "top", fontsize=30, weight="bold", color=c)
                a.text(i, 0.55 if i % 2 == 0 else -0.62, _wrap(e.get("label"), 20), ha="center", va="bottom" if i % 2 == 0 else "top", fontsize=22)
        else:  # cards
            _title(f, spec.get("title")); it = spec.get("items", [])[:4]; n = max(len(it), 1)
            w = 0.88 / n - 0.02
            for i, c in enumerate(it):
                x = 0.06 + i * (w + 0.02); col = PAL[i % len(PAL)]
                _box(f, x, 0.16, w, 0.54, col)
                f.text(x + w / 2, 0.62, _wrap(c.get("head"), int(60 * w)), ha="center", va="top", fontsize=32, weight="bold", color=col)
                f.text(x + w / 2, 0.38, _wrap(c.get("body"), int(80 * w)), ha="center", va="center", fontsize=25, linespacing=1.4)
        f.savefig(out, dpi=100, facecolor=BG)
    finally:
        plt.close(f)
