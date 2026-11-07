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


def _pick_model(page, want, log):
    """Switch Gemini to a model that can watch videos (Nov 6: the profile sat on "Flash-Lite", which declined YouTube links).
    The picker shows the current model's name (Flash-Lite / Flash / Pro / Argon); the menu lists "3.1 Pro Advanced reasoning" etc."""
    try:
        cur = None
        for name in ("Flash-Lite", "Flash", "Pro", "Argon"):   # the picker button shows the current model's short name
            loc = page.get_by_role("button", name=re.compile(rf"^\s*{name}\s*$"))
            if loc.count(): cur = loc.last; break
        if cur is None: raise RuntimeError("model picker not found")
        if want.lower() in (cur.inner_text(timeout=3000) or "").lower().split(): return
        cur.click(timeout=5000); page.wait_for_timeout(1500)
        page.locator(f"[role=menuitemradio]:has-text('{want}'), [role=menuitem]:has-text('{want}'), button:has-text('{want}')").first.click(timeout=5000)
        page.wait_for_timeout(1500)
        log(f"  Gemini model: {want}")
    except Exception as e:
        log(f"  Gemini model picker not usable ({str(e)[:80]}); asking with the current model")


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
                _pick_model(page, cfg.get("yt_gemini_model", "Pro"), log)
                answers = []
                for step, ask in (("summary", ASK_SUMMARY.format(url=url)), ("commentary", ASK_COMMENTARY)):   # comments: read directly
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
    summary, commentary = _clean(answers[0] if answers else ""), _clean(answers[1] if len(answers) > 1 else "")
    if len(summary.split()) < 30 or re.search(r"can(no|')t (directly )?(access|stream|watch|view)|unable to (access|watch|view)|"
                                               r"paste a transcript|encountered an error", summary, re.I):   # Gemini declined to watch it
        log("  YouTube analysis by Gemini: no usable summary; not used"); return None
    coms = fetch_comments(url, log, int(cfg.get("yt_comments_max", 300)))
    court = verdict(cfg, coms, summary, log) if coms else None
    parts = [
        "# Viewer reaction and commentary (Gemini watched the video" +
        (f"; {court['counted']} top YouTube comments were read directly)" if court else "; no comments could be read)"),
        f"Source: {url} (analysed {time.strftime('%Y-%m-%d %H:%M')}).",
        "How to use: the summary is a cross-check for the transcript (the transcript wins on any conflict). " +
        ("Give the court of public opinion with the counted shares (\"of N top comments, about X% sided with ...\"), quote 1 to 3 of "
         "the top comments word for word with the handle (\"one viewer, @handle, wrote ...\"), and use the commentary's angle for "
         "colour, never as fact." if court else
         "Do not mention comments or a public verdict: none were read. The commentary's claims about viewers are unverified: don't use them."),
        "## Summary\n" + summary]
    if court:
        lines = [f"Counted from the {court['counted']} top comments (each comment assigned to one side by the script AI; shares counted):"]
        lines += [f"- {x['side']}: {x['share']}% ({x['n']} comments)" for x in court["sides"]]
        lines += ["", "Most-liked comments (word for word):"]
        lines += [f"- {c['author']} ({c['likes']:,} likes): \"{c['text']}\"" for c in court["top"]]
        parts.append("## Court of public opinion (from the comments)\n" + "\n".join(lines))
    parts.append("## Commentary angle (Gemini)\n" + commentary)
    out.write_text("\n\n".join(parts) + "\n", encoding="utf-8")
    log(f"  YouTube analysis saved ({time.time() - t0:.0f}s; " + (f"{court['counted']} comments counted)" if court else "no comments)"))
    return out


def _clean(t):
    """Gemini's page text without its UI: the "Gemini said" label and the "To explore ..." follow-up chips at the END
    (only when they come in the last third of the answer, so the text itself is never cut)."""
    t = re.sub(r"^\s*Gemini said\s*", "", str(t or "")).strip()
    m = None
    for m in re.finditer(r"\n\s*(?:To explore (?:this|these|more|further)|Would you like)[^\n]*", t): pass
    if m and m.start() > len(t) * 0.66: t = t[:m.start()]
    return t.strip()


FETCH = ("import json,sys,yt_dlp\n"
         "o={'skip_download':True,'quiet':True,'no_warnings':True,'getcomments':True,"
         "'extractor_args':{'youtube':{'max_comments':[sys.argv[2],'all','0','0'],'comment_sort':['top']}}}\n"
         "with yt_dlp.YoutubeDL(o) as y: i=y.extract_info(sys.argv[1],download=False)\n"
         "print(json.dumps([{'author':c.get('author'),'text':c.get('text'),'likes':c.get('like_count') or 0} "
         "for c in (i.get('comments') or []) if c.get('parent')=='root']))")


def fetch_comments(url, log, n=300, timeout=240):
    """The video's top comments, read directly with yt-dlp in its own process (time-limited):
    [{"author", "text", "likes"}], most-liked first. [] when they can't be read (comments off, blocked ...)."""
    import json, subprocess, sys
    try:
        p = subprocess.run([sys.executable, "-c", FETCH, url, str(n)], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
        last = (p.stdout or "").strip().splitlines()
        cs = json.loads(last[-1]) if last else []
    except Exception as e:
        log(f"  comments not readable ({str(e)[:100]})"); return []
    cs = [dict(c, text=re.sub(r"\s+", " ", str(c.get("text") or "")).strip()) for c in cs if c.get("text")]
    cs.sort(key=lambda c: -int(c.get("likes") or 0))
    log(f"  {len(cs)} top-level comments read")
    return cs


VERDICT = """These are the top comments on a YouTube video. What the video is about:
{summary}

Comments, numbered:
{comments}

1. Name 2 to 4 OPPOSING sides a viewer can take on what the video is about: one per main participant or position, phrased as
   who the viewer sides with (e.g. "sides with Youssef", "sides with Weiss", "blames the host"). The sides must exclude each other:
   never two sides that mean the same thing (praising one person and attacking their opponent is the SAME side). Include a side
   for each main participant even if few comments take it.
2. Assign EVERY comment number to exactly one side, or to "neither" (jokes without a position, off-topic, unclear).
Reply with ONLY JSON: {{"sides": ["side 1", "side 2"], "labels": {{"0": "side 1", "1": "neither"}}}}"""


def verdict(cfg, coms, summary, log, k=200):
    """Court of public opinion: the script AI sorts each comment into a side; the shares are COUNTED here, not estimated.
    -> {"sides": [{"side", "share", "n"}], "counted", "top": [5 most-liked]} or None."""
    from .llm import LLM
    use = coms[:k]
    numbered = "\n".join(f"{i}. {c['text'][:220]}" for i, c in enumerate(use))
    c = dict(cfg)
    if c.get("script_provider") == "claude" and not c.get("anthropic_api_key"): c["script_provider"] = "deepseek" if c.get("deepseek_api_key") else "local"
    try:
        with LLM(c, log, lambda: False) as llm:
            j = llm.chat_json("You sort YouTube comments by the position they take. Reply with JSON only.",
                              VERDICT.format(summary=summary[:2500], comments=numbered), max_tokens=8000)
    except Exception as e:
        log(f"  comment verdict: script AI unavailable ({str(e)[:100]})"); j = {}
    labels = {int(i): str(v) for i, v in (j.get("labels") or {}).items() if str(i).isdigit() and int(i) < len(use)}
    sides = [str(x) for x in (j.get("sides") or [])][:4]
    counted = [v for v in labels.values() if v in sides]
    top = [{"author": x.get("author") or "a viewer", "text": x["text"][:300], "likes": int(x.get("likes") or 0)} for x in coms[:5]]
    if len(counted) < 10:
        return {"sides": [], "counted": len(use), "top": top} if top else None
    res = [{"side": sd, "n": counted.count(sd), "share": round(100 * counted.count(sd) / len(counted))} for sd in sides]
    res.sort(key=lambda x: -x["n"])
    log("  comment verdict: " + ", ".join(f"{x['side']} {x['share']}%" for x in res) + f" (of {len(counted)} taking a side)")
    return {"sides": res, "counted": len(use), "top": top}


def extra_notes(srcdir):
    """Text appended to the script's source notes: Gemini's viewer-reaction analysis (YouTube jobs) and the place colour from
    your own footage's GPS (uploads). Empty when there is neither."""
    out = ""
    for name in ("gemini_analysis.md", "place_colour.md"):
        p = Path(srcdir) / name if srcdir else None
        if p and p.is_file(): out += "\n\n" + p.read_text(encoding="utf-8")
    return out
