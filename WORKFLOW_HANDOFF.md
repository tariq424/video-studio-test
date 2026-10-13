# Video Studio — Workflow Handoff

This guide lets any AI assistant (ChatGPT, etc.) or a human continue this project. Paste or upload this file at the start of a new chat.

**The latest copy is always in the repo at `F:\code\video-studio\WORKFLOW_HANDOFF.md`.** A Google Doc copy ("Video Studio — Workflow Handoff", https://docs.google.com/document/d/1Lq8OdLu6XxxhxbXI9G_R5Q4URhVOq4TkKe4balVO1sU) may lag behind it.

Video Studio is a fork of Explainer Studio (`F:\code\explainer-studio`, github `tariq424/explainer-studio`). That repo is frozen; new work happens here.

- **Code:** `F:\code\video-studio`, a private GitHub repo at `tariq424/video-studio`. The copy on F: is the working copy; GitHub is kept in sync with it.
- **Outputs:** `F:\videos\video_studio\jobs\<job id>\`. A job's videos are in its `output\` folder.
- **UI:** `http://127.0.0.1:42020` (fixed since Oct 4; `start-video-studio.bat` starts it without Pinokio). Start it from Pinokio → **Video Studio** → Start (launcher scripts in `C:\pinokio\api\video-studio`, with copies in `pinokio/` in the repo).

## Visual ladder v2 (2026-10-12, on main, OFF by default) — graphics / physics / CapCut
**Nothing changes until you set `"ladder_v2": true` in settings.json** (no UI toggle on purpose). `capcut_fallback` is a second,
separate switch (also off). Not smoke-tested on the PC yet; sandbox-tested only (see below).

v2 order per beat (Shorts: `short.do_fallback` -> `short._v2_rungs`; explainers: `render.do_stills` / `do_motion` -> `render.v2_after_wangp`):
  1. Stock  2. Real photos  3. Cloud still  4. WanGP still - atmospheric only (`illustrate.wangp_lock`; "an illustration fits" no
  longer blocks WanGP)  5. **Remotion graphics (GRAPHICS)**  6. **Physics module (SIMULATION)**  7. **CapCut (CAPCUT)**
  8. Parallax  9. Illustration / silhouette  10. Headline card.
  - A still that passes its check (3/4) is still shown with parallax motion, as before (rung name "parallax" in the chain).
    Rung 8 is only a still the check couldn't judge ("check unavailable") - never one rejected for its content.
  - **No 3D reconstruction in v2** (the generic "object" spinning top included). v1 keeps it. The review menu doesn't offer it under v2.
  - Graphics and physics run once per beat; a beat's second slot goes on down the ladder.
- **Rung 5 - `studio/graphics.py`, `remotion/src/Templates.tsx`.** 8 templates: stat, quote, timeline, compare, route (map),
  chart (bar/line), list (stacked cards), abstract (gradient + particles + text). Router: reuses the script's beat analysis first
  (backdrop map -> route; on-screen stat / quote / timeline / compare / icons -> that template) - no model call; otherwise ONE
  small JSON call (script provider, DeepSeek) picks a template + fills its data, or says "none". "none" -> Claude writes a
  Remotion component (`graphics_claude`, Anthropic key + `script_model`, else the script provider): static checks (imports only
  react / remotion / ../theme; no fetch/eval/require/URLs/timers/random), rendered from `remotion/src/gen/` (gitignored,
  deleted after), one repair round. Cap: `graphics_claude_max_per_video` = 3. Output for both: MP4, `graphics_secs` = 8 s,
  limited colour range, in `<workspace>/graphics/<slot>.mp4`; plays at 1.0x and holds its last frame; treated as a text
  background (overlay cards that would cover it are dropped). Explainers: label burned in, clip at `motion/<id>.mp4`.
  **Hard failure** = crash / no output / timeout (`graphics_timeout` 300 s). A classifier "none" with Claude capped is NOT hard.
- **Rung 6 - `studio/physics.py`.** `route(sec)` picks a module only when the subject matches (keyword rules in `ROUTES`), then
  `fill()` gets parameters from the narration (one JSON call). New: **weather_event** (NOAA NHC CurrentStorms.json + forecast
  advisory for active storms -> forecast points + cone; NOAA HURDAT2 best track for past storms by name/year, cached in
  `<studio>/cache/noaa`; else narration positions; cone radii = approximate NHC average track error, labelled so) and
  **ship_route** (narration waypoints with coordinates; live AIS position via aisstream.io only with `aisstream_api_key` + an
  MMSI - needs `websocket-client`; no historical AIS). Drawn by `SimMapBackdrop` (Sim.tsx, kind "simmap"). vehicle_crash,
  structural_collapse, earthquake stay stubs (those beats fall to graphics / below). The pause/editor chat "simulate" uses the same modules.
- **Rung 7 - `studio/capcut.py`** (needs `capcut_fallback` too). Trigger: graphics HARD-failed and no physics module fit. The beat
  still gets a provisional visual (8-10) and is listed in `short/fallback/capcut.json`. After the Short renders, ONE session per
  video: VectCutAPI (run it yourself: `python capcut_server.py`, port 9001; set `capcut_api_dir` to its folder) writes a draft =
  the rendered Short + a CapCut text card (beat headline + CAPCUT label) over each failed beat; the draft is copied to CapCut's
  drafts folder; computer use (Anthropic API `capcut_cu_model`, `pyautogui`) opens it and clicks Export to `short/capcut/`.
  Success only if an MP4 of the Short's length appears; then it replaces the output (original kept as `*_pre_capcut.mp4`).
  Stops on sign-in / CAPTCHA / upgrade / consent / anything unexpected, `capcut_max_actions` 30, `capcut_timeout` 600 s.
  **Any failure -> the provisional visuals stay (falls through to rung 8+).** Shorts only; explainers skip rung 7.
  Beats the reviewer explicitly chose a visual for are left alone.
- Labels: GRAPHICS, SIMULATION, CAPCUT (existing labels unchanged). Chains (`short/fallback/chains.json`) show e.g.
  `stock -> graphics (template:stat (analysis))`, `... -> graphics -> simulation (ship_route)`,
  `... -> graphics -> capcut (pending: ...) -> headline`; chains carry `"ladder": "v2"` and `"capcut"`. Debugger:
  `treatment == graphics|simulation|capcut`, `escalated_past == graphics|simulation`. Review RUNG names added.
- **Sandbox tests done (2026-10-12):** all 8 templates rendered portrait + landscape and inspected; storm (track + cone) and ship
  maps rendered; template -> MP4 and Claude-component -> MP4 render paths (1080x1920, yuv420p, tv range, 6.0 s); code checker
  rejects fs imports / fetch; HURDAT2 parser on a sample (Ian 2022: peak 155 mph, landfall labelled); router on sample
  narrations; rung escalation (graphics hard-fail -> capcut pending -> headline; ship beat -> simulation; capcut off -> headline);
  CapCut with the API down falls through. **Not tested:** NOAA live fetch (no network here), VectCutAPI draft fields against
  your installed version, the computer-use Export, any full pipeline run.
- **Activation checklist:** (1) `"ladder_v2": true` -> run a smoke test. (2) Optional CapCut: `pip install pyautogui` (not in requirements.txt on purpose), start
  VectCutAPI, set `capcut_api_dir`, `"capcut_fallback": true`; first run with CapCut open and watch it. (3) Optional AIS:
  `pip install websocket-client`, `aisstream_api_key` (free at aisstream.io; stored in the vault).

## Action beats animated first + airline liveries (2026-10-13)
**Action coherence (ladder v2, Shorts and explainers).** `physics.action(sec, text)` -> (verb, module): a physical action verb
(descend / dive / plunge / drop / climb / take off / crash / sink / implode / explode / swerve / roll / bank / capsize / collide ...)
in THE SLOT'S OWN narration (`physics.slot_text`, slot i of n ~ the i-th n-th of the words; explainers: `render.vo_slice`) ->
module: aircraft_flight (aircraft + action), submarine_descent (sub + depth / sink), weather_event (storm words: a track is motion
by itself), ship_route (vessel + voyage words), else None. Attempts / hypotheticals don't count ("tried to crash", "nearly sank",
"could explode"); "feet" / "altitude" talk without an action verb doesn't either.
  - Shorts: an action beat skips the real-photo rung and the WanGP still ("action beat (descended): a still photo can't show it");
    in `_v2_rungs` the matching module runs FIRST (before graphics), once per beat; other slots go graphics -> illustration
    (animated: the aircraft at the verb's attitude) -> headline. No module -> graphics / animated illustration, never a still.
  - Explainers: B-roll skips the Ken Burns photo for an action shot; stills / motion treat an action visual like a WanGP-locked one;
    `v2_after_wangp` runs the module first.
  - Rung 6 (physics after graphics) now also uses the slot's action, not the whole beat: whole-beat matching ("tried to crash the
    jet") had put the flydubai simulation over "...scrambled F-35s" (caught in the sandbox test before shipping).
  - aircraft_flight fixes: a descent with no stated end altitude no longer defaults to 0 ft (it looked like a crash); spelled-out
    altitudes ("fifteen thousand feet") parse without a model; take-off starts / crash ends at 0 only when the narration says so.
  - Sim.tsx aircraft_flight: side-view airliner riding the altitude curve (nose follows the curve, pitch capped at 28 deg) + an
    altimeter dial (hundreds / thousands / ten-thousands needles + drum) driven by the simulated altitude every frame.
**Airline liveries.** `studio/liveries.py`: one entry per airline (body, belly, cheatline, tail colours + tail design: solid / split
/ band / arc / flag, engines, winglets), matched by name in narration + subject. flydubai: white body, blue belly, orange cheatline,
tail split blue / orange, orange engines and winglets; also Emirates, Qatar, El Al, Ryanair, easyJet, Lufthansa, United, American,
Delta, Southwest, Turkish, Air India (colour / tail approximations, no logos or text). `physics.fill` attaches it to aircraft_flight;
flat illustrations of an airliner wear it too (`illustrate.options`). No airline named -> the generic airliner.
`remotion/src/Aircraft.tsx` (LiveryAirliner) draws it for both. Add an airline: one entry in AIRLINES.

## Audience, script length gate, timeline scrubber (2026-10-13)
**Audience (per job, both Shorts and explainers).** Job form "Audience" (next to Narration): Settings default / Common / Informed /
Expert -> state `audience`; global default `"audience": "common"` in settings.json. The only pipeline change is one line in the
narration prompts (`writer.AUDIENCE`, `audience_line(cfg)`): explainer SECTION prompt, Short prompt, and the length pass's RESIZE prompt
(so a trimmed / expanded section keeps the register). Choices: the line goes in as `AUDIENCE: ...` after the narration-style rules; the
outline, notes and fact-check prompts are unchanged; an unknown value falls back to Common.

**Script length (explainers).** Diagnosis: the section prompt asked for 1.25x the section budget but only checked a floor (85%), so
DeepSeek landed either near the inflated number (3-min test: 551 of ~465 words, +18%) or under the floor three times, after which an
UNCHECKED fresh call was kept (15-min: 1,870 of 2,325, -20%); nothing checked the total, and the fact-check pass could change length
freely. Shorts didn't have this (two-sided +/-5%, closest try kept, middle beats dropped) and landed +1%.
Fix (picked: measure and correct, the Short's pattern; not a looser target, which would only move the miss):
  1. sections ask for the real budget, checked two-sided (+/-10%, `LEN_LO`/`LEN_HI`); after 3 misses the CLOSEST try is kept.
  2. `writer.fit_length`: after all sections, while the total is more than 6% off (`TOTAL_TOL`), the section furthest from its own
     budget in the helpful direction is rewritten to its budget from its own points (RESIZE, +/-8%, closest kept, never made worse;
     each section at most once). Visual counts follow (extra visuals dropped when a section shrinks).
  3. fact-check must keep each section within +/-10% of its length, else that section's check is skipped (original kept).
  Log lines: `length: section N a -> b words (budget c); script now x of y` and a final `length: ... within 6%` or `... off`.
  Sandbox-tested with a fake model (20% short -> within 6% in 8 calls; 18% long -> +4.5%; a model that never complies -> unchanged + warning).
  Not changed: the word target still uses settings `wpm` (155; Kokoro measured ~150 on the overnight explainer).
  Not tested on the PC yet: the next real explainer is the test.

**Timeline scrubber (job page, any finished job).** Panel above the edit bar: Video selector Short / Explainer (uses `edit/target`;
the other button is disabled when the job has only one), range scrubber, a beat strip under it (click a beat to jump; title / end
cards dimmed), timestamp m:ss.s / total, the beat at that time (`edit/beats` start+dur), Play, Stop, "Edit this beat" -> `edOpen(beat)`
(the existing panel: chat, candidates, splice, undo). Choices: Stop = pause and keep the position (rewinding would lose the beat);
"Edit this beat" is enabled only when stopped on an editable beat; the old "Edit at" button and "Jump to beat" list stay. Tested in a
headless browser against mocked endpoints (seek, play, stop, edit -> right beat id, segment click, Short <-> Explainer).

## Explainer B-roll under ladder v2: no 3D reconstruction (2026-10-13)
- **Why:** overnight job 20261013_002153 (v2 on) still got 18 reconstructions in the explainer: B-roll (`footage.long_broll`) gives
  subject-locked shots real photos, else `coherence.recon` - 12 of them the generic "object" scene (an icosahedron on a pedestal
  labelled RTL-SDR / HURRICANE RACHEL / FLOCK SAFETY ALPR CAMERA), and s5 replayed the same 3 clips 8 times. v2 had removed
  reconstruction from Shorts and explainer stills/motion, not from B-roll.
- **Fix:** with `ladder_v2`, a locked shot with no real photo goes to `render.v2_after_wangp` (graphics -> physics -> illustration /
  silhouette -> headline card) instead of a reconstruction, with `render.vo_slice()` - the words its slot plays over (visual i of n
  ~ the i-th n-th of the section, +6 words context) - so each visual gets its own graphic, not n copies of one for the section.
  Marked `v["v2"]`; `do_motion` skips decided visuals. v1 unchanged.

## Aircraft type in illustrations (2026-10-13)
- **Why:** smoke job 20261012_192051, beat b1 ("...tried to crash the jet. Netanyahu scrambled F-35 fighters...") drew a diving
  passenger jet over the F-35 line. Chain: `photo -> illustration (WanGP skipped: aircraft beat)`. Graphics (rung 5) runs once per beat
  and was spent on slot 1 (`template:stat`, "2 pilots"); slot 2 fell to rung 9, and the illustration rung only knew one aircraft
  (the beat subject, flydubai 737) and drew `<Airliner>` with the whole beat's verb ("crash" -> dive). Not a classifier or render failure.
- **Fix:** `illustrate.aircraft_for(sec, pos)`: a beat can name two aircraft; slot i of n draws the aircraft named in the i-th n-th of
  the narration (a fighter mention there wins; "the jet" / "the plane" = the beat's subject). Plural -> a pair; a scramble /
  launch / intercept clause -> climb with afterburner. Illustration `g.aircraft` = "airliner" | "fighter", `g.count`;
  Illustration.tsx has a flat generic `Fighter` (twin tails, canopy, side intake, no markings). Silhouettes follow the same type.
  The review menu (`illustrate.variants`) offers each aircraft the beat names. Explainers: each visual's own narration picks it.
- Test clip: b1 slot 2 re-rendered -> pair of fighters climbing on burner, 8 s, 1080x1920.

## Status and policy (2026-10-09) — read first
- **Project closed 2026-10-09** (no tuning; only blockers get fixed), **reopened once 2026-10-10** for cloud stills (commissioned by Tariq).
- **The pipeline is a draft generator.** Expect 2-5 beats per video to be wrong. The **timeline editor** (post-render editing, below)
  is the repair path: swap the visual for something about the actual story. Pipeline tuning is stopped.
- **Visual ladder per beat, in order (reordered 2026-10-11: illustrations before WanGP):**
  1. Stock footage (generic beats: Pexels / Pixabay / NASA; long videos also Internet Archive films) or real photos (subject beats:
     Openverse, Wikimedia Commons, Internet Archive) - short_stock / photos
  2. Cloud still (+ parallax) - `cloud_providers` is empty, so this rung is skipped
  3. **Flat Remotion illustration** (ILLUSTRATION), then **silhouette** (SILHOUETTE) - `illustrate.options`
  4. Beat graphics / map (charts, stats, quotes, maps already play over whatever background the beat gets)
  5. **WanGP still (+ parallax)** - only for atmospheric filler no illustration covers (storm clouds, abstract skies, horizons);
     **never** for aircraft, vehicles, specific buildings or real people (`illustrate.wangp_lock`). WanGP image-to-video only on
     an explicit click.
  6. 3D reconstruction / claymation (subject beats), else headline card
- **Why (Tariq, 2026-10-11):** WanGP keeps hallucinating aircraft anatomy (four wings, wrong engines, wrong attitude, wrong type /
  livery) and the vision check doesn't catch it. A plane drawn in code can't grow a fourth wing; flat illustration reads as a
  design choice, broken photorealism as a mistake.
- **WanGP lock rule** (`illustrate.wangp_lock`, keyword rules): aircraft = the subject is an aircraft, or the narration or still
  prompt names a plane / jet / airliner / helicopter / drone / fighter / model (737, A320, F-35 ...) or cockpit, or the beat is in
  the air / landing / at an airport; vehicles = car, truck, bus, train, ship, boat, tank ...; specific buildings = White House,
  Kremlin, parliament, embassy, palace, cathedral, mosque, stadium, tower, bridge ...; real people = a person subject or the
  narration names a person from the story's entity list. Locked beats with no illustration get claymation (subject beats) or
  the headline card - never WanGP. The chain shows it: `photo -> illustration  (WanGP skipped: aircraft beat)`.
- **Long videos** (`render.illustration_still`): each AI still / motion visual tries cloud, then a 16:9 illustration rendered by
  Remotion into `stills/<id>.jpg` (label drawn in; Ken Burns animates it); a locked visual with no illustration gets a headline
  card still; only the rest go to WanGP. Expect the same few scenes to repeat in a 15-minute video - swap them in the editor.
- **Motion policy (decided 2026-10-09; since 2026-10-11 aircraft never reach WanGP, so this applies only to real photos and old jobs):**
  rotation applies first (directional beats). Then:
  - **Aircraft / single compact subjects -> rigid 2-layer parallax** (subject moves as one piece; tested on job 20261009_131330
    Beat 1, tail stayed attached). **Fallback:** if tearing returns on a real job, switch these to hold-with-zoom (one-line change
    in `depth.layers`: return only the full-frame layer when `subject_mask` finds a subject).
  - **Atmosphere** (clouds, skies, cityscapes, radar, distant buildings) **-> 3-layer parallax.**
- **Known limitations:** parallax on compact subjects tore before the 2-layer split (fixed; fallback above if it returns);
  wrong-airline, wrong-aircraft, wrong-action and wrong-moment visuals (e.g. a four-engine Turkish Airlines jet taxiing for a flydubai
  descent) are expected and can't be fixed by tuning - fix them in the timeline editor.
- **Length check:** after every render the video is compared with the requested length (Short: plan target_secs / short_secs;
  long: minutes). More than 10% off -> "WARNING: length miss" in the log and a red "Length miss" line on the job page. Never rejects.
- **Live and ready:** Internet Archive source, cloud-still rung (no provider configured), debugger, timeline editor (post-render editing), `/make` front-end, ui-blackbox tester (MCP in Claude Desktop,
  venv F:\code\ui-blackbox\.venv, reports in F:\code\ui-blackbox\reports), smoke mode.
- **Deprecated:** `/api/smoke` (old fixed one-beat job). Only the form's smoke mode is supported.

## Bug batch from job 20261011_082753 (2026-10-11)
- **Copyright (Part 1):** the rendered explainer and Short were checked frame by frame (end card at 812-828 s, the whole
  explainer every 12 s, the Short every 5 s): **no YouTube thumbnails, platform screenshots or channel logos are in the files**.
  The end card is "Thanks for watching" + the source credit only. Three video thumbnails at the end are what a YouTube /
  browser player shows after a video ends, not part of the MP4. Still added: a copyright check in every vision prompt
  (stock: "platform" field -> reject "screen capture / thumbnail / channel watermark"; real photos: screen captures count as
  watermark; AI stills: screenshots / thumbnails / TV logos count as marks).
- **Explainer renderer (Parts 2-4, 6):** `explainer.py` renders the long video with the Short's Remotion `Teaser` composition at
  1920x1080 (config `long_renderer`: remotion, default; the old ffmpeg stitcher `assemble.py` is used only when the presenter PIP
  is on). One timeline from the narration: section = 0.4 s + narration wav + 0.8 s, video length = the sum (never a fixed
  target, never trimmed); word times from faster-whisper (as the Short) drive the same karaoke `Captions` (spoken word lights
  up); the end card is its own 5 s beat AFTER the narration with no captions; SRT and chapters from the same timeline.
  - Root cause of the 39 s frozen frame (8:36-9:15): section s7's file had 838 of 1,965 frames - the Windows ffmpeg pass that
    burns in emoji overlays + ASS captions dropped frames, after the section had been stitched from clips of mixed colour range
    (the new illustration clips were full-range yuvj420p). Illustration clips are now converted to limited range, and the new
    renderer doesn't stitch or burn in at all.
  - Root cause of the end card during narration: the old layout put `_end` into the last section's visual slots.
  - Root cause of the "freezing" highlight: the old explainer captions had ONE static highlighted keyword per sentence, no
    word-by-word highlight at all.
- **Guaranteed visual (Part 5):** a missing file, a blank image (no variance, or mean luma < 8) or a black clip (< 6) becomes a
  branded card (animated gradient + text, HeadlineBackdrop, now laid out for 16:9 too), never black. Root cause of the black beats:
  the script AI put Short-style `hook` cards into the long plan; the chart renderer didn't know that kind and silently drew an EMPTY
  dark image (5 charts in job 20261011_082753). Hook cards now render as big-text slides. A simulation on a Short beat replaces
  the beat's own graphic cards (they collided).
- **Explainer render time:** about 29 min for a 14-min explainer on this PC (the old stitcher took ~5 min). Verified on job
  20261011_082753 -> output/_TEST_explainer_remotion.mp4 (your original explainer file was not touched).
- **Captions (Part 7):** at native resolution both formats measured sharp; renders now use JPEG quality 100 (explainer) and the
  captions render with antialiased font smoothing at final size; the explainer uses Montserrat ExtraBold (as the Short) instead of
  libass Arial with a soft shadow.
- **Emoji (Part 8):** the picker asked for "about half, never two in a row" (and the explainer's ffmpeg overlay path dropped some);
  now "about three in four, never the same twice in a row", drawn by Remotion above the caption in BOTH formats (Short: in the free
  part of the caption's time next to the graphic cards; a beat covered by cards end to end gets none).
- **Airplanes in an AI explainer:** `coherence.phase` reads "taking off" as flight, so non-aviation beats got sky scenes and the
  aircraft lock. Flight phases and the sky / airport / radar scenes now apply only when the narration or prompt names an aircraft.
- **UI (Parts 9-12):** thumbnails get a content-keyed `?v=` (candidate ids c1, c2 ... are reused when options are rebuilt, so the
  browser showed cached images); previews have controls + speed buttons (0.25x-2x); Make video stays disabled and Stop video
  visible while a job is running, queued, paused or awaiting review / visuals (Stop cancels those at once); the job page shows one
  line per output: `Short: ✓ Finished <file>` / `Explainer: Working — narration · Section 7 of 12`.
- **Pause chat (Part 13):** the panel chat now appears at every pause (debug pause, awaiting visuals), per beat, and remembers that
  beat's conversation (last 6 turns go to the model). Clear instructions run through DeepSeek (refine, more stock, use options,
  skip, continue, simulate); judgment calls are answered as "goes to Claude" with a **Copy for Claude** button holding a
  ready-to-paste context (beat, narration, ladder, options, conversation). There is no way to call Claude Desktop without an API
  key, so the hand-off is a paste. Backend shown on every message.
- **Simulations (Part 14):** `physics.py` registry, one interface (params -> time series), rendered by `Sim.tsx` (animated profile,
  subject riding the curve, live readout, event marks; label SIMULATION). Built: `aircraft_flight` (cruise -> smooth descent /
  climb -> level-off from the narration's altitudes / time / rate) and `submarine_descent` (depth vs time, p = rho*g*h). Registered,
  not built: vehicle_crash, structural_collapse, earthquake, ship_route, weather_event (they return nothing -> the beat keeps its
  illustration). Real data sources (OpenSky ADS-B, pyBADA, pycrash, PyBullet, libcomcat, neptune-ais, NOAA) are not wired:
  installing new packages on the PC was blocked earlier this week, and OpenSky history needs an account.
- **Overlap rule (2026-10-11, `short._resolve_overlaps`):** one text layer per screen zone. A background that carries its own text
  (headline card, simulation, map with a title) owns the middle of the frame while it is on screen: a graphic card (stat / hook /
  quote ...) that would play over it is dropped and logged ("b0: dropped the hook card at 0.3s - it would cover text already on the
  background"), and emoji keep out of that time. Narration captions have their own zone at the bottom and always stay. Found in
  smoke job 20261011_183723 (hook card over the simulation title); verified by re-rendering that job. The 16:9 simulation readout
  moved to the top so it never meets the explainer's captions.
- **Map (Part 15 Q2):** the map backdrop takes any list of points (`{name, lat, lon, role}`), it is not hard-coded to Dubai-Tabuk.

## Make video / Stop video (2026-10-11)
- **Make video** is disabled while any job is running or queued, with "● Job running: <title>" next to it (the page polls every
  5 s; the button also locks the moment it's clicked, so a double click can't queue two jobs).
- **Stop video** appears next to it while a job runs (the job page's Stop does the same). It is a graceful stop: it requests a
  pause and the job stops at the next safe point - before a stage, between AI stills / checks, after a beat - never inside a
  render or a generation (so a Short render or a WanGP still in progress finishes first). Everything done so far stays on disk;
  the job ends as `stopped` with `cancelled: true` (shown as "cancelled" in the job list) and Resume continues from there.
  A queued / paused / awaiting-visuals job is cancelled at once. The old immediate stop is still the debugger's Abort.
- API: `POST /api/jobs/<id>/stop` -> `{"state": "stopping" | "stopped"}`; `studio.cancel_job`.

## Illustrations and silhouettes (2026-10-11) — app/studio/illustrate.py, remotion/src/Illustration.tsx
- **Where:** the Short ladder rung after the WanGP still (+ parallax) and before claymation (3D reconstruction) / headline card.
  When the WanGP still fails its check, or WanGP fails / isn't running, the beat gets a flat Remotion illustration or silhouette
  instead of claymation. Claymation now fires only when nothing can be drawn for the beat. Pure SVG: CPU only, no model,
  renders in seconds. Labels in the video: **ILLUSTRATION** / **SILHOUETTE** (same yellow tag as GENERATED).
- **Templates** (`Illustration.tsx`, work in 9:16 and 16:9):
  - `illustration` scenes: `sky` (flat airliner in flight, nose by the narration: down 16° / up 12° / level, drifting clouds,
    sun, ground band), `airport` (runway in perspective, terminal, tower, edge lights; airliner landing or on the ground),
    `city` (two-layer skyline with lit windows and a domed government building), `radar` (sweeping scope, blips; a falling
    trail for a descent), `cockpit` (windscreen frames, banking sky, instrument panels, two crew silhouettes from behind, red
    warning light when the narration has alarm/fight/hijack words), `sea` (waves and a ship). Time of day from the narration +
    still prompt: day / dusk (default) / night / storm (lightning flashes); ground desert / green.
  - `silhouette`: airliner (with gear when landing / on the ground), fighter jet (military subject or F-35/fighter words),
    person, people (3 figures), buildings, car, ship - in black against a sky gradient with a large sun/moon disc; optional
    text = the beat's headline backdrop text.
- **Motion (2026-10-11):** every illustration / silhouette moves: layer parallax (sky 0.1-0.15, clouds 0.3-0.45, ground /
  skyline 0.6-0.8, subject 1.1-1.2 of a 3.5%-of-width camera drift, the same idea as the AI-still parallax) inside a slow 1.09 ->
  1.15 zoom, plus drifting clouds, the aircraft travelling along its attitude, blinking lights, radar sweep. Long videos get
  them as animated 6 s clips (`motion/<id>.mp4`, CRF 16), not Ken Burns stills.
- **Attitude / pose from the narration verb** (`illustrate.attitude` / `pose`): dive (descend, dive, dropped, fell, plunged,
  plummeted, lost altitude, crash ...) -> nose 24° down and sinking; climb (climb, ascend, rose, took off, soar) -> 15° up and
  rising; bank (bank, turn, veer, circle, divert) -> side view squashed (wings toward the camera) with a slight roll; else level;
  without a verb, landing / ground from the phase. The verb beats the phase, and a dive / climb / bank puts the sky scene first
  (never a runway). Silhouette aircraft use the same poses. Cars: `moving` (drive, speed, race, chase, flee ...) drive across
  with speed lines, else parked; people: `moving` (run, walk, flee, rush, evacuate ...) walk with a bob, else stand.
  Buildings have no pose.
- **Selection** (`illustrate.options`, keyword rules, no AI call): scenes from narration words (radar / cockpit / airport /
  sea / city), aircraft beats get `sky` (in the air) or `airport` (landing, ground); in the air never a runway. Then a
  silhouette when a shape is known. A beat with several failed slots cycles through the options. No options (abstract
  narration, nothing to draw) -> claymation for subject beats, headline card otherwise.
- **Review / editor:** every illustration and silhouette that fits a beat is offered as a candidate (rung "Illustration" /
  "Silhouette", real thumbnails rendered with Remotion). Debugger: `treatment == illustration|silhouette`; chains.json and the
  trace show `... -> still -> illustration`.
- **"Data viz / text card" rung:** not a new template - a beat's own charts / stats / quote graphics already play over whatever
  background it gets, and the headline card is the text card (last rung).
- **Long videos:** unchanged (their stills come from stock / WanGP with re-rolls; there is no claymation there to replace).

## Cloud stills (rev. 2, 2026-10-10) — app/studio/cloudgen.py, app/studio/archive.py
- **Gemini / ChatGPT removed** (Tariq, 2026-10-10: automated login trips Google's verification and risks suspension of the whole
  Google account; same class of risk for ChatGPT). Gone: browser profile, login button + endpoints, login detection, skip logic,
  failure screenshots, `cloud_primary / cloud_browser / cloud_headless / cloud_profile`. The old profile folder on F: was moved to
  `F:\code\video-studio\_to_delete\cloud_profile_20261010` (delete it when convenient; it holds no logins).
- **The cloud rung stays, provider-neutral:** `cloudgen.PROVIDERS` = {name: fn(prompt, aspect, timeout) -> image bytes}; config
  `cloud_providers` lists the ones to use, in order (first image wins). Each attempt runs with a hard `cloud_timeout` (60 s); any
  failure falls through to the next, then WanGP. Everything else from rev. 1 is unchanged: skip for beats naming a real person,
  vision check (a failed cloud still goes to WanGP and stays in the review panel ✗), GENERATED · CLOUD label, cap 8 per video
  (`cloud_max_per_job`), `short/fallback/cloud_<beat>_<slot>.png`, long videos 16:9 with the label burned in, chains/debugger.
- **Providers in the rev. 2 spec, and why none is wired in yet (`cloud_providers` = [] -> straight to WanGP, as before):**
  - **Goblin AI** (`goblin-ai` 2.0.0): declined. All its logic ships only as compiled binaries (.pyd/.so, "runtime protection"),
    licence "Proprietary", one release, and it depends on Camoufox (an anti-detection browser) and curl_cffi (browser TLS
    fingerprint spoofing) - i.e. it gets "unlimited free" images by evading some other service's bot detection. Can't be
    reviewed before running on the PC, and evading bot detection is a line Claude doesn't cross.
  - **Veida** (`veida` 0.1.0): source reviewed (110 lines, stdlib only, calls veida.ai). Not installed: installing new third-party
    packages on the PC was blocked by the session's safety check. Also note: the client makes a fresh anonymous id per call
    because each anonymous caller only gets one image - it works around the per-caller allowance (the per-IP cap of ~7/day still
    applies) - and free images are watermarked, which the vision check rejects as "text/logo". Wiring it is ~15 lines in
    `PROVIDERS` if you decide it's acceptable (install `veida==0.1.0` yourself).
  - **URVILLAIN Imagine** (urvillain.ai): the site didn't load from this PC's browser pane (navigation failed), and there's no
    API to check; no selectors could be written or tested. Not wired.
  - **Grok Automata** (Chrome extension): needs your Grok account signed in, a visible Grok tab and a manually installed extension
    - the same account-automation risk as Gemini, and nothing the pipeline can drive. Not wired. For hand-picked images, the
    review panel / timeline editor already take "your own file" (path or URL).
- **Internet Archive (new free source, archive.py):** public HTTP API (advancedsearch + metadata) with `requests` - no package,
  no login. Licence rule: only items whose `licenseurl` is creativecommons.org/publicdomain/... (CC0 or Public Domain Mark),
  re-checked on the item itself; anything else (no licence, "no known copyright", NC/ND, CC BY) is skipped. 60 s budget per
  search; on any failure it returns nothing.
  - **Films** (stock rung, `footage.search_slot`): Prelinger Archives first, then any public-domain film; one query per visual;
    **long videos only** - archive films are SD and a 9:16 crop is too soft for a Short (portrait would need >= 1920 px files).
    Ranked and vision-checked like Pexels/Pixabay; contact sheet from the item's thumbnails. Description credit:
    "Archival footage: Internet Archive (public domain)."
  - **Photos** (real-photo rung, `photos.find`): after Openverse and Commons when they give fewer than 6 candidates; same checks;
    credit "Public domain" / "CC0" (no attribution is legally required; the credit line is kept as a courtesy).
  - Not tested against the live API from here (archive.org isn't reachable from Claude's shells); the parser was tested on
    canned replies, and the smoke test runs it on the PC.

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
- Smoke test: see "Smoke mode" below. The old `POST /api/smoke` one-beat job (fixed script, no script AI) is **deprecated and removed**:
  the endpoint now returns 410.

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
- **This is the only smoke path.** Settings -> "Run smoke test (30-second Short)" posts `/api/jobs {"mode":"smoke"}` (no source -> `smoke_source`).
  `/api/smoke` is deprecated (410). A "Smoke_test_visual_review_short.mp4" / 1-beat 12 s job came from the old path, not a length bug.
- Measured 2026-10-08: job 20261008_190501, 33.0 s output, ~18 min end to end (about 15 min of it WanGP stills).

## Short length accuracy (fixed 2026-10-08)
- Cause of 2:04 vs 2:20: scripts were sized at 142 wpm; the narrator really reads ~155 wpm (16 jobs, 146-165), plus a loose +/-12% word check.
- Now: voice_wpm 155; words sized from target minus pauses, tail and the closing line; check +/-5%; after 3 misses the closest try is kept
  (not an unchecked re-ask); >10% long -> drop middle beats; the fact-check can lengthen the script, so it is cut again after (>6%).
- Render: if the narration is more than 3 s off plan["target_secs"], the pace is nudged up to +/-7% (atempo; beat timings scale with it).
- Verified: 2:20 job 20261008_201028 narration 138.5 s (stopped after narration); smoke 20261008_202035 37 s -> 35.0 s via the pace step.

## Debugger (2026-10-08) — studio/debug.py
- Off by default. New video form → "Debug (breakpoints)": Debug mode + breakpoints, one per line:
  `beat == N`, `treatment == stock|photo|still|animate|parallax|3d|card`, `stock_found == N` (also < > <= >=),
  `escalated_past == stock|photo|still|animate`, `narration contains "word"`. Checked once per beat after its visuals are decided.
- With breakpoints on, short_fallback runs beats one at a time (same seeds); normal runs stay batched.
- "Pause now" (any running job): pauses at the next safe point (before a stage; between AI stills/checks; after a beat). Status "paused",
  survives restarts; Continue = resume (caches mean nothing is redone).
- Shared pause panel (#dbp): label (manual / breakpoint / uncertain), "Debug mode for the rest of this run" switch, Continue / Skip step /
  Abort / Generate thumbnails, breakpoints (add, remove, disable all), inspector (chain + reasons from short/fallback/chains.json),
  the beat's treatment card (Use selected = override, supply your own), panel chat.
- Panel chat (DeepSeek, else local): refine / more_stock (no animation) / use options / thumbnails / skip / continue; why-questions get an
  answer from the log + "For deeper reasoning, ask in the Claude chat."
- Trace: job/trace.jsonl + job/trace.md (per-beat chain, decisions, timeline incl. debug on/off, chat). Claude reads trace.md here.
- Rejected real photos: photos/<subject>.rejected.json with reason + preview (small ones are kept as <id>_small.jpg).
- Smoke-tested 2026-10-08: job 20261008_210038 (manual pause, stock_found == 0 at Beat 1, chat use + why, debug off, auto pause → debug on, finished 31.1 s).

## AI stills and aircraft attitude (2026-10-09)
- Tested: the nose-up/down of a WanGP still is fixed by the seed, not the prompt or step count (4/8/12 steps x 3 seeds: 1 of 3 dives
  every time); rotating the still afterwards fails (the vision model's pitch reads are fixed answers; 35 deg only reaches level; seams).
- So (2026-10-09 pm): a subject beat whose narration moves the aircraft (`coherence.attitude_rotation`) gets its AI still turned by
  the verb - 35 deg nose-down for descend/dive/fell/plummet, 0 for climb, 20 for bank (nose side from a blind vision look) - cropped
  to fill, then Remotion parallax. The attitude check is ignored for these; only "garbled" rejects. Tested: 50 deg overshoots.
- "Hold" rung: a still rejected only for lettering/logo is held with a slow zoom (single layer) instead of claymation.
- Parallax is wired: it fires whenever an AI still passes the check (2 of the last 10 jobs before this); the drift is gentle (front layer 80 px).
- Parallax split (depth.layers, 2026-10-09): one dominant subject clear of the bottom edge (>= 0.5% of the frame, e.g. an aircraft)
  -> 2 layers: background with the subject painted out + the subject as ONE rigid layer (fixed the tail tearing off in job
  20261009_131330 Beat 1). Everything else (skies, skylines, landscapes) -> the 3 depth layers as before.
- Six-slot prompt / negative prompt / description-based check: branch wip/six-slot-image-prompts (not live).

## Editor chat (post-render, 2026-10-11)
The pause chat is wired into the timeline editor of a finished job: opening a beat shows "Chat about this beat" (same UI, same
DeepSeek routing, same actions: why / Copy for Claude, refine, more_stock, use option N, simulate, skip -> headline card).
- `debug.chat(..., edit=True)` runs against the editor workspace (`edit.workspace`: the job for Shorts, job/longedit for long
  videos) from the saved job state on disk - nothing is reloaded into the pipeline. "continue" is replaced by **apply**.
- Candidates land in the beat's review entry and are selected in the editor (`ent.select` -> `ED.sel`); nothing touches the
  video until the user approves ("apply it" in the chat, or the Apply to video button).
- apply = `edit.start_apply`: re-renders only that beat and splices it in (Shorts: stream-copy splice on beat keyframes; long:
  BeatClip -> that section -> sections joined), with the usual verify record and undo (`output/*.prev`).
- Endpoints: `POST /api/jobs/<jid>/edit/chat {beat,text}` (409 while any job renders), `GET /api/jobs/<jid>/edit/chat?beat=`.
- Smoke-tested on 20261011_192216 b1: "simulate the descent... lost about 12,000 feet" -> SIMULATION candidate; "apply it" ->
  splice verified (decode ok, 982 frames, audio identical); frames before/after checked, other beats unchanged.

## Branch feat/kokoro-clips-postedit (2026-10-11): Kokoro narration, your own clips, post-render editing v2
Not merged to main and not active. Every feature sits behind a config flag whose default is the old behaviour; with the
defaults this branch behaves exactly like main (checked: the pause-chat prompt is byte-identical, Short edit + undo unchanged).

| Flag (settings.json)  | Default  | Turns on |
|-----------------------|----------|----------|
| `tts_engine`          | `kokoro` | narration engine (kokoro | wanGP); per job: the form's Narration choice |
| `tts_fallback`        | true     | Kokoro unavailable or failing -> WanGP narrates that job instead of stopping |
| `kokoro_voice`        | `am_michael` | any Kokoro preset voice (af_heart, am_fenrir, bm_george, ...) |
| `kokoro_speed` / `kokoro_wpm` | 1.0 / 140 | Kokoro pace; `kokoro_wpm` sizes Shorts (140 = am_michael measured 2026-10-12) |
| `kokoro_online` | false | false = the worker runs offline (HF_HUB_OFFLINE=1; the model is cached) |
| `kokoro_python` / `kokoro_device` | "" | Kokoro env python (default app/kenv) / cuda or cpu (default: cuda when available) |
| `own_clips`           | false    | "Provide clips" on the job form + the clip-to-beat matcher |
| `post_edit_v2`        | false    | explainer slot editing, Short/Explainer switch, open job by ID, multi-step undo, chat context + supply/card actions |

### 1. Kokoro TTS (studio/tts.py, app/kokoro_worker.py, pinokio/install_kokoro.js)
- Runs in its own env (app/kenv): Kokoro needs PyTorch, which Video Studio's env doesn't have; installing it there could shift
  numpy etc. under the running app. Video Studio calls `kenv python kokoro_worker.py request.json` once per job (model loads
  once) and converts each 24 kHz WAV to 48 kHz stereo, the same format WanGP narration is normalised to, so word timings,
  batch splitting, captions and mixing are untouched. Short: every narration batch in one call. Explainer: every chunk.
- With Kokoro, narration doesn't need WanGP (`_need_tts`), and on Shorts it still runs beside the footage search.
- No voice cloning (preset voices only). WanGP stays the default and is still there for the cloned voice.
- Activate: (1) copy pinokio/install_kokoro.js and pinokio/pinokio.js into C:\pinokio\api\video-studio (the menu gets
  "Install Kokoro narration (optional)"), run it: creates app/kenv, installs torch (CUDA 12.8 build, ~3 GB), kokoro>=0.9.2,
  soundfile, and warms the model with one sentence. espeak-ng comes with Kokoro's English front end (espeakng-loader ships
  the library), so no separate OS install is expected; if the warm-up complains about espeak, install espeak-ng for Windows.
  (2) set `"tts_engine": "kokoro"`. (3) smoke-test, then measure the real pace and set `kokoro_wpm`.
- Tested here with a stand-in model only (sandbox has no GPU / Hugging Face access): worker contract, 48 kHz stereo output,
  caching, missing-env error. The kokoro 0.9.4 API (KPipeline(lang_code, device), results yielding audio) was checked
  against its source.

### 2. Clip-to-beat matcher (studio/clips.py)
- Job form (when `own_clips` is on): "Provide clips" = upload video files and/or paths on this PC, plus an optional note.
  Clips are numbered in the order given (uploads, then paths); stored in src/clips/, listed in state `my_clips`.
- The script is written from the text source as before. Then: each clip is probed and described once by the vet vision
  model (4 frames -> one sentence; cached in src/clips/clips.json).
- Matching (src/clips/match.json): a structured note ("clip1=beat3, clip2=beat5,6", "clip 2 -> 4-5", "section" works for
  explainers) is taken literally; a free-text note or none goes to the script AI (DeepSeek, local model without a key) with
  the beats, the clip descriptions and the note; with no AI reachable, word overlap between each clip's description / file
  name / its own part of the note and the narration. A clip can cover several beats in a row (successive parts).
- Shorts: covered beats get their part cut to 1080x1920 as short/stock/clips/own<N>_<beat>.mp4 and go into pick.json like
  vetted stock (own=True): stock search skips them, the ladder fills only what the clip doesn't cover, no ILLUSTRATIVE
  label, review rung "Your footage", the review panel lists "Your footage: beats ... · Generated visuals: beats ...".
- Explainers: before the B-roll search, the covered section's AI still/motion slots get successive parts (1920x1080,
  broll/own/, stock_src "yours"), so they are never searched or generated.
- Timeline editor: every clip of the job is a one-click "Your footage" candidate on every beat (cut once into <ws>/own/);
  the jump list and the bar show which beats use your footage. The assembler / splice needed no change: your clips are
  ordinary footage files to them.
- Tested here on synthetic clips: note parsing, AI-unavailable fallback, Short cuts (sizes/lengths), explainer slot
  placement, editor candidates.

### 3. Post-render editing chat on any finished job (studio/edit.py, debug.py, server.py, index.html)
The editor chat itself (pause chat in the timeline editor, "apply it" = re-render that beat and splice) is already on
main. This branch adds, behind `post_edit_v2`:
- Remotion explainers are editable. They have no build/sec_*.mp4, so on main the editor finds no beats for them. Each visual
  slot of build/public/teaser.json is a beat (id <section>_<slot>); apply renders that slot's frame range of the Teaser
  composition and splices it in between keyframes on the slot boundaries (first edit of an explainer: one keyframe
  re-encode of the whole file, then only the slot is encoded). The edit is kept for a full re-render (plan visual
  `edit_bgs`/`edit_slot`, read by explainer.build). Old FFmpeg-stitched explainers keep the old section-rebuild path.
- Jobs with a Short AND an explainer: "Editing: Short | Explainer" switch on the editor bar (state `edit_target`).
- "Open a job by ID" box on the job list.
- Undo is a stack (edit/history/NNN: the old frames of the range, the timeline JSON, the beat's review state, the plan
  entry). Each Undo restores the newest edit exactly (checked frame-by-frame); repeat to go back further. Without the flag
  the stack keeps only the last edit (one-step undo, as before). A full re-render clears the stack.
- Chat: full context for the beat (Short: previous/next beat; explainer: section title and narration), plus "supply" (your
  file path or URL -> candidate, selected) and "card" (a headline card with your words). Rewriting the narration itself
  isn't offered post-render (it shifts every later beat; needs a new render); the chat says so and offers a card.
- Tested here on a rendered test explainer (slot edit: only that slot's 72 frames changed, audio identical; second edit
  with your clip; undo twice restored each step exactly) and a rendered test Short (unchanged behaviour, undo exact).

### Activation checklist (when you decide)
1. Merge the branch (or check it out on F:), restart Video Studio when no job is running.
2. Kokoro: run install_kokoro.js, then `"tts_engine": "kokoro"`. Smoke test. Measure and set `kokoro_wpm`.
3. Clips: `"own_clips": true` (form section appears). 4. Editor v2: `"post_edit_v2": true`.
Always on in this branch (not behind a flag): if no chat model is reachable, the chat replies with that instead of a
server error.


## Kokoro install completed — ready to activate (2026-10-12, overnight)
Installed on the PC; nothing activated. Video Studio was not restarted, its env (app/env) was not touched, no job was running
(the Blyb1D927pM job, 20261011_200632, had already finished at ~22:34). Flags unchanged: tts_engine=wanGP, own_clips=false,
post_edit_v2=false. main unchanged; F:\code\video-studio still has main's code (F: is a plain copy, not a git checkout).

What is installed (F:\code\video-studio\app\kenv, Python 3.10.20 from Pinokio's miniforge):
- torch 2.11.0+cu128 (CUDA 12.8; arch list includes sm_120, the RTX 5060 Ti is detected, capability 12.0)
- kokoro 0.9.4, misaki 0.9.4, soundfile 0.14.0, spaCy + en_core_web_sm 3.8.0, transformers 5.19.0
- espeak-ng: bundled by espeakng-loader 0.2.4 (kenv\lib\site-packages\espeakng_loader\espeak-ng.dll). No OS install was
  needed and none was done.
- Kokoro-82M model + am_michael voice cached in C:\pinokio\api\video-studio\cache\HF_HOME (downloaded by the warm-up, "kokoro ok").
- Installed by C:\pinokio\api\video-studio\install_kokoro.js (same as the branch's pinokio/install_kokoro.js). Also
  left there: kokoro_smoke.js/.py, kokoro_bench.js/.py, kokoro_worker_branch.py (test helpers; safe to move to _to_delete).

Smoke test (the branch's kokoro_worker.py in kenv; report + audio in F:\videos\video_studio\kokoro_smoke\):
- CPU and GPU both: return code 0, 24 kHz, 10.75 s for a 25-word sentence, RMS 0.039, peak 0.43, no NaN.
  Per call ~11-13 s wall time, almost all of it start-up (model load ~9 s + a Hugging Face check).
- Steady state on the GPU (bench_report.json): 72 s of narration in 1.1-3.0 s (24-65x real time), offline.
  So a Short's narration is ~10-15 s per job, an explainer's ~15-40 s (one worker call per job, model loads once).
- Pace: am_michael at speed 1.0 = 139.5-139.7 wpm (the cloned WanGP voice is ~155). kokoro_wpm default set to 140.
- Not checked by ear: listen to smoke_cuda.wav / bench_cuda.wav before switching.

Branch changes from the install (committed on feat/kokoro-clips-postedit): the worker runs offline by default
(HF_HUB_OFFLINE=1, kokoro_online=false) and names repo_id; kokoro_wpm default 140 (measured).

### Activation (your step)
1. Wait until no job is running (status "current": null).
2. Put the branch's code on F: (F: is not a git checkout, so copy; your settings.json, .env, env/ and kenv/ stay):
   ```
   git clone -b feat/kokoro-clips-postedit https://github.com/tariq424/video-studio F:\code\vs-branch
   robocopy F:\code\vs-branch\app F:\code\video-studio\app /E /XD env kenv __pycache__
   robocopy F:\code\vs-branch\pinokio C:\pinokio\api\video-studio pinokio.js install_kokoro.js
   copy /Y F:\code\vs-branch\WORKFLOW_HANDOFF.md F:\code\video-studio\
   ```
   (or ask Claude: "activate the Kokoro branch" - same copy, with the usual md5 check against main first)
3. In F:\code\video-studio\settings.json add:  `"tts_engine": "kokoro"`
   (optional later: `"own_clips": true`, `"post_edit_v2": true`; leave `kokoro_voice` = am_michael unless you prefer another)
4. Restart Video Studio from Pinokio (Stop / Start). 5. Smoke test (30-second Short).

### Morning checklist
- [ ] Listen to F:\videos\video_studio\kokoro_smoke\bench_cuda.wav (am_michael). Other voices: af_heart (best-rated,
      female), am_fenrir, am_puck (US male), bm_george, bm_fable (UK male); set kokoro_voice.
- [ ] No job running -> copy the branch to F: (step 2) -> set tts_engine -> restart.
- [ ] Smoke test: log should show "Kokoro (am_michael) rendered ...s of narration in ...s"; narration stage ~15 s.
- [ ] Check the Short's length lands near target (sized with kokoro_wpm 140); adjust kokoro_wpm if it's off.
- [ ] Back out any time: "tts_engine": "wanGP" and restart.

### Warnings / gotchas
- Kokoro is a preset voice, not your cloned narrator: Shorts and explainers will sound different from earlier videos.
- Slower than the cloned voice (140 vs ~155 wpm): same script = longer video; Short sizing accounts for it via kokoro_wpm.
  kokoro_speed 1.1 would bring it close to 155 if you prefer the old pace (then set kokoro_wpm ~154).
- Offline by default: the model sits in the app's Pinokio HF cache, C:\pinokio\api\video-studio\cache\HF_HOME
  (HF_HOME=./cache/HF_HOME in the app's ENVIRONMENT; Video Studio started from Pinokio passes it to the worker). If that
  cache is cleared, or Video Studio is started outside Pinokio (start-video-studio.bat, HF_HOME not set), the worker can't
  find the model offline -> set "kokoro_online": true (downloads ~330 MB once) or re-run install_kokoro.js.
- Only the am_michael voice file is cached. Another kokoro_voice needs one online run: set "kokoro_online": true for that
  job (the voice, ~0.5 MB, downloads), then back to false.
- First call per job loads the model (~9 s) and uses ~0.5-1 GB VRAM alongside WanGP; fine on 16 GB.
- Benign warnings in the worker output (LSTM dropout, weight_norm deprecation) - ignore.
- The Pinokio menu entry for the installer only appears once pinokio.js from the branch is copied (step 2).

## Never-pause mode (2026-10-12, branch) - "decide everything myself"
Visuals mode `never` (job form: "Decide everything: never pause, make the best call when unsure"; selected by default; config
`visual_review_default: "never"` for jobs that don't say, e.g. API / smoke / /make). At the visual review step, a beat the
pipeline is unsure about no longer stops the job: it keeps the pipeline's own pick (the ladder's best surviving treatment), or
the beat's headline card when nothing usable was found, logs "bN: unsure (...) - decided on my own: ...", and leaves the
reason on the beat (review panel / editor show it) so you can change it afterwards in the timeline editor.
Still stops (these are your explicit choices or real failures, not uncertainty): "Review every beat" mode, unticked "Skip
script review", pause_on_questions (off by default), debugger breakpoints / Pause now, and errors (e.g. WanGP not running).
Back to the old behaviour: pick "Auto" on the form, or `"visual_review_default": "auto"`.

## Merged to main + Kokoro default (2026-10-12)
- feat/kokoro-clips-postedit merged into main (fast-forward). F:\code\video-studio synced; settings.json: tts_engine kokoro,
  own_clips true, post_edit_v2 true (backup of the old settings: _to_delete\settings_before_merge_20261012.json).
- Kokoro is the default narration (config default tts_engine = "kokoro"). Fallback: tts_fallback (default true) - if the
  Kokoro env is missing or the worker fails, that job narrates with WanGP instead (logged "falling back to WanGP"); if WanGP
  isn't running either, the job stops with a clear message. Per job, the form's "Narration" select picks Kokoro or the WanGP
  cloned voice (state tts_engine). Whole app back to WanGP: "tts_engine": "wanGP" in settings.json.
- Smoke tests on the PC after the merge (2026-10-12, all passed):
  1. 20261012_010803 standard smoke Short, Kokoro + never-pause: narration 30 s in 14 s, Short 33 s (+8%), no pause.
  2. 20261012_011640 / 20261012_011745 pasted text + your clips: vision descriptions; unrelated clips correctly left out;
     wing + cockpit clips placed by DeepSeek (beat 1 cockpit, beat 2 wing), "Your footage" flags in the editor. Note: the
     pasted-text Short came out 42 s for a 30 s smoke target (script writer overshoot, not Kokoro).
  3. Short editor chat: "put a card ..." -> "apply it" -> splice verified -> Undo restored the original clip.
  4. 20261012_020000 (copy of the Blyb1D927pM explainer, test only): 102 slots editable; chat card + apply on slot s0_4,
     neighbours and captions untouched; undo exact (23,700 frames, audio same).
- Fixes found by the smoke tests: job state.json written atomically + reads retry (an editor thread read a half-written
  file); forced keyframes now half a frame early (times like 29.566667 rounded past the boundary frame, so every explainer
  splice fell back to a full re-encode: 9.7 min -> 2.5 min per edit; keyframe stamp v2 redoes old ones once); the clip
  matcher keeps DeepSeek's "nothing fits" instead of falling back to word matching.
- Seen, not fixed: in the Blyb1D927pM explainer a branded text card (slot s0_4) carries a SILHOUETTE label.
