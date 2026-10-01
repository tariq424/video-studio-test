"""Non-YouTube sources: an uploaded audio file (e.g. a NotebookLM Audio Overview) or text (pasted, or a .txt/.md/.pdf/.docx upload).
Every source ends up as src/transcript.txt + src/meta.json, so the rest of the pipeline doesn't care where it came from."""
import json, re, time
from pathlib import Path

AUDIO = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac", ".opus", ".webm", ".mp4"}
DOCS = {".txt", ".md", ".pdf", ".docx"}

def kind_of(name):
    ext = Path(name).suffix.lower()
    return "audio" if ext in AUDIO else "doc" if ext in DOCS else None

def transcribe(audio, log):
    from faster_whisper import WhisperModel
    def run(m):
        segs, info = m.transcribe(str(audio), vad_filter=True)
        out, t0 = [], time.time()
        for s in segs:
            out.append(s.text.strip())
            if time.time() - t0 > 60: log(f"  transcribed to {int(s.end // 60)} min..."); t0 = time.time()
        return re.sub(r"\s+", " ", " ".join(out)).strip()
    try:
        return run(WhisperModel("large-v3-turbo", device="cuda", compute_type="float16"))
    except Exception as e:
        log(f"  GPU transcription unavailable ({str(e)[:80]}); using CPU (slower)")
        return run(WhisperModel("small", device="cpu", compute_type="int8"))

def doc_text(path):
    ext = path.suffix.lower()
    if ext in (".txt", ".md"): return path.read_text(encoding="utf-8", errors="ignore")
    if ext == ".pdf":
        from pypdf import PdfReader
        return "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)
    if ext == ".docx":
        import docx
        return "\n".join(p.text for p in docx.Document(str(path)).paragraphs)
    raise RuntimeError(f"Unsupported document type: {ext}")

def load(src, upload, title, credit, log):
    """src = job/src folder; upload = saved file path (or None, then src/pasted.txt is used)."""
    if upload and kind_of(upload.name) == "audio":
        log(f"Transcribing {upload.name} on this PC...")
        text = transcribe(upload, log); kind = "audio"
    elif upload:
        text = doc_text(upload); kind = "document"
    else:
        text = (src / "pasted.txt").read_text(encoding="utf-8"); kind = "text"
    text = re.sub(r"[ \t]+", " ", text).strip()
    if len(text.split()) < 150: raise RuntimeError(f"The {kind} has only {len(text.split())} words; need at least 150 to make a video.")
    name = upload.stem.replace("_", " ") if upload else "Pasted notes"
    meta = {"title": title or name, "channel": credit or ("NotebookLM" if "notebooklm" in (name + (credit or "")).lower() else ""),
            "uploader": credit or "", "webpage_url": "", "description": "", "source_kind": kind}
    (src / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    (src / "transcript.txt").write_text(text, encoding="utf-8")
    log(f"Source: {kind}, {len(text.split())} words, titled '{meta['title']}'")
    return meta, text
