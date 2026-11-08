"""Non-YouTube sources: an uploaded audio file (e.g. a NotebookLM Audio Overview) or text (pasted, or a .txt/.md/.pdf/.docx upload).
Every source ends up as src/transcript.txt + src/meta.json, so the rest of the pipeline doesn't care where it came from."""
import json, re, time
from pathlib import Path

AUDIO = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac", ".opus", ".webm", ".mp4",
         ".mov", ".m4v", ".mkv"}   # video files too: the speech is transcribed and your footage's GPS colours the story (place.py)
DOCS = {".txt", ".md", ".pdf", ".docx"}

def kind_of(name):
    ext = Path(name).suffix.lower()
    return "audio" if ext in AUDIO else "doc" if ext in DOCS else None

VIDEO = {".mov", ".mp4", ".m4v", ".mkv", ".webm"}


def transcribe(audio, log, cues=None):
    """-> the speech as text. cues = a list to fill with {"start", "end", "text"} per segment (the source-clip rung's timestamps)."""
    from faster_whisper import WhisperModel
    def run(m):
        segs, info = m.transcribe(str(audio), vad_filter=True)
        out, t0 = [], time.time()
        if cues is not None: cues.clear()
        for s in segs:
            out.append(s.text.strip())
            if cues is not None and s.text.strip(): cues.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()})
            if time.time() - t0 > 60: log(f"  transcribed to {int(s.end // 60)} min..."); t0 = time.time()
        return re.sub(r"\s+", " ", " ".join(out)).strip()
    try:
        return run(WhisperModel("large-v3-turbo", device="cuda", compute_type="float16"))
    except Exception as e:
        log(f"  GPU transcription unavailable ({str(e)[:80]}); using CPU (slower)")
        return run(WhisperModel("small", device="cpu", compute_type="int8"))

def has_video(path):
    """True when the file has a picture stream (an .mp4 can be audio only)."""
    try:
        import subprocess
        from . import media
        r = subprocess.run([media._bin("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width",
                            "-of", "csv=p=0", str(path)], capture_output=True, text=True, timeout=30)
        return bool(r.stdout.strip().split(",")[0].strip())
    except Exception:
        return False


def own_footage_source(src, upload, cues, log):
    """Your own uploaded video becomes the job's real source (owner, 2026-11-07): src/source_video.mp4 + src/source_cues.json, so
    the source-clip rung shows YOUR footage first, cut where the transcript matches each beat."""
    from . import media
    out = Path(src) / "source_video.mp4"
    try:
        if not out.is_file():
            try: media.ff("-i", upload, "-map", "0:v:0", "-c", "copy", "-movflags", "+faststart", out, timeout=600)   # remux, no re-encode
            except Exception:
                media.ff("-i", upload, "-map", "0:v:0", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", out, timeout=1800)
        (Path(src) / "source_cues.json").write_text(json.dumps(cues, indent=1, ensure_ascii=False), encoding="utf-8")
        log(f"  your footage is the source: {len(cues)} timed line(s); the source-clip rung uses it first")
    except Exception as e:
        out.unlink(missing_ok=True)
        log(f"  your footage could not be prepared as the source ({str(e)[:120]}); pictures come from the ladder")


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
    own = bool(upload and upload.suffix.lower() in VIDEO and has_video(upload))
    if upload and kind_of(upload.name) == "audio":
        log(f"Transcribing {upload.name} on this PC...")
        cues = []
        text = transcribe(upload, log, cues); kind = "video" if own else "audio"
        if own: own_footage_source(src, upload, cues, log)
    elif upload:
        text = doc_text(upload); kind = "document"
    else:
        text = (src / "pasted.txt").read_text(encoding="utf-8"); kind = "text"
    text = re.sub(r"[ \t]+", " ", text).strip()
    if len(text.split()) < 150: raise RuntimeError(f"The {kind} has only {len(text.split())} words; need at least 150 to make a video.")
    name = upload.stem.replace("_", " ") if upload else "Pasted notes"
    meta = {"title": title or name, "channel": credit or ("NotebookLM" if "notebooklm" in (name + (credit or "")).lower() else ""),
            "uploader": credit or "", "webpage_url": "", "description": "", "source_kind": kind}
    if own: meta.update(own_footage=True, channel=credit or "Your footage")
    (src / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    (src / "transcript.txt").write_text(text, encoding="utf-8")
    log(f"Source: {kind}, {len(text.split())} words, titled '{meta['title']}'")
    return meta, text
