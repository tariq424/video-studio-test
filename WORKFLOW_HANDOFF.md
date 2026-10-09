# Video Studio — Workflow Handoff

This guide lets any AI assistant (ChatGPT, etc.) or a human continue this project. Paste or upload this file at the start of a new chat.

**The latest copy is always in the repo at `F:\code\video-studio\WORKFLOW_HANDOFF.md`.** A Google Doc copy ("Video Studio — Workflow Handoff", https://docs.google.com/document/d/1Lq8OdLu6XxxhxbXI9G_R5Q4URhVOq4TkKe4balVO1sU) may lag behind it.

Video Studio is a fork of Explainer Studio (`F:\code\explainer-studio`, github `tariq424/explainer-studio`). That repo is frozen; new work happens here.

- **Code:** `F:\code\video-studio`, a private GitHub repo at `tariq424/video-studio`. The copy on F: is the working copy; GitHub is kept in sync with it.
- **Outputs:** `F:\videos\video_studio\jobs\<job id>\`. A job's videos are in its `output\` folder.
- **UI:** `http://127.0.0.1:42020` (fixed since Oct 4; `start-video-studio.bat` starts it without Pinokio). Start it from Pinokio → **Video Studio** → Start (launcher scripts in `C:\pinokio\api\video-studio`, with copies in `pinokio/` in the repo).

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
Full order: `transcript → script (long) → short_script → review → short_stock → short_voice → short_fallback → short_render → charts → voice → captions → broll → presenter → motion → stills → assemble`.

**Long-video B-roll** (`broll` stage, `footage.long_broll`). Every AI still or motion visual first tries real landscape stock footage:
1. The script AI turns each image prompt into search phrases.
2. Clips are found and checked with the same search, ranking and checking as for Shorts.
3. The clip is saved in `broll/clips/` and recorded as `v["stock"]`.

Only visuals with no good match are rendered on the GPU by WanGP. In assembly a stock clip is slowed down up to 1.4x, then holds its last frame, to fill its slot. Turn this off with `long_broll: false` in `settings.json`.

Locked visuals (see **Subject lock** below) never take a generic clip: if no clip shows the subject, WanGP renders an AI still or motion clip instead. After `write_plan`, `short.verify_quotes` turns any quote card whose words aren't in the transcript into a headline card.

### Story-level coherence (`coherence.py`, Oct 4 2026; replaces per-beat locking below where they differ)
Test of Oct 4 (job 20261004_164620) showed per-beat locks were not enough: only 2 of 11 Short beats were locked, so "passenger jet" and
"wing" beats showed Biman, AnadoluJet and GoAir planes, and the photo-real AI stills invented fake airlines.
- `coherence.entities()`: one LLM call lists the story's identifiable subjects (kind, brand, category words, an "avoid" description,
  colours; named people with role/row). Cached in `<job>/entities.json`, shared by the long video and the Short.
- `coherence.assign()`: any shot whose search phrases or image prompt mention the subject's CATEGORY ("jet", "wing", "SUV") is locked
  to it. Interior shots (cabin, dashboard) are not locked, but every unlocked shot is checked for the forbidden category
  (`AVOID` question in the vision check) and rejected if it shows any such object.
- Locked shots with no confirmed real footage become **3D reconstructions** (`remotion/src/Recon.tsx`, three.js via `@remotion/three`):
  low-poly airliner (in flight / landing on a desert runway / parked with police car), cabin with mannequin passengers and labelled
  seats, cockpit door, SUV on a road, labelled mannequin people, generic object. Coloured with the subject's scheme, labelled
  "RECONSTRUCTION", never a logo or a face. Short: `do_fallback` adds them as backdrops. Long: `long_broll` renders 9 s clips
  (`short.render_recon`, composition `Recon`) and uses them as the shot's footage.
- **Subject-locked shots never search the stock libraries** (Pexels/Pixabay/NASA are for generic scenes). They go to
  `photos.py`: real openly licensed photos of the subject, from **Openverse** first (no key; aggregates Flickr, Commons and more;
  anonymous limit 200 requests/day), then **Wikimedia Commons**. Flickr's own API is deliberately not used (free keys are
  non-commercial; Openverse already indexes Flickr). An Openverse 429 (throttled) or outage is logged and the search goes straight
  to Commons; a throttled empty result is not cached, so a resume retries. No failure in this chain stops the job: with no usable
  photo the shot becomes a 3D reconstruction. Photos under 900 px wide (by metadata or by the downloaded file) are rejected.
  Only CC0, Public Domain, CC BY and CC BY-SA (no NC, ND or GFDL). Each photo is vision-checked (subject's brand in its title/tags or
  visible, no other brand, no watermark). Short: shown whole over a blurred copy with an on-screen credit; long: 9 s slow zoom/pan
  clip with the credit burned in top-right for the whole clip. WanGP image-to-video is deliberately NOT used on these photos
  (garbled liveries; CC BY-SA derivative question). Every photo gets a credit line (title, author, licence, link) in the YouTube description. Each photo is used once per video.
  Order for a locked shot: real photos -> 3D reconstruction (Short: the route map first if the beat has one). Long videos: if the
  reconstruction render fails, a drawn headline card (`photos.headline_clip`); WanGP NEVER draws a subject-locked shot - if even the
  card fails, the broll stage stops with an error rather than fall back to an AI image.
- Photo-real AI stills are now only used for unlocked (generic) beats.
- Oct 4 test (job 20261004_204512) fixes:
  - photo downloads are polite (1.5 s apart) and retried on 429/503 (Retry-After, else 5 s then 15 s); duplicates by title removed;
  - the most specific entity wins ("fighter jet" -> the F-35, not the airliner);
  - locked beats: the real subject photo comes first even if it shows a different moment (the narration carries the action);
    photos are rejected only for wrong brand/livery, wrong model, watermark, not a real photo, or < 900 px - never for action.
    Beats about what happens inside (cockpit, cabin) open on one real photo, then the cabin/cockpit reconstruction;
  - every generic stock clip must FIT the narration (vision question "fits", given the narration): no landmark of another country,
    no unrelated event, no calm/routine scene over an emergency; clothing logos count as brands;
  - Shorts no longer borrow other beats' clips; a beat without enough fitting footage gets fallback visuals instead;
  - the script AI is told to match the beat's mood and place in its search phrases;
  - Remotion is retried (up to 3 times) when headless Chrome is slow to start ("trying to connect to the browser").
- App address is fixed: http://127.0.0.1:42020 (next free port if busy, printed). `start-video-studio.bat` in the repo root runs it
  without Pinokio (`start-video-studio.bat reload` = auto-restart on code changes, which also stops a running render).
- Remotion WebGL: `--gl=angle` on Windows (GPU), `swangle` elsewhere; override with `remotion_gl` in settings.json. Software rendering
  is about 2 frames/s at 1080p, so the GPU matters for long videos.
- The separate `video-studio-coherence` repo (Copilot) was reviewed and not used: its modules were non-working stubs.

### Subject lock and brand rejection (`footage.py`, Oct 2026)
Built after a flydubai Short showed a Qatar Airways wing and a Turkish Airlines jet, and a Mitsubishi Outlander video showed Toyotas and Mercedes.
- **Subject lock.** When a beat or visual is about an identifiable entity (a named airline's aircraft, a car make/model, a named person, a product), the script AI sets `subject: {name, brand}` (Short beats in `SHORT`; long visuals in the `QUERIES` prompt, which also puts the make/model in the search phrases).
- **Reference photo.** `footage.reference()` fetches a photo of the subject from the Wikimedia Commons API (no key; Google has no free image API and scraping it breaks their terms). Cached in `refs/<slug>.jpg`.
- **Strict check.** For locked slots, `verify()` shows the vision model the reference photo next to the clip's frames (`STRICT` prompt). The clip is used only if it shows the same subject; when the subject has a brand, the brand must be visible in the frames or named in the library description. Library top-results fallback and borrowing other beats' clips are off for locked slots.
- **Brand rejection, all slots.** Any visible brand, airline livery or logo that isn't the subject's rejects the clip.
- **Fallback for locked Short beats with no match** (`short_fallback` stage, `short.do_fallback`, writes `short/fallback.json`): first the beat's route map if the script gave one (`backdrop.kind == "map"`), then AI stills from WanGP (`still_prompt`, 1088×1920) turned into 2.5D parallax layers (`depth.py`, Depth Anything V2 Small ONNX on the CPU, downloaded once to `models/`), else a headline card. If WanGP is down, beats get the map or headline card. Each fallback visual covers about 7 s.

Stages that don't apply to the chosen mode are skipped (`stages_for(mode)`). Rendering stages retry automatically, 3 times, 60 s apart.

### Short pipeline (`app/studio/short.py`): almost no GPU
1. **short_script.**
   - Notes come from `writer.make_notes`, cached in `src/notes.txt` so the long and short scripts share them.
   - One LLM call writes 7–12 beats. Each beat has narration (30–48 words), 1–2 animated graphics and 2 Pexels search phrases.
   - Graphic types: hook, quote, stat, compare, icons, timeline. A beat's second graphic appears when its `at` word is spoken.
   - `writer.fact_check` checks the narration and graphics against the transcript.
   - The end-card beat is added automatically.
   - The plan is saved in `short/plan.json`.
2. **review.** **Skipped by default** (the "Skip script review" box is ticked). Untick it to read and edit the script first. Setting "When review is skipped, still pause if the fact-check raises questions" (`pause_on_questions`, off by default) pauses only when the fact-check has questions; otherwise the questions are written to the log. When reviewing, check:
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
   - **Keys:** `PEXELS_API_KEY` and `PIXABAY_API_KEY` in the project `.env`; NASA needs none. Check them at `http://127.0.0.1:<port>/api/test_footage?q=...&orient=portrait|landscape`.
   - **Selection:**
     1. The script AI ranks candidates by meaning from each library's own description (Pexels page title, Pixabay tags, NASA title). This uses no GPU.
     2. The vision model checks only the top-ranked clips for overlaid text or brand logos, scene cuts, darkness or blur. It does not judge relevance; it was too literal at that in tests.
     3. If nothing passes, unlocked beats fall back to the library's own top results; locked beats get fallback visuals instead (see Subject lock).
   - **Cutting:** only the needed seconds are cut straight from the source URL at CRF 14, with no full download.
   - **Top-up:** in the Short build, beats with too little footage are topped up from other beats' clips, and each clip gets screen time in proportion to its length.
   - **Files:**
     - `short/stock/footage.json`: search cache, rankings and picks, used to resume a job.
     - `short/stock/pick.json`: the clips used.
     - `clips/` and `sheets/`: the clips, and the 4-frame preview sheets for checking picks by eye.
   - Removing a beat from `footage.json` → `picked` makes it re-pick on Resume.
4. **short_voice.** WanGP TTS (`qwen3_tts_base`, cloned narrator voice) per beat; word timings from faster-whisper, saved in `short/timings.json`.
5. **short_fallback.** Map, AI-still (2.5D) or headline visuals for locked beats without matching footage (see Subject lock).
6. **short_render.**
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
- `Backdrops.tsx`: full-screen fallback backgrounds. `MapBackdrop` (d3-geo + Natural Earth 1:50m via `world-atlas`, offline) draws the route origin → actual landing in gold with a plane, the planned destination dashed; `HeadlineBackdrop`; `LayersBackdrop` (2.5D parallax on depth layers).
- Backgrounds are one continuous layer across beats, each shot overlapping the next by 0.4 s, so there is no dark frame at beat changes.
- New npm deps (Oct 2026): `d3-geo`, `topojson-client`, `world-atlas` (all pure JS).

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
- **The app's port can change** when Pinokio restarts (42006 before Oct 4, then 42003). The start.js page prints the current one ("Video Studio running on ...").
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
  - brand rejection is now in the vision check; watch whether small logos still get past `qwen2.5vl:7b`.
- Upload the Moonshots long video, and put its link in the Short descriptions.

## Visual review for Shorts (Phase 1, Oct 2026)
- Job form "Visuals (Shorts)": **Auto** (ladder stops at the first passing step; pauses only when a beat is uncertain: the check
  couldn't run, or the AI still failed and the beat fell back to reconstruction/headline) or **Review every beat** (every
  treatment except animation for every beat, then pauses).
- Animation (WanGP LTX-2 image-to-video, ~14 min per 7 s clip on the RTX 5060: the 19B model streams through system RAM) runs ONLY
  from an explicit click: "Show all options for this beat" or "Add animation". Approve auto / Approve all remaining never animate.
  FastWan 5B was tested (Oct 2026): 7.6 min and unusable quality, so it is not used.
- Stage `short_review` (after short_fallback): `review.collect` writes `short/review/review.json` (candidates per beat, auto pick,
  decisions, history); job status `awaiting_visuals`. Survives restarts.
- Review panel on the job page: thumbnails (coarse stills; garbled animations show the worst frame with ⚠), click = 2-second middle
  preview (ffmpeg for clips, Remotion `ShotPreview` composition for parallax/reconstruction/map), Use (multi, ordered), Approve auto,
  Skip (headline card), Show all options for this beat (GPU, one beat), Refine (DeepSeek: descriptive / correction / supply ->
  new prompts + stock searches -> new option set; History -> Revert), your own file (path on the PC or URL, with a label).
- After the render: `output/thumbnail_9_16.png` (thumb916.py; options in short/thumb.json; regenerate/approve on the job page;
  Settings "Channel name"), then unused treatment files and previews are deleted (thumbnails kept; used files listed in short/used.json).
- Smoke test: Settings -> "Run smoke test (1 beat)" or `POST /api/smoke {"visual_review":"every"}`: fixed one-beat script, no YouTube.

## Post-render editing (Oct 2026) — app/studio/edit.py
- Every finished job page: player + "Edit at m:ss (beat)" -> beat panel (thumbnails, 2 s previews, Refine, Supply, Add animation,
  Show all options) + fit buttons (Auto / Freeze / Slow down / Loop / Trim / Speed up / Add still) + Preview in the video (half res,
  with narration) + Apply to video. Undo last edit (one level), Full re-render (edits kept), Done editing (clean up = prune).
- Fit rule (edit.layout): longer footage -> middle segment; shorter -> information beats get the beat's still/card after the
  footage, atmospheric beats (edit.atmospheric) slow motion up to 1.3x then hold the last frame.
- Shorts: keyframes forced on every beat boundary (edit.ensure_keyframes, after each render / first edit of an older Short);
  apply = Remotion renders the beat's frame range of Teaser (cached bundle, media over http) -> encoded with ENC_S -> stream-copy
  splice at the keyframes -> original audio muxed back; teaser.json updated; review.json beat "edit" (build() honours it).
- Long videos: beat = visual slot (sid_vi); workspace job/longedit (16:9 Short-like review space, short/space.json);
  apply = BeatClip render -> v_<sid>_<vi>.mp4 -> assemble.section() rebuilds that section -> sections joined by stream copy ->
  audio from build/final_audio.wav. plan visual edit_clip keeps the edit for full rebuilds.
- After a render only previews are pruned now; unused treatment files stay until "Done editing (clean up)".

## /make — describe a video (Oct 2026)
- http://127.0.0.1:42020/make: Describe box -> "Fill the form" (POST /make/parse: phi4-mini via Ollama, fallback gemma3:4b, plus
  rules in studio/make.py; links/paths/numbers always from the rules; model switches only count when the text mentions the topic)
  -> the real form (/?embed=1 in an iframe) filled by data-testid -> you click Make video -> live run pane (/make/status).
- Spec only has real options: input youtube|local_file|text (NotebookLM = local file), mode short|explainer|both, lengths,
  script_review, visuals auto|review, captions, presenter, script_ai. Research / TLDR / verification switch / fact-check switch /
  thumbnail / channel are reported as "not done" (they don't exist as per-job options).
- Saved jobs: F:\code\video-studio\make_saved.json. Local file by path: form field "file-path" (server copies it).
- app/vs_runner.py: Playwright runner (headless Edge; installs playwright on first use) -> screenshots/<ts>/ + steps.jsonl;
  POST /make/runner {spec, click_make, edit:{job,beat,cands,fit}}; Make video is only clicked when click_make is true (tests).
- Every post-render edit records state.edits[].verify = {frames_same, audio_same, decode_ok}.

## Smoke mode (30-second Short)
- "smoke test" on /make (or Make → "Smoke test (30-second Short, pipeline check)" in the form) makes a ~30 s Short: 2 beats of narration (~58-word target, accepted 0.8-1.2x) plus the closing line, about 75 words. Real Shorts keep the 2:00 minimum.
- No link given → `smoke_source` in config (the flydubai video; its transcript is cached, so YouTube isn't contacted).
- Policy: use smoke mode for pipeline iteration; real lengths only for actual videos.
- Measured 2026-10-08: job 20261008_190501, 33.0 s output, ~18 min end to end (about 15 min of it WanGP stills).

## Short length accuracy (fixed 2026-10-08)
- Cause of 2:04 vs 2:20: scripts were sized at 142 wpm; the narrator really reads ~155 wpm (16 jobs, 146-165), plus a loose +/-12% word check.
- Now: voice_wpm 155; words sized from target minus pauses, tail and the closing line; check +/-5%; after 3 misses the closest try is kept
  (not an unchecked re-ask); >10% long -> drop middle beats; the fact-check can lengthen the script, so it is cut again after (>6%).
- Render: if the narration is more than 3 s off plan["target_secs"], the pace is nudged up to +/-7% (atempo; beat timings scale with it).
- Verified: 2:20 job 20261008_201028 narration 138.5 s (stopped after narration); smoke 20261008_202035 37 s -> 35.0 s via the pace step.
