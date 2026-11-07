"""YouTube video analysis through Gemini (owner, 2026-11-06): Gemini can watch a YouTube link, so for a YouTube job it is asked
(nothing is generated, only read) for
  1. a summary with timestamps,
  2. the "court of public opinion" from the comments: an estimated split between the sides, the most-liked comments quoted
     word for word with handle and likes, and the main themes,
  3. a short blog-style commentary.
The answers are saved as <job>/src/gemini_analysis.md; writer.make_notes() appends that file to the source notes so the explainer
and the Short can quote the comments and use the verdict. Uses the signed-in Gemini profile (imagegen.profile_dir "gemini").
analyze() never raises (cancel aside) and never hangs: every answer has a time limit, a human check / usage limit stops it."""
import re, time
from pathlib import Path

ASK_SUMMARY = ("Watch this YouTube video: {url}\n\nGive a factual summary in 8 to 12 bullet points, each with the timestamp "
               "(mm:ss) of the moment it describes. Name the speakers as the video names them. Facts only, no opinion.")
ASK_COMMENTS = ("Now read the comments on that video and report the court of public opinion:\n"
                "1. VERDICT: the sides or positions viewers take, each with an estimated share of comments in percent, and in one line "
                "how you estimated it (how many comments you read).\n"
                "2. TOP COMMENTS: the 5 most-liked comments, quoted word for word, each with the author's handle and like count.\n"
                "3. THEMES: the 3 to 5 main themes of the reaction.\n"
                "If you cannot see the comments, say exactly that and do not invent any.")
ASK_COMMENTARY = ("Write a blog-style commentary of about 150 words on the video and on how viewers reacted: sharp but fair, and "
                  "clearly separate what was said in the video from the audience's opinion.")
NO_COMMENTS = re.compile(r"(can(no|')t (see|access|read|view)|unable to (see|access|read|view)|do(es)? not have access|"
                         r"no access to)[^.]{0,60}comments", re.I)


def is_youtube(url):
    return bool(re.search(r"(youtube\.com/(watch|shorts|live)|youtu\.be/)", str(url or ""), re.I))


def analyze(cfg, url, srcdir, log, stop=lambda: False):
    """-> path of src/gemini_analysis.md, or None (logged). Cached: an existing analysis is reused."""
    out = Path(srcdir) / "gemini_analysis.md"
    if out.is_file() and len(out.read_text(encoding="utf-8").split()) > 80: return out
    if not cfg.get("yt_gemini_on", True) or not is_youtube(url): return None
    from . import imagegen
    timeout = int(cfg.get("yt_gemini_timeout", 300))
    t0 = time.time()
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            context, page = imagegen._launch(pw, cfg, "gemini")
            try:
                page.goto(cfg.get("gemini_url", "https://gemini.google.com/app"), wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(4000)
                answers = []
                for step, ask in (("summary", ASK_SUMMARY.format(url=url)), ("comments", ASK_COMMENTS), ("commentary", ASK_COMMENTARY)):
                    if stop(): raise RuntimeError("cancelled")
                    imagegen._check(page, step)
                    before = len(imagegen._responses(page))
                    imagegen._send(page, imagegen._box(page), ask)
                    answers.append(imagegen._wait_answer(page, before, timeout, step))
                    log(f"  Gemini {step}: {len(answers[-1].split())} words")
            finally:
                context.close()
    except Exception as e:
        if str(e) == "cancelled": raise
        why = getattr(e, "why", None) or str(e).splitlines()[0][:200]
        log(f"  YouTube analysis by Gemini skipped ({why}); the script uses the transcript only"); return None
    summary, comments, commentary = (answers + ["", "", ""])[:3]
    if len(summary.split()) < 30 or re.search(r"can(no|')t (directly )?(access|stream|watch|view)|unable to (access|watch|view)|"
                                               r"paste a transcript|encountered an error", summary, re.I):   # Gemini declined to watch it
        log("  YouTube analysis by Gemini: no usable summary; not used"); return None
    saw = bool(comments.strip()) and not NO_COMMENTS.search(comments)
    parts = [
        "# Viewer reaction and commentary (Gemini watched the video" + (" and read its comments)" if saw else "; it could NOT see the comments)"),
        f"Source: {url} (analysed {time.strftime('%Y-%m-%d %H:%M')}).",
        "How to use: the summary is a cross-check for the transcript (the transcript wins on any conflict). " +
        ("Quote 1 to 3 of the top comments word for word with the handle (\"one viewer, @handle, wrote ...\"), give the verdict as "
         "\"by Gemini's estimate of the comments\", and use the commentary's angle for colour, never as fact." if saw else
         "Do not mention comments or a public verdict: none were read."),
        "## Summary\n" + summary.strip()]
    if saw: parts.append("## Court of public opinion (from the comments)\n" + comments.strip())
    parts.append("## Commentary angle\n" + commentary.strip())
    out.write_text("\n\n".join(parts) + "\n", encoding="utf-8")
    log(f"  YouTube analysis by Gemini saved ({time.time() - t0:.0f}s; comments {'read' if saw else 'not visible'})")
    return out


def extra_notes(srcdir):
    """Text appended to the script's source notes (empty when there is no analysis)."""
    p = Path(srcdir) / "gemini_analysis.md" if srcdir else None
    return ("\n\n" + p.read_text(encoding="utf-8")) if p and p.is_file() else ""
