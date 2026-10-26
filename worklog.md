<!-- QC STATUS (frame QC recalibration job; keep this block at the top, update at every commit) -->
## QC STATUS

- **Job:** frame QC recalibration. Apply the prepared patch, then run the report-mode smoke test. Nothing gets enabled in this job.
- **Steps done:**
  - Round 1: steps 1 (apply v2, bc521cd), 2 (smoke specimens, 36271ea) and 3 (run, 2dc347b; B FAIL).
  - Round 2: step 4 (apply v3, 1980d64) and step 5 (re-run, report mode; FAIL, 9acc260/4727f5f).
  - Round 3: step 6, part 1 (apply v4, 83ee757) and part 2 (run; FAIL; fb8e8b2).
  - Since 2026-10-26 3:55 PM the loop runs through the Claude-Koda exchange doc (Google Doc 1GV6ZvXQJwyyiNfy1ZM1FT22Jo-xGKCPpW5FAgQIViE4). Tariq overrode the stop rule: no round cap; it runs until a full PASS or a genuine WALL.
  - Round 4: v5 applied (2e2cee6); run 3:59-4:12 PM; FAIL (6c25cd5).
  - Round 5: v6 applied (8010bd3); run 4:25-4:32 PM. Everything PASS except the upside-down segment (4967fe3).
  - Round 6: v7 applied (MSG 004); run started 4:48 PM.
- **Next step (exact):** round 6 run (started 4:48 PM).
  1. Collect results into `qc_smoke_results/round6/`.
  2. Post the RESULT in the exchange doc.
  3. Wait for MSG 005.
- **Flags, unchanged in every commit:**
  - `qc_on` = False. Code default; set nowhere in `config.py`, `settings.json` or any job cfg.
  - `interview_qc` = False. Code default; set nowhere.
  - `qc_mode`: set nowhere, so the patched code defaults to "report".
- **Round 6 setup (MSG 004):**
  - qc_v7.py from Drive (id 1YZELkOs1lXQ3wWjWhsqDjoC6r-J2b2CD): 28,887 bytes, SHA-256 `1e0a785d...98d6`, `QCVER = 7`.
  - v6 was backed up to `F:\code\patches\qc_v6.py`. v7 applied; hash matches; compiles.
  - The round-5 qc.json files were moved to `_to_delete\round5_qcjson`.
- **Round 5 verdict (v6, single-image upright tests): FAIL on 1 criterion only.**
  - Results: `qc_smoke_results/round5/`.
  - **A zero hard flags: PASS.**
    - `would_fix` is empty; `qc_final` 0/6.
    - 115 s: sideways via orient (asis:no;180:no;90ccw:yes). It was single, ignored and not rescued.
    - 145 s: asis:no and every rotation no, so nothing was flagged.
  - **B sideways 10-20 s caught as sideways: PASS.** 13 s and 19 s: asis:no;180:no;90ccw:yes. `qc_part` span 9.5-22.5 s, sideways.
  - **B upside down 30-40 s caught as upside_down: FAIL.** 31 s and 37 s: asis:yes, a yes-bias on the upside-down frames.
  - **B black: PASS.** 55 s via pixel, rescued; span 51.5-58.5 s.
  - **B nothing else hard: PASS.** `would_fix` holds only the sideways and black spans.
  - **B blur soft only: PASS.** 73 and 79 s are blurry/blurry soft. Orient answered no to as-is and to every rotation, so it flagged nothing.
  - **Complete: PASS.** 0/30 and 0/6 unchecked for both specimens.

- **Round 5 setup (MSG 003):**
  - qc_v6.py from Drive (id 1sXfmWFBuszwf0RvSxjt0GSWXbmlLvyhG): 24,661 bytes, SHA-256 `37cb34c2...72d4`, `QCVER = 6`.
  - v5 was backed up to `F:\code\patches\qc_v5.py`. v6 applied; hash matches; compiles.
  - The round-4 qc.json files were moved to `_to_delete\round4_qcjson`.
- **Round 4 verdict (v5, report mode, specimens unchanged): FAIL.**
  - Results: `qc_smoke_results/round4/`.
  - **Pairwise orientation has a "right" bias:**
    - Every checked sample of A (29/29) and of B (29/29) took an orientation flag.
    - 180:right answers: 22/29 on A, 23/29 on B. 90ccw:right: 7 on A, 6 on B.
    - The 90cw pair was never even reached.
  - **A zero hard flags: FAIL.** Every sample is flagged upside_down or sideways via orient. `qc_final` flags 6/6. 109 s was unchecked (vision error).
  - **B sideways caught as sideways: FAIL.** 13 s and 19 s answered 180:right, so they were labelled upside_down.
  - **B upside down caught as upside_down: label correct, but not meaningful.** 31 s and 37 s answered 180:right, exactly as A's upright frames did.
  - **B black caught: PASS.** 55 s via pixel.
  - **B nothing else hard-flagged: FAIL.** Everything is flagged.
  - **B blur soft only: FAIL as reported.** 73 and 79 s are blurry/blurry by the model, but orient overrode them to hard flags (73 s upside_down, 79 s sideways).
  - **Status complete: PASS.** A 1/30 unchecked, B 0/30; both 0/6 in `qc_final`.
  - The finger fix worked: no confirmed finger on either specimen. First looks still said finger at A 115 s and B 13, 25 and 115 s, but every confirm said none.

- **Round 4 setup (2026-10-26, from MSG 002 in the exchange doc):**
  - qc.py v5 came from Drive (`qc_v5.py`, id 10wvOhwheH3YI6FE5_aI3EEvAvP5H44Nd). It is 22,880 bytes, has SHA-256 `8683fcfa413029913ba5b0f991b1ec071072ea6443a7164192931ce74abb4a78` and contains `QCVER = 5`.
  - v4 was backed up to `F:\code\patches\qc_v4.py`. v5 is applied on F: and in the repo; hash matched, compiles.
  - The round-3 `*.qc.json` files were moved to `qc_smoke\_to_delete\round3_qcjson\`. The specimens are unchanged.
- **Step 6, part 2: round 3 run (2026-10-26, 15:00-15:05 local, v4, report mode, same specimens):**
  - `qc.available` was True (`qwen2.5vl:7b`). Specimen SHA-256s are unchanged after the run.
  - Results are in `qc_smoke_results/round3/`:
    - sheets and json for both specimens;
    - `A_round3_finger_flags.png`: A's frames hard-flagged as finger;
    - `B_round3_orient_strips.jpg`: the rotate-and-compare strips the model saw for B at 13, 19 and 31 s. In each strip the upright panel is plain to see: panel 3 at 13 and 19 s, panel 2 at 31 s.
- **Round 3 verdict:**
  - **A: zero hard-fault flags. FAIL.**
    - Hard faults: `qc_part` would cover 9.5-16.5 s and 57.5-70.5 s as finger.
      - 13 s: finger/finger, via model, rescued by its probe.
      - 61 and 67 s: finger/finger, via model.
    - `qc_final` flags 2 s as finger (finger/finger, via model, rescued).
    - These frames show hands typing on a keyboard or pointing at a screen, not a finger over the lens.
    - Orientation (via orient) put **no** flag on A.
    - Soft flags: blurry at 1, 25, 169 and 175 s; face_closeup at 43 and 121 s.
  - **B: sideways 10-20 s caught as sideways. FAIL.**
    - 13 s and 19 s: first "sideways", confirm "none", via model. The rotate-and-compare check ran and returned no flag.
  - **B: upside down 30-40 s caught as upside_down. FAIL.**
    - 31 s: first "finger", confirm "none", via model. Rotate-and-compare ran and returned no flag.
    - 37 s: first "face_closeup", confirm "face_closeup", via model. That is a confirmed soft flag, and because the frame was already judged bad, rotate-and-compare never ran on it.
  - **B: black 50-60 s caught. PASS.**
    - 55 s: black, via pixel (flat-black test), rescued by its probe. The right label.
  - **B: nothing else hard-flagged. FAIL.**
    - Finger, via model: 61 and 67 s (persistent) and 127 s (rescued). The `qc_part` spans are 51.5-70.5 s (black plus finger) and 123.5-130.5 s.
    - 115 s finger was single and ignored.
  - **B: blur reported as soft, not hard. PASS.** 73 and 79 s were blurry/blurry, via model, soft.
  - **Both: status complete. PASS.** Unchecked is 0% for both: 0/30 in `qc_part` and 0/6 in `qc_final`.
  - **Overall round 3: FAIL. Stop rule triggered:** A took hard flags, and B's rotation faults were not caught with the right labels. Under the agreed rule this is reported as **"orientation is not judgeable by this local model"**, a scope decision for Tariq, with no further prompt tweaks.
- **Facts for the decision:**
  - The pixel black test works.
  - Orientation via orient produced zero false flags on A, but also zero catches on B, even with clearly upright panels in the strip.
  - The report does not record the orientation answer itself (panel 1, "none", or a parse failure), only that no flag came back.
  - A frame with a confirmed soft flag skips the orientation check.
  - The remaining hard false positives on A are now "finger", via model.
- **Step 6, part 1 verified (2026-10-26, round 3; task from the Koda handoff doc, CURRENT MESSAGE "STEP 6"):**
  - qc.py v4 came from Tariq's Google Drive (`qc_v4.py`, id 1mGVZok5J5w44ertXszMc1chUhyRbJKNA). The muse.ai link is blocked by this session's network allowlist.
  - It is 19,284 bytes, has SHA-256 `69a550ea2b303006abff5909e26d657cc6057530e1a2b897d204b5cb66682600` and contains `QCVER = 4`. Saved as `F:\code\patches\qc.py`.
  - The v3 file that was applied was backed up to `F:\code\patches\qc_v3.py` (SHA-256 `572c7f29...e4c6`).
  - v4 was copied over `app/studio/qc.py` on F: and in the repo. The SHA-256 matches and py_compile is OK. No other code file was changed.
  - The round-2 `*.qc.json` files were moved to `F:\code\patches\qc_smoke\_to_delete\round2_qcjson\`. The specimens were not rebuilt; their SHA-256s are unchanged.
- **Step 5, round 2 run (2026-10-26, 12:54-12:58 local, v3, report mode, same specimens, not rebuilt):**
  - The old `specimen_A.qc.json` and `specimen_B.qc.json` were moved to `F:\code\patches\qc_smoke\_to_delete\round1_qcjson\`, since rm isn't permitted from my side, so every frame was judged fresh.
  - `qc.available` was True at 12:54:43 (`qwen2.5vl:7b`).
  - Specimen SHA-256s are unchanged after the run.
  - Results are in `qc_smoke_results/round2/`. `A_round2_false_sideways.png` shows upright frames of A that both checks called sideways.
- **Round 2 verdict:**
  - **A: zero hard-fault flags. FAIL.**
    - Hard faults: `qc_part` would cover 6 spans as "sideways": 15.5-28.5, 33.5-46.5, 51.5-70.5, 75.5-82.5, 87.5-94.5 and 123.5-178.0 s.
    - `qc_final` flags 32, 92 and 152 s as sideways. All of these frames are upright.
    - first/confirm verdicts: 24 of 30 samples came back "sideways" on the first look; 19 of those 24 confirmed. Two single-sample hard hits were ignored (103 s sideways, 115 s finger).
    - Soft flags: 85 s blurry, 121 s face_closeup.
  - **B: sideways 10-20 s caught. PASS.**
    - 13 s and 19 s were both sideways/sideways (first/confirm).
    - Caveat: A's upright frames get the same verdict, so this detection is not meaningful on its own.
  - **B: upside down 30-40 s caught as upside_down. FAIL.**
    - 31 s and 37 s were both sideways/sideways, so a hard flag, but the wrong fault.
  - **B: black 50-60 s caught. FAIL.**
    - 55 s: first "black", confirm "black", state ok, so dropped. Both stages named black, but the confirm reply evidently had `"ok": true`, which the two-agree rule treats as "not confirmed".
    - The pixel check did not fire: the frame's mean luminance is **16.0**, which is video black in limited range (Y=16), against a threshold under 6.
  - **B: nothing else hard-flagged. FAIL.**
    - Sideways spans also cover 41-52.5, 57.5-64.5, 87.5-94.5, 99.5-106.5, 123.5-148.5 and 153.5-178 s.
  - **B: blur reported as soft, not hard. PASS.** 73 and 79 s were blurry/blurry, soft.
  - **Both: status complete. PASS.** Unchecked is 0% for both: 0/30 in `qc_part` and 0/6 in `qc_final`.
  - **Overall round 2: FAIL.**
    - v3's orientation-first prompt makes `qwen2.5vl:7b` call ordinary upright frames sideways, and the strict confirmation agrees.
    - The black threshold of 6 can't catch limited-range black (16).
    - A confirm reply of "black" with `"ok": true` is discarded.
- **Step 4 verified (2026-10-26, round 2):**
  - The v3 patch `F:\code\patches\qc.py` is 15,975 bytes, has SHA-256 `572c7f299b3fee43bb4c66c0fa0d083f039be918b32826d6f47a85342ee5c4e6` and contains `QCVER = 3`.
  - The v2 file in the repo was backed up to `F:\code\patches\qc_v2.py` (SHA-256 `7d7ed591...6177`). The v1 original stays at `qc_v1_original.py`.
  - v3 was copied over `app/studio/qc.py` on F: and in the repo. The SHA-256 of both copies matches the pickup hash, and py_compile is OK. No other code file was changed.
- **Step 1 verified (2026-10-26, commit bc521cd):**
  - The patch `F:\code\patches\qc.py` is 12,311 bytes, has SHA-256 `7d7ed59145f4d6c143b174589374d6a9d2093480f4b26103f5a38381ccda6177` and contains `QCVER = 2`.
  - Original backed up to `F:\code\patches\qc_v1_original.py` (SHA-256 `9f2bc68a...93273d`).
  - The patch was copied over `app/studio/qc.py` on F: and in the repo. The SHA-256 of both copies matches, and py_compile is OK. No other code file was changed.
- **Step 2 verified (2026-10-26):**
  - **specimen_A.mp4** (164,968,649 bytes, SHA-256 `a8c53647...843dff`) is a byte-identical copy of `F:\videos\newsroom\staging\20261023_032233\output\AI_Just_Learned_to_Hack_Power_and_Water_Systems_short.mp4`.
    - Newsroom item 907bb4a591d1, "AI is getting better at hacking power, water systems...". Status: published, so approved by Tariq.
    - 178.0 s, 1080x1920, h264 + aac. The file is dated 2026-10-23, before the v1 QC run, so it was never QC-modified.
    - It is the shortest approved video of 90 s or more.
  - **specimen_B.mp4** (88,598,047 bytes, SHA-256 `5814dfbd...4cc4d7a`) was built by `F:\code\patches\qc_smoke\make_B.py` with the PC's ffmpeg 7.1. Video re-encoded with x264 veryfast crf 20; audio stream-copied.
  - **Injected faults (actual), each 10.0 s, with ffmpeg `enable='between(t,a,b)'`:**
    - 10.0-20.0 s: sideways. `transpose=1`, then refilled to 1080x1920.
    - 30.0-40.0 s: upside down. `hflip,vflip`, i.e. 180 degrees.
    - 50.0-60.0 s: black. `drawbox` fill.
    - 70.0-80.0 s: strong blur. `boxblur=20:2`.
    - Clean video between each pair of faults: 10 s.
  - **Frame grabs check the placements:** at 9/11, 19/21, 29/31, 39/41, 49/51, 59/61, 69/71 and 79/81 s, each fault is present inside its window and absent outside it. Grabs saved as `F:\code\patches\qc_smoke\grabs_B.png`.
  - **B plays end to end:** a full ffmpeg decode gives exit 0 with no errors. Duration is 178.005 s, the same as A. The audio is intact: mean -18.1 dB and max -1.5 dB, identical to A.
- **Step 3 note on sampling, worked out before the run, so not a result:**
  - `qc_videos.py` picks its spacing by file name. "specimen_*" has no "short" in it, so `qc_part` samples every 6 s at 1, 7, 13, 19, 25, ... s, and `qc_final` samples every 30 s.
  - A hard fault counts only when it appears in 2 neighbouring samples. Inside the fault windows the samples are:
    - sideways 10-20: 13 and 19;
    - upside down 30-40: 31 and 37;
    - black 50-60: **only 55**;
    - blur 70-80: 73 and 79.
  - So the black window can't meet the persistence rule unless a neighbouring sample is also flagged black.
- **Step 3 run (2026-10-26, 10:20-10:23 local, report mode):**
  - `qc.available` was True at 10:19:57; Ollama tags include `qwen2.5vl:7b`.
  - Hook `qc-smoke` ran `scripts\qc_videos.py` on `F:\code\patches\qc_smoke\list.json`, with backups in `F:\code\patches\qc_smoke\backup`.
  - SHA-256 of both specimens is unchanged after the run, so report mode modified nothing.
  - Results are in `qc_smoke_results/`:
    - `*_part_qc.json`: `qc_part`, every 6 s, 30 samples.
    - `*_final_qc.json` and `*_sheet_qc.jpg`: `qc_final`, every 30 s, 6 samples.
    - `B_fault_samples.png`: the frames QC actually saw inside the fault windows. Each one clearly shows its fault.
- **Verdict:**
  - **A: zero hard-fault flags. PASS.**
    - Hard faults: none confirmed and persistent.
    - Two single-sample hard hits were ignored: 127 s finger, 157 s sideways.
    - Soft flags: blurry at 1, 25, 169 and 175 s; face_closeup at 43 s.
    - Unchecked: 0/30 in `qc_part`, 0/6 in `qc_final`.
  - **B: injected hard faults caught. FAIL.**
    - Sideways 10-20 s: samples at 13 and 19 s show it clearly. Nothing was flagged.
    - Upside down 30-40 s: samples at 31 and 37 s. 31 s was not flagged; 37 s came back as `face_closeup` (soft), not upside_down.
    - Black 50-60 s: the only sample, 55 s, was not flagged.
  - **B: nothing else hard-flagged. PASS.** The only hard hit was the 127 s finger, single-sample and ignored, the same as in A.
  - **B: blur segment reported as soft and not counted as hard. PASS.** It was reported as blurry at 73 and 79 s.
  - **Both: QC status complete. PASS.** Unchecked is 0% for both: 0/30 in `qc_part` and 0/6 in `qc_final`.
  - **Overall: FAIL**, because none of the 3 injected hard faults was detected.
- **Gaps found:**
  - `qc_part` does not keep each sample's first-check answer, so this run can't tell whether `qwen2.5vl:7b` missed the faults on the first check or the strict confirmation dropped them.
  - `qc_final`, at a 30 s spacing with the 2-neighbouring-samples rule, can only ever confirm a hard fault that lasts about 30 s or more.
  - At a 6 s spacing, a 10 s fault holds only one sample about 1/3 of the time (the black window here), so it can never meet the persistence rule.


---

# Worklog — God's Eye View + Video Studio ladder v2

Newest entries at the top of each log. Status snapshot first.

## Status (2026-10-15)

| Item | State |
|---|---|
| God's Eye View install (`F:\code\gods-eye-view`, fork `tariq424/gods-eye-view`) | Installed, runs on pinned port 4173, hot reload works |
| GEV smoke test | Partial: flights OK (194, OpenSky), earthquakes OK (48/24h). **Ships layer and console not verified** |
| Video Studio ladder v2 | Live (`ladder_v2: true`), CapCut off. F: matches GitHub main `afc346f` |
| v2 graphics rung | Proven in real jobs |
| v2 simulations (storm / ship / altitude / sub), live NOAA fetch | **Never fired in a real job** |
| v2 Claude-written graphics | **Never needed yet** |
| v2 CapCut fallback | **Off, untested** |

## Open items / next steps
1. Video Studio 30-s smoke test on a hurricane or shipping story → exercises simulations + live NOAA.
2. GEV: verify ships layer + browser console.
3. Decide: allow a 2nd graphic per beat (different template) to cut illustration/silhouette/headline filler on extra slots.
4. Decide: AI stills (cloud/WanGP) were rejected on every checked beat in the last two jobs — fix prompts/checker or skip that rung for such stories.
5. Optional: supervised first CapCut run (needs `pip install pyautogui`, VectCutAPI running, `capcut_api_dir`, `capcut_fallback: true`).
6. Known noise: GEV adsb.lol fallback returns HTTP 420 (rate limit); main OpenSky feed works.

---

## God's Eye View log

**2026-10-15** — Reviewed state. Found Oct 12 setup log: Node check passed, fork created (`isFork: true`, parent bilawalsidhu), cloned, port patch applied and pushed, `npm ci` + `npm run doctor` OK, Vite on `http://localhost:4173`, `netstat` LISTENING on 4173. dev.log shows HMR updates (hot reload works). Screenshots: `F:\code\_gev-setup\smoke-flights.jpg`, `smoke-layers.jpg`.

**2026-10-12** — Setup.
- Port pin: `package.json` dev = `vite --port 4173 --strictPort`; `server/standalone/vite.config.js` ignores `PORT`, sets `strictPort` and `hmr: true`. Sandbox-verified: `PORT=5555` still starts on 4173; second instance fails with "Port 4173 is already in use".
- Couldn't create the GitHub repo or run Windows commands from Claude (GitHub write blocked; terminals click-only). Wrote `F:\code\_gev-setup\run-setup.cmd` / `setup.ps1` (Node check 24.14+ not 25, `gh` fork, clone, patch, `npm ci`, doctor, dev server, netstat). Tariq ran it.
- Restart later: `F:\code\_gev-setup\start-gev.cmd`.
- Out-of-box layers: flights, military, satellites, earthquakes, cameras, radio, launches, weather work without keys. Optional keys via in-app POWER UP: Cesium ion (photoreal 3D, free personal), Google Maps (metered), OpenAI (voice).

## Video Studio ladder v2 log

**2026-10-15** — Checked activation: already done by another session on Oct 14 (F: synced to `afc346f`, `ladder_v2: true`, server idle). Per-beat results from jobs 20261014_192031 and 20261014_194800: graphics fired on every beat stock didn't cover (10 of 12 templates from the beat's own data, 2 via model call); extra slots fell to illustration/silhouette/headline; no simulation, no Claude-written graphics, no CapCut; every checked AI still rejected.

**2026-10-13/14** (other sessions, from git log) — Follow-up commits on main incl. physics by slot / action beats, fighter illustration before graphics, liveries, stock-download failure handling, length policy, audience setting, Windows startup scripts.

**2026-10-12** — Built ladder v2, commit `3a1ccb5` on main, all behind flags (default off).
- New order: stock → real photos → cloud still → WanGP still (atmospheric only) → **Remotion graphics (GRAPHICS)** → **physics module (SIMULATION)** → **CapCut (CAPCUT)** → parallax → illustration/silhouette → headline. 3D reconstruction removed from v2.
- `graphics.py` + `remotion/src/Templates.tsx`: 8 templates (stat, quote, timeline, compare, route map, chart, list, abstract). Router reuses beat analysis, else one JSON call. Claude-written component fallback: import/network checks, one repair, cap 3 per video.
- `physics.py`: `weather_event` (NOAA NHC active advisories / HURDAT2 best tracks, approximate cone), `ship_route` (narration waypoints, optional live AIS via aisstream.io). vehicle_crash / structural_collapse / earthquake left as stubs. `SimMapBackdrop` in Sim.tsx.
- `capcut.py`: one CapCut session per video for beats where graphics hard-failed and no physics fit (VectCutAPI draft + computer-use Export); any failure keeps the provisional visual.
- Review, debugger, chains, handoff updated. Sandbox tests: all templates rendered both orientations, MP4 paths, HURDAT2 parser, router, escalation, CapCut fall-through.
- Answers given: CapCut server = VectCutAPI; Claude-graphics cap = 3/video, 1 repair; classifier reuses beat analysis; CapCut failure → falls through to rung 8+.
