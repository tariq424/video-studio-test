"""Read text baked into an image (a source screenshot / frame), e.g. the AI prompt shown in a tutorial.

Engines, best first:
1. pytesseract, when the Tesseract program is installed (setting tesseract_cmd, PATH, or C:\\Program Files\\Tesseract-OCR).
2. RapidOCR (ONNX, pip only, runs on the CPU). It drops the spaces between English words, so its lines are re-spaced
   with wordninja when that package is present.
Nothing installed -> ("", "none"): the caller simply has no OCR prompt and the ladder carries on.
"""
import os
import re
import shutil
from pathlib import Path

_rapid = {"engine": None}


def _tesseract_cmd(cfg):
    for c in [cfg.get("tesseract_cmd"), shutil.which("tesseract"),
              r"C:\Program Files\Tesseract-OCR\tesseract.exe", r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"]:
        if c and Path(c).is_file():
            return str(c)
    return None


def _respace(line):
    """'identicaltotheuploadedimage.Hewearsadark,tailored' -> 'identical to the uploaded image. He wears a dark, tailored'."""
    line = re.sub(r"([.,;:!?])(?=[A-Za-z])", r"\1 ", line)
    line = re.sub(r"(?<=[a-z])(?=\d)", " ", line)
    try:
        import wordninja
    except ImportError:
        return line
    def split(m):
        w = m.group(0)
        parts = wordninja.split(w)
        return " ".join(parts) if len(parts) > 1 else w
    return re.sub(r"[A-Za-z]{7,}", split, line)


def _lines_tesseract(cmd, path):
    import pytesseract
    from PIL import Image
    pytesseract.pytesseract.tesseract_cmd = cmd
    with Image.open(path) as im:
        data = pytesseract.image_to_data(im.convert("RGB"), output_type=pytesseract.Output.DICT)
    rows = {}
    for i, word in enumerate(data["text"]):
        if not str(word).strip() or float(data["conf"][i]) < 40:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        r = rows.setdefault(key, {"y": data["top"][i], "x": data["left"][i], "words": []})
        r["words"].append(str(word).strip())
    out = sorted(rows.values(), key=lambda r: (r["y"], r["x"]))
    return [(r["y"], " ".join(r["words"])) for r in out]


def _lines_rapid(path):
    if _rapid["engine"] is None:
        from rapidocr_onnxruntime import RapidOCR
        _rapid["engine"] = RapidOCR()
    res, _ = _rapid["engine"](str(path))
    lines = []
    for box, text, score in res or []:
        if float(score) < 0.6 or not str(text).strip():
            continue
        lines.append((float(box[0][1]), _respace(str(text).strip())))
    return sorted(lines)


def read(path, cfg=None, log=print):
    """-> (text, engine). Lines in reading order, joined with newlines. Never raises."""
    cfg = cfg or {}
    if not cfg.get("ocr_on", True):
        return "", "off"
    cmd = _tesseract_cmd(cfg)
    engines = (["tesseract"] if cmd else []) + ["rapidocr"]
    if cfg.get("ocr_engine") in engines: engines = [cfg["ocr_engine"]]
    for engine in engines:
        try:
            lines = _lines_tesseract(cmd, path) if engine == "tesseract" else _lines_rapid(path)
            return "\n".join(t for _, t in lines), engine
        except ImportError:
            continue
        except Exception as e:
            log(f"  OCR ({engine}) failed on {Path(path).name}: {str(e)[:150]}")
    return "", "none"


def prompt_from(text, min_words=12):
    """The paragraph that looks like a written prompt: the longest run of consecutive long lines (UI labels, file names and
    single words around it are dropped). -> text, or "" when there is no such paragraph."""
    best, run = [], []
    for line in str(text or "").splitlines():
        line = re.sub(r"[»«|•©®™]+", " ", line).strip()
        words = line.split()
        if len(words) >= (2 if run else 5) and sum(c.isalpha() for c in line) > 0.6 * len(line):
            run.append(line.strip())
        else:
            if sum(len(l.split()) for l in run) > sum(len(l.split()) for l in best):
                best = run
            run = []
    if sum(len(l.split()) for l in run) > sum(len(l.split()) for l in best):
        best = run
    out = re.sub(r"\s+", " ", " ".join(best)).strip()
    out = re.sub(r"^(prompt|copy prompt)\s*[:\-]?\s*", "", out, flags=re.I)
    return out[:900] if len(out.split()) >= min_words else ""
