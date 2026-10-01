# Video Studio — Workflow Handoff

This guide lets any AI assistant (ChatGPT, etc.) or a human continue this project. Paste or upload this file at the start of a new chat.

**The latest copy is always in the repo at `F:\code\video-studio\WORKFLOW_HANDOFF.md`.** A Google Doc copy ("Video Studio — Workflow Handoff", https://docs.google.com/document/d/1Lq8OdLu6XxxhxbXI9G_R5Q4URhVOq4TkKe4balVO1sU) may lag behind it.

Video Studio is a fork of Explainer Studio (`F:\code\explainer-studio`, github `tariq424/explainer-studio`). That repo is frozen; new work happens here.

- **Code:** `F:\code\video-studio`, a private GitHub repo at `tariq424/video-studio`. The copy on F: is the working copy; GitHub is kept in sync with it.
- **Outputs:** `F:\videos\video_studio\jobs\<job id>\`. A job's videos are in its `output\` folder.
- **UI:** `http://127.0.0.1:42006`. Start it from Pinokio → **Video Studio** → Start (launcher scripts in `C:\pinokio\api\video-studio`, with copies in `pinokio/` in the repo).

## Ground rules (owner: Tariq)
- **Everything on F:.** Videos go in `F:\videos`. C: is for system files only; Ollama's model store on C: is the one accepted exception.
- **Never print, paste or type API keys.**
  - LLM keys live in Windows Credential Manager under the service name `ExplainerStudio`, shared with the old app. Enter them only in the app's Settings page.
  - The Pexels and Pixabay keys are in the project's `.env`, which git ignores. Scripts read them at runtime; never display them.
- **No deletions** without explicit approval. Rename old versions instead (for example `_v2.mp4`).
- **No footage from YouTube or podcasts.** Use only free stock (Pexels, Pixabay, NASA), our own AI clips and stills, and our own graphics. We summarize the source's ideas and credit the source: in the closing line, on the end card and in the description.
- **Communication:** direct and terse, with honest assessments.
- **Review scripts before showing them.** Fix names, facts and length yourself, using the transcript as the reference, and only ask the owner about what can't be fixed automatically.

## Inputs
1. **YouTube link.** Captions are used if available, otherwise local faster-whisper transcription. A transcript can also be pasted.
2. **Uploaded file:**
   - audio (`.mp3 .m4a .wav ...`), for example a NotebookLM Audio Overview, transcribed locally with whisper;
   - documents (`.txt .md .pdf .docx`).
3. **Pasted text,** such as NotebookLM notes or a briefing doc.

Inputs 2 and 3 take an optional title and credit. Code: `app/studio/sources.py`.

## Outputs ("Make")
- **Long explainer:** 1080p, 3–20 min, made by the original pipeline (`writer.py`, `render.py`, `captions.py`, `assemble.py`), using WanGP stills and motion.
- **Short:** vertical 1080×1920, default 2:45. YouTube's limit is 3:00, so the code caps it at 2:56 and speeds up the narration slightly if it runs over.
- **Both:** the Short's end card then points to the full breakdown ("linked below").

## Pipeline stages (`app/studio/pipeline.py`)
Full order: `transcript → script (long) → short_script → review → short_stock → short_voice → short_render → charts → voice → captions → broll → presenter → motion → stills → assemble`.

**Long-video B-roll** (`broll` stage, `footage.long_broll`). Every AI still or motion visual first tries real landscape stock footage:
1. The script AI turns each image prompt into search phrases.
2. Clips are found and checked with the same search, ranking and checking as for Shorts.
3. The clip is saved in `broll/clips/` and recorded as `v["stock"]`.

Only visuals with no good match are rendered on the GPU by WanGP. In assembly a stock clip is slowed down up to 1.4x, then holds its last frame, to fill its slot. Turn this off with `long_broll: false` in `settings.json`.

Stages that don't apply to the chosen mode are skipped (`stages_for(mode)`). Rendering stages retry automatically, 3 times, 60 s apart.

### Short pipeline (`app/studio/short.py`): almost no GPU
1. **short_script.**
   - Notes come from `writer.make_notes`, cached in `src/notes.txt` so the long and short scripts share them.
   - One LLM call writes 7–12 beats. Each beat has narration (30–48 words), 1–2 animated graphics and 2 Pexels search phrases.
   - Graphic types: hook, quote, stat, compare, icons, timeline. A beat's second graphic appears when its `at` word is spoken.
   - `writer.fact_check` checks the narration and graphics against the transcript.
   - The end-card beat is added automatically.
   - The plan is saved in `short/plan.json`.
2. **review.** The owner approves in the UI ("Edit Short script" is available). Before that, the AI should do its own once-over:
   - total length about 400–430 words for 2:45;
   - hook in plain words;
   - one idea per beat;
   - real stats only (not version numbers);
   - names spelled correctly.
3. **short_stock.** Uses the shared module `app/studio/footage.py`, which long videos use too.
   - **Sources:**
     - Pexels, portrait; it prefers the sharper 1440×2560 or 2160 files.
     - Pixabay: portrait, or 4K landscape centre-cropped to vertical with no upscaling.
     - NASA Image & Video Library, only when a beat mentions space or rockets. NASA clips are landscape and use the frame layout.
   - **Keys:** `PEXELS_API_KEY` and `PIXABAY_API_KEY` in the project `.env`; NASA needs none. Check them at `http://127.0.0.1:42006/api/test_footage?q=...&orient=portrait|landscape`.
   - **Selection:**
     1. The script AI ranks candidates by meaning from each library's own description (Pexels page title, Pixabay tags, NASA title). This uses no GPU.
     2. The vision model checks only the top-ranked clips for overlaid text or brand logos, scene cuts, darkness or blur. It does not judge relevance; it was too literal at that in tests.
     3. If nothing passes, Shorts fall back to the library's own top results.
   - **Cutting:** only the needed seconds are cut straight from the source URL at CRF 14, with no full download.
   - **Top-up:** in the Short build, beats with too little footage are topped up from other beats' clips, and each clip gets screen time in proportion to its length.
   - **Files:**
     - `short/stock/footage.json`: search cache, rankings and picks, used to resume a job.
     - `short/stock/pick.json`: the clips used.
     - `clips/` and `sheets/`: the clips, and the 4-frame preview sheets for checking picks by eye.
   - Removing a beat from `footage.json` → `picked` makes it re-pick on Resume.
4. **short_voice.** WanGP TTS (`qwen3_tts_base`, cloned narrator voice) per beat; word timings from faster-whisper, saved in `short/timings.json`.
5. **short_render.**
   - Builds `short/public/teaser.json`, `voice.wav` (loudness -14 LUFS) and the media folder.
   - Runs `npx remotion render src/Root.tsx Teaser` in `remotion/` with `--public-dir` set to the job's `short/public`.
   - Writes `output/<title>_short.mp4` (Remotion JPEG quality 95, CRF 16, gentle 0–4% zoom for sharpness).
   - Writes `output/youtube_short_description.txt`: "Summarized from: [source]" plus its link, and "Space footage courtesy of NASA" if NASA clips were used. Stock libraries need no credit. If the mode is Both, paste the long video's link into its placeholder.
   - The closing line says "That was a short summary of [source]". No footage from the source is ever used, only its ideas, which are credited.

### Remotion template (`remotion/`)
React/TypeScript, Remotion 4.0.531. `npm install` and the Chrome headless shell are installed by Pinokio Install.
- `Root.tsx`: loads `teaser.json` from the public dir.
- `Teaser.tsx`: timeline, progress bar and top tag. Graphics stay at most 4.6 s so the footage shows.
- `Background.tsx`: stock clips are cover-fit with a slow zoom at 0.85× speed; landscape clips use `fit:"frame"`; stills scroll.
- `Captions.tsx`: karaoke captions, up to 6 words, 46 px, at y=1390. The space between words must stay **inside** the span.
- `Graphics.tsx`: the graphic types plus the CTA end card (optional thumbnail and badge).

## What runs where (and what it costs)
Making a video from the app uses **no Claude resources**.
| Step | Runs on | Cost |
|---|---|---|
| Transcript (YouTube captions, or Whisper for audio files) | PC CPU/GPU | free |
| Script writing, fact-check, footage ranking | **DeepSeek API** (`deepseek-v4-pro`) | a few cents per video |
| Stock-clip checking | PC GPU (Ollama `qwen2.5vl:7b`) | free |
| Footage | Pexels, Pixabay, NASA | free |
| Narration (cloned voice) | PC GPU (WanGP `qwen3_tts_base`) | free |
| Short render | PC CPU (Remotion) | free |
| Long-video AI stills and clips, only where no stock fits | PC GPU (WanGP) | free |

Claude is used only if "Claude" is picked as the Script AI (that needs an Anthropic API key, which isn't set up), or when you ask an AI assistant in chat to review or change things.

**Typical Short timings (Oct 2026, after the speed-ups):** about 18 minutes of machine time, plus your script review. Before the speed-ups it was about 25.
- Script and fact-check: about 1 min.
- Footage and narration together: about 8 min. They run side by side, and narration batches about 115 words per voice call. Each WanGP call has about 32 s of fixed overhead, so fewer, longer calls are faster.
- Render: about 8.5 min on the CPU. Raising concurrency from 75% to 100% didn't help.

## Reviewing a script before approving it
This is the human or AI step the app can't do for itself:
- **Length.** About 400–410 words for a Short. The narrator speaks at about 142 words per minute, and Shorts must stay under 3:00.
- **Hook.** It's in plain words.
- **One idea per beat.**
- **Stat graphics.** They must show real quantities: no version numbers, no "1.0x", and no ranges as a single number (use a text card instead).
- **Quotes.** Only words that were actually said go in quote cards; a paraphrase becomes a headline card.
- **Names.** Spelled correctly; captions often mishear them, for example "Dennis" for Demis Hassabis.
- **Fact-check questions.** Answer any the app flags at the top of the review page.

## Hardware and tools
- **PC:** Windows, RTX 5060 Ti 16 GB. Pinokio at `http://localhost:42000`; a script runs when you open `http://localhost:42000/api/video-studio/<script>.js`.
- **WanGP:** MCP at `http://127.0.0.1:42004/mcp/`. Models:
  - `flux2_klein_9b` for stills;
  - `ltx2_distilled` for motion, **landscape 1280×720 only**, because vertical output burns in gibberish text;
  - `qwen3_tts_base` for the voice.
- **Ollama:** `qwen3:14b` (optional script AI) and `qwen2.5vl:7b` (clip vetting).
- **Script AI:** DeepSeek by default (`deepseek-v4-pro`, Anthropic-compatible endpoint, thinking disabled). DeepSeek can't see images, so image QA for long videos is off.
- **ffmpeg:** imageio-ffmpeg 7.1. On Windows, image overlays must be full-length looped inputs starting at t=0, or ffmpeg hangs.

## Syncing code
- The F: copy is the working copy.
- When an AI edits the code, it commits and pushes to `tariq424/video-studio`.
- **Verify every copy to F: with a checksum** (`md5sum`). A file-copy tool once silently wrote an older version.

## Test results (Oct 1 2026)
- **Test 1:** job `F:\videos\video_studio\jobs\20261001_083509`, Moonshots AMA #293, Short only, 2:56. Made before the multi-source footage. Clips were picked by hand and the script was trimmed by hand.
- **Test 2 (current pipeline):** job `F:\videos\video_studio\jobs\20261001_150550`. Output: `output\AI_Mind_Uploads_Abundance_Risk_Moonshots_AMA_in_3_Min_short.mp4`, 2:55.
  - Includes the multi-source footage, sharper rendering, "That was a short summary of..." ending, "SUMMARIZED FROM" end card and hard cuts between beats.
  - `_v1.mp4` in the same folder is the render from before the hard-cut and borrowing fixes.
  - The script was edited before approval: trimmed from 451 to 410 words, and two misleading stat graphics fixed.
  - One weak beat (the arms race) got generic field footage.
- **Fixed after test 2, so new jobs only:**
  - Vision checks no longer reject clips on a too-literal reading of the search phrase.
  - Scripts are sized to the narrator's measured pace (`voice_wpm` 142).
- **Test 3:** job `F:\videos\video_studio\jobs\20261001_173258`, the Fireship Remotion tutorial (`https://youtu.be/deg8bOoziaE`), Short only, 2:44.
  - First run with batched narration and footage running alongside it: 18 minutes of machine time.
  - The script reviewer caught a quote DeepSeek had invented ("Code is the new camera"). **Always check quote cards against the transcript.**
- **Not yet tested end to end:** long-video B-roll (the `broll` stage).

## Open items
- Run a long video to test the `broll` stage, then check how many AI visuals got replaced and what that did to render time.
- Possible improvements:
  - a "my clips" folder per job, for hero shots made by hand in CapCut (Seedance), used before stock footage;
  - Internet Archive public-domain footage as an option for historical topics;
  - word timings with whisper on the GPU instead of the CPU, to save about 30–60 s;
  - a stronger brand-logo check: a phone advert with a visible "vivo" logo got past the vision model twice.
- Upload the Moonshots long video, and put its link in the Short descriptions.
