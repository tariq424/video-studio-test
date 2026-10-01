# Explainer Studio — Workflow Handoff

**Project home (code): `F:\code\explainer-studio`** — git repo, pushed to GitHub (private).
Outputs (jobs, shorts, videos) stay in `F:\videos\explainer_studio`. Secrets: `.env` (Pexels key) and `settings.json` live in the project but are git-ignored; API keys are in the Windows vault.
Folders: `app/` (Flask app + pipeline), `remotion_teaser/` (teaser Short, Remotion), `remotion_short/` (an earlier Short template from another session), `pinokio/` (copies of the launcher scripts in `C:\pinokio\api\explainer-studio`).

This guide lets any AI assistant (ChatGPT, etc.) or a human continue this project. Paste or upload this file at the start of a new chat.

## Ground rules (owner: Tariq)
- **All outputs go on F:.** Videos go in `F:\videos`. C: is for system files only.
- **Never print, paste or type API keys.** Keys are stored in Windows Credential Manager (service `ExplainerStudio`) and entered only through the app's Settings page. The Pexels key in the project `.env` is read by scripts at runtime and must never be displayed.
- **No deletions** without explicit approval. Rename old versions instead (for example `_v2.mp4`).
- **No footage copied from YouTube or the podcast.** We use only Pexels stock (free, commercial use OK), our own AI-generated clips and stills, and charts.
- **Communication:** be direct and terse, and give honest assessments.

## Hardware and tools
- **PC:** Windows, RTX 5060 Ti 16 GB.
- **Pinokio:** runs at `http://localhost:42000`. To run one of the app's helper scripts, open `http://localhost:42000/api/explainer-studio/<script>.js`. The launcher scripts live in `C:\pinokio\api\explainer-studio\` (start.js, install.js, test_ff.js = generic runner).
- **WanGP:** runs local generation; its MCP endpoint is `http://127.0.0.1:42004/mcp/`. Models:
  - `flux2_klein_9b` for stills (1920×1088);
  - `ltx2_distilled` for motion clips. Use **1280×720 landscape, 121 frames only**. Vertical LTX output always burns in gibberish text.
  - `qwen3_tts_base` for the cloned narrator voice.
- **Ollama:** `qwen3:14b` (models on C:, accepted). Optional local script provider.
- **ffmpeg:** comes from the imageio-ffmpeg package (7.1, includes libass), installed in the app's own Python environment (`app\env`).

## Part 1 — Long explainer video (Explainer Studio app)
- **Location:** app code in `F:\code\explainer-studio\app\`; UI at `http://127.0.0.1:42005` (start it via Pinokio start.js).
- **Use:** paste a YouTube link and set a target length, then press Start. Jobs are saved in `F:\videos\explainer_studio\jobs\<timestamp>\`.
- **Pipeline stages**, in `studio/pipeline.py`. Failed stages retry automatically, 3 times, 60 s apart.
  1. **transcript** (`transcript.py`): YouTube captions, falling back to faster-whisper.
  2. **script** (`writer.py`): written in chunks, notes → outline → sections → fact check against the transcript. Default provider is **DeepSeek** (`deepseek-v4-pro`, Anthropic-compatible endpoint, thinking disabled). Other providers: z.ai, Claude, Ollama. Provider code is in `llm.py`; settings are in `config.py`.
  3. **review:** the owner approves a clean script in the UI. Before showing it, the AI should check it itself: correct names (the guest is **Salim** Ismail), facts against the transcript, and only ask the owner about things it can't fix.
  4. **charts** (`charts.py`).
  5. **voice** (TTS clone, `render.py`). The text sent to TTS is folded to plain ASCII ("Rémi" → "Remi").
  6. **captions** (`captions.py`): one caption per full sentence (split if over about 24 words), keyword highlighted in gold, emoji icons. Word timings come from faster-whisper small.en.
  7. **presenter:** OFF by default. The lip sync was bad, so it was dropped.
  8. **motion**, then **stills** (WanGP).
  9. **assemble** (`assemble.py`, ffmpeg): scene cuts follow sentence starts.
- **Image QA:** DeepSeek can't see images, so `qa_provider` is set to off. Check stills by eye using contact sheets.
- **Known ffmpeg trap on Windows:** image overlays must be full-length looped inputs starting at t=0 (`-loop 1 -framerate 24 -t <dur>`), shown with `enable=between(...)`. Inputs that start late hang ffmpeg 7. Always pass `-nostdin` and set a timeout.
- **Latest finished long video:** `F:\videos\explainer_studio\jobs\20260929_222317\output\AI_s_Wild_Next_Decade_Safety_Abundance_and_the_Race_to_Scale_explainer_1080p.mp4`

## Part 2 — YouTube Short teaser (Remotion)
- **Source:** `F:\code\explainer-studio\remotion_teaser\`. This is React/TypeScript built with Remotion 4.0.531.
  - `src/Root.tsx`: loads `public/teaser.json`.
  - `src/Teaser.tsx`: the timeline. Each graphic stays at most 4.6 s so the scenery shows.
  - `src/Background.tsx`: stock clips are cover-fit with a slow zoom; landscape AI clips use `fit:"frame"` (shown whole over a blurred copy); stills scroll horizontally.
  - `src/Captions.tsx`: karaoke captions, up to 6 words per page, 46 px, at y=1390. Put the space between words **inside** each span, or the spaces disappear.
  - `src/Graphics.tsx`: graphic types hook, quote, compare, stat, icons, timeline and cta, shown in a band at the top.
  - `build_teaser.py`: builds `public/teaser.json` and `public/voice.wav` from the narration. The `SCENES` dictionary sets which clip plays in each beat (b0–b8) and which graphic appears at which word.
- **Teaser assets:** `F:\videos\explainer_studio\shorts\moonshots_teaser_v2\`
  - `plan.json`: 9 beats, about 300 words of narration.
  - `voice\b*.wav` and `timings.json`: made by `app\make_teaser_voice.py`.
  - `motion\*_l.mp4`: landscape AI clips made by `app\make_teaser_motion.py`. Ignore the vertical ones; they contain gibberish text.
  - `stock\`: Pexels footage. `queries.json` holds the searches, `candidates.json` what came back, `pick.json` the vetted picks, `clips\` the originals and `trim\` the 10 s 1080×1920 versions.
- **Rebuild steps:**
  1. Run `npm install` in the remotion folder.
  2. Copy the media into `public\media\`: stills (`s*.jpg`), motion clips (`*_l.mp4`), and `stock\trim\*.mp4` into `public\media\stock\`.
  3. Run `python build_teaser.py <teaser folder>`.
  4. Run `npx remotion render Teaser out.mp4 --concurrency=2`. The render is 1080×1920 and takes about 15 minutes.
- **Stock-footage workflow** (the "Videer" approach; Videer itself lives in `F:\videer` and `F:\videer_wsl`):
  1. Write 2 search phrases per beat. Use concrete visuals ("MRI scanner", "solar farm aerial"), not abstract ideas.
  2. Run `app\stock_search.py`. It calls the Pexels `/videos/search` endpoint with `orientation=portrait` and reads the key from the project `.env`.
  3. **Vet every clip.** Pull 4 frames spread across each candidate. Reject clips with on-screen text or logos, nonsense or off-topic content, duplicates, and shots that change partway through. Only about 1 in 6 candidates survives.
  4. Run `app\stock_download.py`, then trim each clip to 10 s at 1080×1920.
  5. Add creator credits to the description file, even though Pexels doesn't require them.
- **Current teaser (v3):** `F:\videos\explainer_studio\shorts\moonshots_teaser_v2\Moonshots_AMA293_teaser_short.mp4`, 118.6 s, about 96% motion. Older versions are `_v1` and `_v2` in the same folder.
- **Upload text:** `youtube_short_description.txt`. **TODO:** paste the long video's YouTube URL in place of the placeholder.

## Open items / ideas
1. Upload the long video, put its URL in the Short's description, then upload the Short.
2. Optional: build Pexels search, vetting and the Remotion render into the Explainer Studio app, so every job gets stock footage automatically. The hard part is vetting: it needs a vision model that can actually see images (DeepSeek can't), or vetting by eye from contact sheets.
3. Optional: render Remotion on the PC instead of in the cloud.

## Tips for the next AI
- Ask it to read the code files above before changing anything. The pipeline is stable, so make small edits.
- If a render or ffmpeg step hangs, check first for the late-starting-input trap described in Part 1.
- Large files: work locally on F:. Don't route big files through chat uploads.
