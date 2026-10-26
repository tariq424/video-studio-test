<!-- QC STATUS (frame QC recalibration job; keep this block at the top, update at every commit) -->
## QC STATUS

- **Job:** frame QC recalibration. Apply the prepared patch, then run the report-mode smoke test. Nothing gets enabled in this job.
- **Steps done:** 1 (apply).
- **Next step (exact):** STEP 2. Make the smoke specimens in `F:\code\patches\qc_smoke\`.
  - `specimen_A.mp4`: a copy of the source below.
  - `specimen_B.mp4`: A with 4 injected faults, 10 s each. Then verify B plays end to end with audio.
- **Flags, unchanged in every commit:**
  - `qc_on` = False. Code default; set nowhere in `config.py`, `settings.json` or any job cfg.
  - `interview_qc` = False. Code default; set nowhere.
  - `qc_mode`: set nowhere, so the patched code defaults to "report".
- **Step 1 verified (2026-10-26):**
  - The patch `F:\code\patches\qc.py` is 12,311 bytes, has SHA-256 `7d7ed59145f4d6c143b174589374d6a9d2093480f4b26103f5a38381ccda6177` and contains `QCVER = 2`.
  - Original backed up to `F:\code\patches\qc_v1_original.py` (SHA-256 `9f2bc68a5ee0af4257fe9bb09c60364af97af30980bc486a6bbb35c646d9dd1f`).
  - The patch was copied over `app/studio/qc.py` on F: and in the repo. The SHA-256 of both copies matches the pickup hash, and py_compile is OK on both. No other code file was changed.
- **Specimen A source (chosen, copy not made yet):** `F:\newsroom\staging\20261023_032233\output\AI_Just_Learned_to_Hack_Power_and_Water_Systems_short.mp4`.
  - 178.0 s, 1080x1920. Published (approved by Tariq), item 907bb4a591d1.
  - File dated 2026-10-23, before the v1 QC run, so it was never QC-modified.
- **Injected timestamps:** none yet.
- **Verdict:** not run yet.

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
