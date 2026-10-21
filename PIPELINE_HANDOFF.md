# Pipeline handoff: Video Studio fork

State as of 2026-10-21. Fork: `tariq424/video-studio-test`, checked out at `F:\code\video-studio-test`.
Server: port 42021. Jobs: `F:\videos_test\jobs`. The main volume (`F:\code\video-studio`) is untouched.

Proof run: smoke test job `20261021_013704`, output `Steal_Perfect_AI_Image_Prompts_from_Pinterest_short.mp4` (37 s).
In that run the source clips, the Gemini images (with rembg parallax), a Flow clip and stock all rendered. WanGP never
started.

---

## 1. The visual ladder (ladder v2)

Each beat climbs the ladder until it has the number of visuals it needs.

| # | Rung | Code | What it does |
|---|---|---|---|
| 1 | **Stock footage** | `footage.fill` | Pexels / Pixabay. A hard relevance gate runs first (see 1.1), then model ranking and vision vetting. |
| 2 | **Source clip** | `source_visuals.make` | 2.5 s of the original video at a caption cue that matches the narration. Shown full frame, tagged `SOURCE · <channel>`. At most 2 per output. |
| 3 | **Image generator (Gemini)** | `imagegen.generate_many` | Gemini describes a screenshot of the source and writes a recreate prompt, then generates a new image from it. A beat that needs more visuals gets a second image (another angle / a close-up). See section 2. |
| 4 | **Source parallax** (Remotion render #1) | `depth.cutout_layers` | rembg cuts the subject out of the Gemini image; Remotion moves the two layers for 2.5D. See section 3. |
| 5 | **Google Flow** | `flow.generate` | A generated 10 s video clip. **Paid credits (15 per clip): the last resort for AI video.** |
| 6 | **WanGP** | `wangp.py` | Only for atmospheric stills, the presenter, or the TTS fallback. Started on demand and unloaded right after. See section 4. |
| 7 | **Physics** (data provider) | `physics.provide` | Real data, the narration's numbers, the script's map route, or a labelled synthetic path. Off for non-physical subjects. |
| 8 | **Remotion graphics** (render #2) | `graphics.render_payload` / `graphics.make` | Draws the physics payload, or else a data template / composition. |
| 9 | **Headline card** (render #3) | `HeadlineBackdrop` | The floor: always succeeds. |

**Removed on 2026-10-21:**
- Bing Image / Bing Video / Meta / Sora automation
- OCR
- the real-photo rung
- the illustration / silhouette rung

On the explainer, shots locked to a named subject now go down the image ladder instead of to real photos.

**Inactive by default:**
- Cloud stills: no provider is configured.
- CapCut: off.

**No on-screen labels (2026-10-21):** rung tags (`GENERATED · GEMINI`, `GENERATED · FLOW`, `SOURCE · ...`, `ILLUSTRATIVE`,
`SYNTHETIC`, `GRAPHICS`, `RECONSTRUCTION`) are kept in the timeline JSON and the job log but never drawn on the video. AI use
is disclosed through YouTube's "Altered content" answer instead (the Publisher sets Yes when a timeline has a
`GENERATED · GEMINI / FLOW / WanGP` tag, or the Newsroom's `ai_content.json` says so).

Every rung is isolated (`short._safe`). A failure is logged with its reason and the next rung runs. Pause and cancel
still propagate. The job log prints the ladder line, then one decision line per slot, e.g.
`b1#2: new image from gemini (described from the source screenshot), rembg parallax`.

### 1.1 Stock relevance gate (`footage.on_subject`)

A clip is rejected unless its title / tags share both:
- a content word with the beat's stock queries (or its locked subject), and
- a concrete word from the narration.

Other rules:
- Broad words (computer, data, technology...) don't count.
- For Pixabay, only the first 8 tags count.
- The closing-card slot is exempt.

### 1.2 Source clips (`source_visuals.py`)

- **Cue matching:** the beat's narration is matched to a real caption cue (no guessed timestamps). At least 4 shared
  content words are needed to set the beat's generic stock aside. If the source clip then fails, that stock is given back.
- **Download:** fast path is `yt-dlp -j` (stream URL + `http_headers`), then ffmpeg seeks into the stream. Without those
  headers googlevideo answers 403. Fallback: yt-dlp `--download-sections` (bounded to 90 s).
- **Shorts:** a full-frame `video` item, copied into `public/media/fb`.
- **Explainer:** the visual's footage (`v["stock"]`, `stock_src: source`).
  - At most one per section, never the same excerpt twice.
  - It gets only its own length (+0.4 s); the section's other visuals share the rest of the slot.
- **Load errors:** a clip that fails to load in Remotion logs `Remotion media error: <file>: <reason>` (`[VS-MEDIA-ERROR]`
  marker in `Background.tsx`, copied into the job log by both render loops).

---

## 2. Gemini automation (`app/studio/imagegen.py`)

Playwright drives Gemini (`https://gemini.google.com/app`) in installed Chrome, using the Google-signed-in profile that
Flow already uses (`F:\videos_test\flow_profile`; setting `gemini_profile` to use another). Everything happens in one
Gemini chat per beat:

1. **Upload** the source screenshot. This is the rung-2 screenshot, else a frame of the rung-2 clip, else a fresh
   screenshot at the matched cue (`source_visuals.snapshot`; at most 2 fresh ones per output).
   - Upload method: an `input[type=file]` if present, else the "Open upload file menu" button → "Upload files" → file
     chooser.
2. **Describe + prompt.** It sends "Describe this image in detail, then write a prompt to recreate it without brands or
   text. Put the final prompt on its own line, starting with PROMPT:"
   - The answer is read from `model-response` once it stops streaming (Stop button gone, text stable).
   - `extract_prompt` takes the `PROMPT:` line; else a fenced or quoted block; else the last paragraph.
3. **Generate.** It sends "Generate an image: <prompt> Tall vertical 9:16 portrait image. No text, letters, logos or brand
   names." (16:9 for the explainer). It waits for a new image at least 300 px on its short side.
4. **Download.** It hovers the image and uses Gemini's "Download" button; else it fetches the image URL
   (googleusercontent `=s0` for full size) with the browser's cookies. The image is re-saved as JPEG at
   `short/imagegen/<beat>_gemini.jpg`, with the prompt beside it (`.prompt.txt`).
5. **Second image** (beat needs more than one visual). In the same chat it sends "Generate a second image of the same
   scene from a different camera angle..." (then "...a close-up of the main subject..."), giving `<beat>_gemini_2.jpg`.
   - Capped by `imagegen_per_beat` (2).
   - If the extra image fails, the first is kept.
   - Flow only runs for whatever the beat still lacks.

**No source screenshot:** Gemini writes the prompt from the beat's narration ("Write a prompt for a photorealistic image
that illustrates this narration..."). No other model is involved: no DeepSeek, Bing or Meta.

**Failure handling:**

| Situation | Effect |
|---|---|
| Not signed in / CAPTCHA / "unusual traffic" | Gemini is skipped for the rest of the job. CAPTCHAs are **never** automated: run `scripts\imagegen-login.ps1 -Site gemini` and clear it by hand. |
| Usage-limit text | Cools down for `imagegen_cooldown_hours` (6). The cooldown is saved in `F:\videos_test\imagegen_state.json`, so later jobs skip too. |
| Gemini declines / no image within `imagegen_timeout` (240 s) | That beat falls to Flow. |
| Any failure | Saves `short/imagegen/<beat>_gemini_<step>_fail.png` + `.html` (steps: open, describe, generate, download, extraN) for selector fixes when Gemini's page changes. |

**No real people:** the describe / narration prompt requires anonymous figures (from behind, silhouettes, hands, out of
focus) and every generate request adds "No real or recognizable people" (added 2026-10-21 after an image resembled a real
former president). Flow prompts carry the same rule.

**Settings:** `imagegen_on`, `gemini_profile`, `gemini_url`, `imagegen_timeout`, `imagegen_per_beat` (3: scene, another
angle, close-up; raised from 2 on 2026-10-21 because 165 s Shorts used Flow for every beat's third visual),
`imagegen_max_per_video` (8 beats), `imagegen_cooldown_hours`, `imagegen_headless` (false).

**Account note:** Gemini and Flow automate the same Google account. On 2026-10-10 the project removed Gemini browser
automation over account-suspension risk; it was brought back on 2026-10-21 at the owner's request, so that risk applies
again.

---

## 3. Remotion parallax workflow (rung 4)

`depth.cutout_layers(image, prefix, log, size)`:
1. The Gemini image is resized and cropped to fill the frame (1080x1920 for Shorts, 1920x1080 for the explainer).
2. **rembg** (`u2net`) cuts out the subject → `<prefix>_L1.png` (RGBA). The model (~170 MB) downloads once into
   `F:\code\video-studio-test\models\u2net`.
3. The subject area is painted out of the background (blurred fill from its surroundings) → `<prefix>_L0.jpg`, so moving
   the subject never reveals a hole.
4. Fallback: if rembg isn't installed, or finds no clear subject (under 2% or over 90% of the frame), the depth-map
   layers are used instead (`depth.layers`, Depth Anything V2 ONNX).

**Rendering:**
- Shorts: the layers become a `{"type": "layers", "layers": [...], "tag": "GENERATED · GEMINI"}` background.
- Explainer: `v["layers"]` → the same `layers` background in `explainer._visual_bg`.
- Remotion's `LayersBackdrop` moves the layers at different speeds (2.5D).
- If parallax fails, the image is shown as a still.

---

## 4. WanGP memory policy (`app/studio/wangp.py`)

- Nothing starts WanGP when a job starts. `alive()` reports "running, or can start on demand" and **never starts it**
  (the status pill reads "WanGP: starts on demand").
- The first real generation starts WanGP's MCP server from the Pinokio install (`wangp_dir`, default
  `C:\pinokio\api\wan.git`): `app\env\Scripts\python.exe wgp.py --mcp --mcp-transport streamable-http --mcp-port <free>`.
  Output goes to `F:\videos_test\wangp_on_demand.log`.
- **Unload:**
  - Right after each generation, the process is stopped (taskkill /T), which unloads every model and frees the VRAM.
  - Batches (`with wg.hold()`): presenter clips, narration chunks and motion run as one batch and stop once at the end.
  - Every job also releases it when it ends, whether it succeeded, failed or was cancelled.
- A WanGP you started yourself in Pinokio is used but never stopped.
- **Presenter disabled → WanGP never starts.** If the presenter is on and WanGP fails, the presenter is skipped
  ("On-screen presenter skipped (...)") and the explainer continues.
- **Not yet exercised live:** the on-demand start. No test job has needed WanGP. A 3-minute explainer with the presenter
  on would prove it.

---

## 5. Voice and humor

The rule that works: summary first, punch-up second. Don't make the model write facts, opinion and jokes in one pass.

**Short** (`short.SHORT`):
- The script is a plain summary with one short opinion; the prompt says "do not write jokes".
- Then the fact-check (our opinion and joke are protected word for word).
- Smoke test only: `trim_smoke` cuts in code to ~30 s.
- `writer.punch_up` adds one dry, snarky joke per beat (a separate DeepSeek call).

**Explainer** (`writer.write_plan`):
- The section prompt asks for a plain summary, no jokes.
- Then `fit_length`, the fact-check and the jargon check.
- Then `writer.punch_up_long`:
  - one "Our take:" sentence per section, inserted ~60% of the way through
  - one joke at the end
  - a second joke in sections over 220 words
- The old one-pass editorial rewrite is opt-in (`explainer_editorial_review`); it failed 5 of 5 times on DeepSeek.

**Other rules:**
- Short-only jobs never promise a longer video.
- With both outputs, the description keeps `Full breakdown: <PASTE LONG VIDEO LINK HERE>` for the YouTube Publisher.

---

## 6. Physics gate

`physics.non_physical` turns physics off for non-physical subjects (laptops, MacBook, apps, AI models, websites,
Pinterest...) unless the beat also names a real moving thing (vehicles, ships, aircraft, storms...). Log:
`physics off: 'Pinterest' is not a physical object`.

---

## 7. Operations

### Restarts

- `F:\code\restart-stack.ps1`:
  1. Stops the previous fork server (by `server.pid`) and every process listening on 42021 / 42030 (Get-NetTCPConnection
     plus a netstat fallback, then taskkill /T).
  2. Starts both servers.
  3. Reports SUCCESS **only if 42021 belongs to the new process**.
- On 2026-10-20 three stale servers were found stacked on 42021; the old script had reported SUCCESS while old code kept
  serving. Some results before that date may have come from older code than reported.
- `F:\code\restart-watcher.ps1` (start once per logon): creating `F:\code\.restart-request` makes it run the restart
  script and write `F:\code\.restart-result`.
- `F:\code\.pip-request` (one line of package names) is installed into the fork's env during the next restart. That is
  how rembg was installed; it also moved Pillow from 13.0 to 12.3.
- The fork runs with `VS_RELOAD=0`: every code change needs a restart.

### Sign-in / checks

- `scripts\imagegen-login.ps1 -Site gemini|flow` opens Chrome on the shared Google profile.
- Close every Chrome window on that profile before a job: two Chrome processes can't share one profile.
- Flow auto-approves each generation ("Approve", never "Always approve").

### Settings worth knowing

| Setting | Default |
|---|---|
| `flow_max_per_video` | 4 |
| `flow_timeout` | 480 |
| `imagegen_*` | see section 2 |
| `wangp_on_demand` | true |
| `wangp_start_timeout` | 300 |
| `source_snapshot_max_uses` | 2 |
| `source_visual_max_uses` | 2 |

---

## 8. Known limitations

1. **Gemini page dependence.** The selectors target the October 2026 Gemini page; when Google changes it, use the
   `_fail.png` / `_fail.html` files.
2. **Gemini images** may carry small garbled lettering (e.g. on a watch dial) despite "no text", plus Google's own
   visible / SynthID watermarking.
3. **Length.** Narration runs ~20% long (a 30 s smoke test came out 36-37 s). The 3-minute explainer test came out 5.6
   minutes (the writer runs long, plus the added takes and jokes).
4. **YouTube 403s** on source downloads still happen intermittently; the beat then falls to the next rung.
5. **Flow** takes 1-4 minutes per clip, longer when queued; a timeout after Approve still spends the credits.
6. **WanGP on-demand start** is unit-tested only (see section 4).

## 9. Tests

`python -m pytest -q tests`: 76 pass. Key files:
- `test_imagegen_wangp.py`: the real Playwright Gemini flow against `tests/fixtures/mock_imagegen.html` (upload →
  describe → prompt → generate → second angle → download, refusal, no profile, saved cooldown), the rembg cut-out, and the
  WanGP on-demand lifecycle.
- `test_four_fixes.py`: full-frame source clips, explainer punch-up, physics gate, presenter never crashes.
- `test_source_visuals.py`, `test_flow_source_rungs.py`, `test_voice_protection.py`.
