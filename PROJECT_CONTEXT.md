# Project Context — for any AI picking this up

Owner: Tariq (GitHub `tariq424`). Windows 11 PC (`tariq-i9`, i9 + RTX 5060-class GPU, 8 GB VRAM). Retired; makes YouTube videos (several channels) and runs side projects.
House rules: be direct and terse; data over optimism; **all outputs go on F:** (videos in `F:\videos`); C: is system only. "Smoke test" in Video Studio = a 30-second Short.

This file covers two **independent** projects. They share nothing (separate folders, repos, ports, Node installs' `node_modules`).
Running history: `worklog.md` (same folder). Video Studio's own deep handoff: `F:\code\video-studio\WORKFLOW_HANDOFF.md` (~700 lines; read its top sections first).

---

## 1. God's Eye View (GEV) — personal research install

**What it is:** open-source real-time geospatial dashboard (upstream `github.com/bilawalsidhu/gods-eye-view`, MIT). Photorealistic 3D globe in the browser with live aircraft (ADS-B), ships (AIS), satellites, earthquakes, public CCTV, weather/cyclones, NASA FIRMS fires, transit, plus voice control (OpenAI Realtime). For Tariq's own curiosity — **no connection to Video Studio.**

**Where:**
- Code: `F:\code\gods-eye-view` (Windows git clone). Remotes: `origin` = `github.com/tariq424/gods-eye-view` (a GitHub fork, therefore public), `upstream` = bilawalsidhu.
- URL: `http://localhost:4173` — **pinned**. Start: `F:\code\_gev-setup\start-gev.cmd` (or `npm run dev` in the repo).
- Setup scripts / logs / smoke screenshots: `F:\code\_gev-setup\` (`setup.ps1`, `setup.log`, `dev.log`, `smoke-*.jpg`).

**Architecture (upstream):**
- Frontend: Vite 6 + CesiumJS (`vite-plugin-cesium`), plain JS modules in `src/` (`src/layers/<layer>/` one module per layer, `src/app/`, `src/ui/`, `src/voice/`, `src/director/` for camera tours).
- Local backend = Vite dev-server middleware: `server/standalone/vite.config.js` → `build/vite.js` (`createBrowserViteConfig`) + `server/providers/*` (proxies/adapters for each feed: aircraft, vessels, space, cyclones, weather, wind, firms, cctv, transit, traffic, overpass, openai, …). Also an MCP server (`npm run mcp`, `server/mcp/`).
- Keys: optional, added in-app via **POWER UP** chip → saved to repo-root `.env` (gitignored). Works keyless for flights, satellites, earthquakes, cameras, radio, launches, weather. Useful free keys: **Cesium ion** (photoreal 3D + world terrain, personal non-commercial), Google Maps (metered), OpenAI (voice), NASA FIRMS, OpenSky client, TomTom.
- Node: requires 24.14+ (not 25) or 26. Uses the system Node (same install Video Studio's Remotion uses).

**Local changes vs upstream (one commit, pushed to the fork):**
- `package.json`: `"dev": "vite --port 4173 --strictPort"`.
- `server/standalone/vite.config.js`: `port: 4173` (ignores `PORT` env), `config.server.strictPort = true`, `config.server.hmr = true`. If 4173 is busy, Vite exits with "Port 4173 is already in use" instead of switching.

**Status (2026-10-15):**
- Installed, `npm ci` done, `npm run doctor` OK, runs on 4173 (netstat confirmed), hot reload confirmed (HMR updates in `dev.log`).
- Verified: Flights layer (~194 aircraft, OpenSky), Earthquakes (48/24h, USGS).
- **Not verified:** Ships layer, clean browser console.
- Known noise: adsb.lol flights fallback returns HTTP 420 (upstream rate limit); primary OpenSky works.

---

## 2. Video Studio — YouTube video generator

**What it is:** local web app that turns a YouTube link (or NotebookLM audio/notes, or a typed description via `/make`) into a narrated **Short** (vertical, up to ~3 min), a **long 16:9 explainer**, or both. Treat output as a **draft**; Tariq fixes wrong visuals in the built-in timeline editor. Copyright-strike avoidance matters (multiple channels): no source-podcast footage, honest labels on visuals.

**Where:**
- Code: `F:\code\video-studio` — **working copy, NOT a git repo**. Source of truth on GitHub: private `tariq424/video-studio` (branch `main`). Sync = copy changed files to F: and **verify md5** (a copy tool once wrote stale files). As of 2026-10-15 F: matches `main` @ `afc346f`.
- UI/API: `http://127.0.0.1:42020` (Flask). Start: Pinokio → Video Studio → Start, or `start-video-studio.bat`. `/api/status` shows `current` job (null = idle).
- Jobs/outputs: `F:\videos\video_studio\jobs\<YYYYMMDD_HHMMSS>\` (`output\` holds the MP4s).
- Settings: `F:\code\video-studio\settings.json` (non-secret overrides of `app/studio/config.py` DEFAULTS); API keys in Windows Credential Manager (vault "ExplainerStudio").

**Stack / external services:**
- Python 3 + Flask (`app/server.py`), job runner `app/studio/pipeline.py`.
- Script AI: DeepSeek (`deepseek-v4-pro`, via Anthropic-compatible API) — default provider; Claude/z.ai/local Ollama also supported. No Anthropic key is set currently.
- Local models: Ollama (`qwen2.5vl:7b` vision checks, `phi4-mini` for /make), **WanGP** in Pinokio (image/video gen, MCP), **Kokoro** TTS (default narration; WanGP voice clone as fallback).
- Rendering: **Remotion** (React/TS, `remotion/`) for Shorts and explainers; ffmpeg.
- Stock: Pexels, Pixabay, NASA, Internet Archive; real photos: Openverse, Wikimedia Commons, Internet Archive.

**Code map (`app/studio/`):**
- `pipeline.py` stages — Shorts: `transcript → short_script → review → short_stock → short_voice → short_fallback → short_review → short_render`; long: `script → charts → voice → captions → broll → presenter → motion → stills → assemble`.
- `short.py` (Short script, stock, narration, **visual ladder `do_fallback`**, timeline `build`, Remotion render), `ladder.py` (cloud/WanGP stills + vision check), `footage.py`/`photos.py`/`clips.py` (stock, real photos, user clips), `cloudgen.py` (cloud stills; no provider configured), `illustrate.py` (flat illustrations/silhouettes + `wangp_lock`), `coherence.py` (story phases, 3D recon specs), `graphics.py` (v2 Remotion graphics), `physics.py` (simulations), `capcut.py` (v2 CapCut fallback), `render.py`/`explainer.py`/`assemble.py` (long video), `review.py` (visual review menu, previews), `edit.py` (post-render timeline editor), `debug.py` (breakpoints, trace, pause/editor chat), `make.py` (`/make`), `tts.py`, `writer.py`, `config.py`.
- `remotion/src/`: `Root.tsx` (compositions Teaser, ShotPreview, BeatClip, Recon), `Background.tsx` (per-shot renderer + honesty tags), `Backdrops.tsx` (map, headline, parallax layers), `Templates.tsx` (v2 graphics), `Sim.tsx` (time-series + map simulations), `Illustration.tsx`, `Recon.tsx`, `Graphics.tsx` (overlay cards), `Captions.tsx`.
- Per-job decision record: `short/fallback/chains.json` (each beat's ladder chain), `trace.md` when debugging.

**Visual ladder v2 (live since 2026-10-14; `"ladder_v2": true`, `"capcut_fallback": false`):** for each beat, first that works wins:
1. Stock footage → 2. Real photos (subject beats, labelled FILE) → 3. Cloud still (no provider set: skipped) → 4. WanGP still, atmospheric only (never aircraft/vehicles/buildings/real people) → 5. **Remotion graphics** (GRAPHICS: 8 templates — stat, quote, timeline, compare, route map, chart, list, abstract; chosen from the script's own beat data, else one DeepSeek call; else Claude/DeepSeek writes a Remotion component, cap 3/video) → 6. **Physics simulation** (SIMULATION: aircraft altitude, submarine depth, `weather_event` from NOAA NHC/HURDAT2 with approximate cone, `ship_route` with optional live AIS; only when the subject matches) → 7. **CapCut** (CAPCUT: only if graphics hard-failed and no simulation fit; one VectCutAPI draft + computer-use Export per video; currently off) → 8. Parallax (a still the checker couldn't judge) → 9. Illustration/silhouette → 10. Headline card.
- Graphics/physics run once per beat; a beat's extra slots continue down the ladder. v2 has no 3D reconstruction.
- Labels on screen: ILLUSTRATIVE, FILE, GENERATED (· CLOUD / · PARALLAX), ILLUSTRATION, SILHOUETTE, GRAPHICS, SIMULATION, CAPCUT.

**Status (2026-10-15):**
- Recent real jobs finish end-to-end with v2. Graphics rung fires on every beat stock doesn't cover (mostly from beat data, no extra model call).
- **Never exercised in a real job:** simulations (incl. live NOAA download), Claude-written graphics, CapCut.
- Observed issues: (a) extra slots per beat fall to illustration/silhouette/headline filler; (b) AI stills (cloud/WanGP) were rejected on every checked beat in the last two jobs.
- Project policy: development was "closed" 2026-10-09 then reopened several times; Tariq commissions specific builds and treats the pipeline as a draft generator.

**Working rules for AIs on Video Studio:**
- Don't restart Video Studio while a job runs (check `/api/status`). Restart only after pushing code changes, when asked.
- New features behind flags, default off; activation is Tariq's call.
- Claude sandbox-tests static things (logic, single frames); Tariq runs full videos on the PC unless he asks otherwise.
- Commit to `main` (no branches unless asked); update `WORKFLOW_HANDOFF.md` and `worklog.md`.

---

## 3. How Claude reaches the PC (practical notes)
- Cloud session linked to the PC through the Claude desktop app. File access to `F:\code` via device tools; a Linux VM shell sees it at `~/mnt/code` (no Windows commands, can't see `.git` folders, deletes need permission).
- Computer use: File Explorer is click-only, terminals click-only, browsers view-only — Claude can't type Windows commands. Workaround used: write a `.cmd`/`.ps1` to F: and have Tariq double-click it.
- Browser: Claude in Chrome extension was unreliable (tab-group errors); the desktop app's built-in browser works and can reach `http://127.0.0.1:42020` and `http://localhost:4173` (site approval required).
- GitHub from Claude's cloud shell: read/push only to repos attached to the session; it can't create repos or forks.

## 4. Next steps (open)
1. Video Studio 30-s smoke test on a hurricane or shipping story → exercises simulations + live NOAA.
2. GEV: check Ships layer + browser console.
3. Decide: allow a 2nd graphic per beat (different template) to reduce filler.
4. Decide: fix or skip the AI-still rung (rejected on every checked beat recently).
5. Optional supervised CapCut run (`pip install pyautogui`, run VectCutAPI, set `capcut_api_dir`, `capcut_fallback: true`).
