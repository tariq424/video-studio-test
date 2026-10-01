# Video Studio — Workflow Handoff

This guide lets any AI assistant (ChatGPT, etc.) or a human continue this project. Paste or upload this file at the start of a new chat.

Video Studio is a fork of Explainer Studio (`F:\code\explainer-studio`, github `tariq424/explainer-studio`). That repo is frozen; new work happens here.

- **Code:** `F:\code\video-studio`, a private GitHub repo at `tariq424/video-studio`. The copy on F: is the working copy; GitHub is kept in sync with it.
- **Outputs:** `F:\videos\video_studio\jobs\<job id>\`. A job's videos are in its `output\` folder.
- **UI:** `http://127.0.0.1:42006`. Start it from Pinokio → **Video Studio** → Start (launcher scripts in `C:\pinokio\api\video-studio`, with copies in `pinokio/` in the repo).

## Ground rules (owner: Tariq)
- **Everything on F:.** Videos go in `F:\videos`. C: is for system files only; Ollama's model store on C: is the one accepted exception.
- **Never print, paste or type API keys.**
  - LLM keys live in Windows Credential Manager under the service name `ExplainerStudio`, shared with the old app. Enter them only in the app's Settings page.
  - The Pexels key is in the project's `.env`, which git ignores. Scripts read it at runtime; never display it.
- **No deletions** without explicit approval. Rename old versions instead (for example `_v2.mp4`).
- **No footage from YouTube or podcasts.** Use only Pexels stock (free for commercial use, credited anyway), our own AI clips and stills, and our own graphics.
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
Full order: `transcript → script (long) → short_script → review → short_stock → short_voice → short_render → charts → voice → captions → presenter → motion → stills → assemble`.

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
3. **short_stock.**
   - Searches Pexels for portrait clips of at least 6 s.
   - Builds a 4-frame contact sheet from each clip's preview pictures, so nothing is downloaded before vetting.
   - A vision model **describes** each clip and drops ones with overlaid text or brand logos, scene cuts, poor quality or very dark footage. Setting `vet_provider`: `local` uses Ollama `qwen2.5vl:7b`; alternatives are `zai`, `claude` and `off`.
   - The **script AI** (DeepSeek) then picks 2–3 clips per beat by matching those descriptions to the narration, with no repeats, plus one spare for the end card. A small vision model is good at describing clips but bad at judging fit; the test run proved it, first rejecting every clip and then accepting every clip.
   - Downloads the picks and trims them to 1080×1920, 30 fps, at most 10 s.
   - Files: `short/stock/pool.json` (vetted candidates), `pick.json` (chosen clips), `clips/`, and `sheets/` (contact sheets, for checking picks by eye).
   - Still check the picks by eye before rendering. Removing an entry from `pick.json` makes the next Resume re-pick that beat.
4. **short_voice.** WanGP TTS (`qwen3_tts_base`, cloned narrator voice) per beat; word timings from faster-whisper, saved in `short/timings.json`.
5. **short_render.**
   - Builds `short/public/teaser.json`, `voice.wav` (loudness -14 LUFS) and the media folder.
   - Runs `npx remotion render src/Root.tsx Teaser` in `remotion/` with `--public-dir` set to the job's `short/public`.
   - Writes `output/<title>_short.mp4` and `output/youtube_short_description.txt` (source credit plus Pexels credits; if the mode is Both, paste the long video's link into its placeholder).

### Remotion template (`remotion/`)
React/TypeScript, Remotion 4.0.531. `npm install` and the Chrome headless shell are installed by Pinokio Install.
- `Root.tsx`: loads `teaser.json` from the public dir.
- `Teaser.tsx`: timeline, progress bar and top tag. Graphics stay at most 4.6 s so the footage shows.
- `Background.tsx`: stock clips are cover-fit with a slow zoom at 0.85× speed; landscape clips use `fit:"frame"`; stills scroll.
- `Captions.tsx`: karaoke captions, up to 6 words, 46 px, at y=1390. The space between words must stay **inside** the span.
- `Graphics.tsx`: the graphic types plus the CTA end card (optional thumbnail and badge).

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

## Test result (Oct 1 2026)
- **Job:** `F:\videos\video_studio\jobs\20261001_083509`, the Moonshots AMA #293 as a Short only.
- **Output:** `output\AI_Is_Already_Uploading_Minds_Moonshots_AMA_in_3_Min_short.mp4`, 2:56 long, with 27 clips.
- **Fixed by hand:** the script was trimmed from 451 to 425 words, and "Dennis" was corrected to Demis Hassabis.
- **Clip picks:** these were corrected by hand. The new AI picking (described above) had not yet run on a full job.
- **Render:** about 7 min on the PC with Remotion. Narration took about 9 min on the GPU.

## Open items
- Upload the Moonshots long video, and put its link in the Short descriptions.
- Optional: B-roll for long videos from the same Pexels search plus vetting, which would cut WanGP render time.
