# Pipeline handoff: Video Studio fork (visual ladder v2, Flow, voice)

State as of 2026-10-19, fork `tariq424/video-studio-test`, commit `0cdf26f`. Server: port 42021, jobs in
`F:\videos_test\jobs`, launcher `scripts\start-isolated-test.ps1`. The main volume (`F:\code\video-studio`) is untouched.

First fully autonomous run with a Google Flow clip: job `20261019_204806`
(`output\Google_s_Gemini_4_Argon_writes_a_million_tokens_at_once_short.mp4`, 26 s).

---

## 1. Visual ladder (per beat)

Every rung is isolated (`short._safe`): a failure is logged with its reason and the next rung runs. Pause and cancel
still propagate. A beat that fails outright gets a headline card. Rungs are never skipped silently; each skip is logged.

| # | Rung | Where | Notes |
|---|---|---|---|
| 1 | **Stock** (Pexels, Pixabay; NASA / Internet Archive where relevant) | `footage.fill` | Hard relevance gate first (see below), then model ranking and vision vetting |
| 2 | **Source clip** (2.5 s from the original video) | `source_visuals.make` / `auto_request` | The beat's narration is matched to a real caption cue (no guessed timestamps). At most 2 per output |
| 3 | **Google Flow** (generated 10 s clip) | `flow.generate`, called in `short.do_fallback.prepare` | Long videos: `render.do_stills`, before the cloud still. Max 4 per video |
| 4 | **Real photos** (Openverse, Wikimedia Commons, Internet Archive) | `photos.find` | Only for beats locked to a named subject; skipped when the beat already has its source clip |
| 5 | **Cloud still** | `ladder.run` / `cloudgen` | |
| 6 | **WanGP still** (atmospheric beats only) | `ladder.run` / `wangp` | 5 s connect timeout; after 2 connection errors WanGP is skipped for 10 min (circuit breaker) |
| 7 | **Physics data** | `physics.provide` | Real data, the narration's numbers, the script's map route, or a labelled synthetic path. Saved to `short/physics/<slot>.json` |
| 8 | **Remotion graphics** | `graphics.render_payload` / `graphics.make` | Draws the physics payload; otherwise a template or Claude-written composition |
| 9 | CapCut | `capcut` | Only when graphics hard-failed and no physics payload; off by default |
| 10 | Parallax | `depth_free` | Only for a still the check couldn't judge |
| 11 | Illustration / silhouette | `illustrate.pick` | |
| 12 | Headline card | | The floor: always succeeds |

### Source clip vs stock

- Before stock is final, the 2 beats whose narration best matches a caption cue (at least 4 shared content words) have
  their generic stock **set aside** so rung 2 runs for them (`source_over_stock`).
- If the source clip then fails, **the set-aside stock is given back** to that beat (logged:
  `source clip failed; the stock set aside for it is back`).
- Reusing a transcript from an earlier job also copies its timed caption cues (`src/source_cues.json`); jobs with cues
  are preferred.

### Stock relevance gate (`footage.on_subject`)

A clip is rejected before any model or vision check unless its title / tags share:
1. a content word with the beat's stock queries (or its locked subject), **and**
2. a concrete word from the narration ("quantum", "Google", "recorder").

Broad words (computer, data, technology, digital, business...) don't count. For Pixabay tag lists, only the first 8
tags count. The closing-card slot is exempt. Log line: `skipped ... (its description names neither the shot's subject
nor anything the narration says: ...)`.

### Subject locking (`coherence.assign`)

A beat is locked to a story subject only on its **exact name**, or its brand when only one subject has that brand
(whole words). Generic category words ("camera", "chip") never lock. This fixed "Meta" matching "metallic" and a spy beat
locked to "Kling 4" because of "camera".

---

## 2. Google Flow rung (`app/studio/flow.py`)

**Setup (one time, done):** `scripts\flow-login.ps1` opens Chrome with the profile `F:\videos_test\flow_profile`; sign in
and close Chrome. **Close that Chrome window before any job**: two Chrome processes can't share the profile
("profile is already in use").

**Flow per beat** (2026 Flow UI, verified live):
1. Prompt: the beat's `still_prompt` + `motion`, else one DeepSeek call (`visual_prompt`). Rules: photorealistic, no
   text, logos or real people.
2. Launch installed Chrome (`channel="chrome"`) on the profile via Playwright (installed into the fork's `app\env`).
3. Open `https://labs.google/fx/tools/flow`. If no prompt box is showing (landing page), click **New project**.
4. Type the prompt into the session panel's text box. Send with an aria-labelled send button if present, otherwise
   the **last enabled button of the prompt panel** (the round arrow). If the text is still in the box: Enter, then
   Ctrl+Enter.
5. **Auto-approve.** Flow's agent asks: *"Would you like me to kick off this 1 video generation, costing 15 credits?"*
   with Approve / Always approve / Reject. The code clicks **Approve** once per generation:
   - first `get_by_role("button", name=re.compile(r"^\s*(check\s*)?Approve\s*$"))`
   - else `page.get_by_text("Approve", exact=True)`, because the choice is rendered as a plain element, not a button.
   - The exact match can't hit "Always approve", which is never clicked because it changes the account setting.
   - Log: `flow: approved the generation (15 credits)`. Setting: `flow_auto_approve` (default true, the owner's choice).
6. Wait up to `flow_timeout` (480 s). The media grid shows the result as a thumbnail (`<img>`), not `<video>`. Once a new
   tile appears, the code clicks the newest tile (and hovers it) so its player loads a `<video>`. A blob/data source
   is fetched in the page; an https source via the browser context. The file is re-encoded to H.264 30 fps.
7. Output: `short/flow/<beat>_flow.mp4` plus `.prompt.txt`; `usage.json` counts clips per video.

**Failure handling.** Any failure is logged and the ladder goes on to photos. Failures that would repeat for every beat
(no profile, not signed in, prompt box not found, out of credits) skip Flow for the rest of the job. On failure the page
is saved as `short/flow/<beat>_fail.png` and `<beat>_fail.html`, for selector fixes when Flow's UI changes.

**Settings:** `flow_on`, `flow_profile`, `flow_url`, `flow_timeout` (480), `flow_max_per_video` (4), `flow_headless`
(false), `flow_auto_approve` (true).

**Cost:** 15 credits per clip (Omni 1.1 Flash, 10 s, 9:16 default), up to 60 per video. Each attempt also creates an
"Untitled" project in the Flow account.

---

## 3. Voice / humor (Shorts)

The rule that worked: **don't make the model do everything in one pass.**

- **Script** (`short.SHORT`): a plain, clear, conversational summary. One short opinion of ours ("honestly,", "our take:")
  is welcome, but the prompt says **do not write jokes**. No hard opinion+joke gate (it choked DeepSeek: 3-6 failed
  attempts per run).
- **Fact-check** (`writer.fact_check`): an opinion of ours (`take`) is protected word for word; if accuracy requires,
  it's rechecked without protection and logged.
- **Smoke test (30 s)**: `short.trim_smoke` trims in code (the model ignores word budgets). It keeps the first sentence,
  or the sentence with a number when the first has none (with the first if both fit in 18 words), plus our opinion
  sentence; it never cuts inside a sentence. Then `writer.punch_up(force=True)` adds one joke per beat.
- **Full Shorts**: the editorial review (analysis + humor, up to 5 attempts with per-beat failure reasons) runs, then
  `punch_up` only for beats still without a joke.
- **Punch-up** (`writer.PUNCH`): one DeepSeek call per beat: "ONE funny closing observation (max 12-18 words), dry,
  snarky, conversational, about a concrete consequence... If the topic is too dry, joke about how dry it is." No new
  facts; never punches at victims or ordinary people. Appended as the beat's last sentence. Uses Claude only if an
  Anthropic key is set; **the owner chose to stay on DeepSeek**.
- **Short-only jobs** never promise a longer video: the prompt forbids it and any such line is stripped from the beats
  and the description. With both outputs, the description keeps `Full breakdown: <PASTE LONG VIDEO LINK HERE>`, which
  the YouTube Publisher replaces with the explainer URL (`POST /publish/pair` publishes the explainer first).

Example output (job `20261019_183936`):
> Google says its Willow quantum chip just got dramatically more reliable. *Big win for Google, and for anyone who likes
> their errors expensive and rare.*

---

## 4. YouTube source downloads and 403

`source_visuals._download_range`:
1. **Fast path:** `yt-dlp -j` (format JSON) gives the stream URL **and its `http_headers`**. ffmpeg seeks into the
   stream with `-headers ... -ss <cue> -t 2.8`. Usually 7-17 s. Without the headers, googlevideo answered
   **403 Forbidden**.
2. **Fallback:** yt-dlp `--download-sections` (bounded to 90 s).
3. If both fail: `source evidence unavailable: <reason>` (the long stream URL is replaced by `<url>`) and the ladder
   continues. A beat whose stock was set aside gets it back; otherwise it goes on to Flow.

**Known:** YouTube still refuses some requests intermittently (403 on the same video that worked minutes earlier).
Retrying the run usually works.

---

## 5. Restarts (no manual PID hunting)

- `F:\code\restart-stack.ps1` kills 42021 and 42030, starts both, and polls up to 60 s for HTTP 200.
- `F:\code\restart-watcher.ps1` (start once per logon): when `F:\code\.restart-request` appears it runs the restart
  script and writes `F:\code\.restart-result`. Claude triggers restarts by creating the request file.
- The fork server runs with `VS_RELOAD=0`: **every code change needs a restart** before it takes effect.

---

## 6. Known limitations

1. **Trim weakness:** the smoke trim chooses sentences by position and numbers, not meaning. When a beat has no number
   it keeps the first sentence, which can be background (e.g. "A token is a chunk of text the AI reads or writes"), and
   the punch-up joke then riffs on it.
2. **Flow generation time:** about 1-4 min per clip, longer when Flow queues ("high demand"). The wait cap is 8 min per
   beat; a smoke test with Flow takes about 8 min instead of 4. A timeout after Approve still spends the credits.
3. **Flow UI dependence:** selectors target the October 2026 layout. When Google changes it, use the `_fail.png` /
   `_fail.html` files to update `flow.py`.
4. **Strict stock gate:** abstract beats can end up with no stock at all and fall to source clips, Flow or graphics.
   Tune with `stock_subject_gate` / the word lists in `footage.py`.
5. **Source clip budget:** at most 2 per output (editorial caution, not a fair-use guarantee).
6. **Photo search:** Wikimedia Commons rate-limits (HTTP 429). The User-Agent follows Wikimedia's policy and downloads
   are spaced 3 s apart, but photo rungs can still be slow.
7. **WanGP:** down for most of these tests; the ladder ran without it. The long-video stills stage no longer stops when
   WanGP is down (under ladder v2).
8. **Joke quality** varies run to run; the checks can prove a joke exists, not that it's funny.

## Tests

`python -m pytest -q tests` (55 pass), including `tests/test_flow_source_rungs.py` and `tests/test_voice_protection.py`
(source-clip matching, Flow fallthrough, subject locking, stock gate, smoke trim, punch-up, fact-check protection).
