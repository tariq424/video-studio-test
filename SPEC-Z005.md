# SPEC-Z005 — Media Routes POC: standalone smoke-test GUI (port 42054)

Owner direction (Tariq, Nov 2, 2026): Prove EVERY external media route on its own,
outside Video Studio (which is frozen). No QC / coherence gate in this POC — Tariq
judges the outputs himself. If a route runs out of credit or quota, that is a valid
POC result, not a build failure.

## Placement / independence (hard constraints)
- Repo: tariq424/video-studio-test, NEW branch `poc/media-routes` (from main).
  ALL work inside a new top-level folder `media-poc/`. Do NOT modify, import from,
  or depend on any existing file (`app/`, `remotion/`, `tests/` stay untouched).
  Reading existing files for reference (imagegen.py, marble.py, wangp.py) is fine.
- Runtime: own venv inside media-poc/, own process, own port **42054** (verify it is
  free first; if taken, report BLOCKED naming the occupant — never kill anything).
- Outputs: `media-poc/output/` (gitignored). Secrets: `media-poc/secrets/`
  (gitignored, PC-local only, never committed, never logged — not even partially).
- Pinokio: provide `media-poc/pinokio.js` + a start script so the app can be pinned
  and launched like the other studio apps. Server binds 127.0.0.1:42054.

## The app
Single-page GUI (Python; FastAPI or stdlib http.server — your choice; no Video
Studio code):
- Input row: description text area (default: "A white passenger jet with exactly two
  wings descending through clouds toward a runway at dusk, photorealistic"),
  aspect select (16:9 default, 9:16), and an image upload/picker used by the
  describe and image-to-video routes.
- A big **RUN ALL — one-button smoke test** button.
- One card per route (list below): name, what it proves, RUN button, status line
  (idle / running / ok / failed + elapsed seconds), output preview (img or video
  player), note/error text. A route that cannot run (no token, not signed in, not
  installed, out of credit) must state exactly that — a precise blocker message is a
  PASS for that card's plumbing.
- RUN ALL runs every route sequentially (browser and GPU routes serialized), then
  renders a summary table (route, result, seconds, output file, note) and writes
  `media-poc/output/smoke-report.json`.
- A "Sign-ins" panel: one OPEN LOGIN button per browser profile (opens a visible
  browser on that profile for Tariq's one-time sign-in). Profiles live in
  `media-poc/profiles/<site>/`.

## Routes — each is fn(description, aspect, ctx) -> output file | Blocker(reason)
- R1 cloudflare-flux: Cloudflare Workers AI REST, model
  `@cf/black-forest-labs/flux-1-schnell`. Account ID + API token from
  `secrets/cloudflare.env`. Output: image.
- R2 hf-flux: Hugging Face FLUX.1-schnell via gradio_client (approach per
  imagegen.py's hf provider — read for reference, do not import). Optional
  HF_TOKEN in `secrets/hf.env` raises quota. Output: image.
- R3 deepseek-describe: DeepSeek API, model `deepseek-flash` (vision). Input image
  -> description text + a ready-to-use image prompt (both shown as text on the
  card). Key from `secrets/deepseek.env`. Proves the describer leg.
- R4 chatgpt-image: browser profile (ChatGPT — Tariq's paid account, the Codex
  account). Prompt -> image. Playwright on `profiles/chatgpt`. Not signed in ->
  Blocker("sign-in needed — use OPEN LOGIN").
- R5 bing-image: browser profile (Bing Image Creator; approach per imagegen.py).
  Output: image.
- R6 meta-image: browser profile (meta.ai). Prompt -> image. NEW provider — build
  selectors defensively; on failure save a screenshot of the page state next to the
  output for diagnosis.
- R7 meta-video: browser profile (meta.ai). Take R6's image (or the uploaded /
  selected image) -> video with a slow cinematic motion prompt. Output: mp4.
- R8 flow-video: browser profile (Google Flow). Prompt -> short video. Blocker if
  not signed in.
- R9 wangp: local WanGP — still from the description, then image-to-video of that
  still, calling the same local endpoint pattern `app/studio/wangp.py` uses (read
  for reference, do not import). The incumbent baseline. WanGP unreachable ->
  Blocker("WanGP not reachable").
- R10 marble-video: World Labs Marble via browser profile (`profiles/marble`):
  type the scene prompt into "Imagine a world", wait for the world to load, record
  a slow walk-forward as frames -> encode mp4 (screenshot-recording approach per
  app/studio/marble.py — read for reference, do not import). Card must warn:
  "uses one of the few free generations".
- R11 blender-video: Blender driven by a bpy Python script: build a simple
  primitive scene evoking the description (a low-poly jet from primitives over a
  ground plane, sun + sky), camera orbit, render a 3–4 s mp4 (EEVEE, 720p fine).
  Locate blender via PATH + common install paths and log what was found. Not found
  -> Blocker("Blender not installed"). Do NOT install anything — installation is a
  separate approved step.

## Non-goals
No coherence/QC checks. No Video Studio integration. No publishing or uploading
anywhere. No account creation. No package installs beyond the POC venv's own pip
requirements (list them in the RESULT; if one cannot be installed, mark only that
route BLOCKED).

## Acceptance — all reported in Z005-RESULT.md at the repo root of this branch
1. Server boots standalone on 42054; RESULT carries log proof the page serves.
2. All 11 route cards present; each route either produced an output file (path +
   size in RESULT) or reported a precise blocker; RUN ALL produced
   smoke-report.json (attach its contents or a summary table to RESULT).
3. Routes whose secrets exist must run end-to-end. For missing secrets, RESULT
   lists exactly which files Tariq must create under media-poc/secrets/ (file
   names + required variable names — never values).
4. Commits + Z005-RESULT.md pushed to `poc/media-routes`. Existing app tests
   untouched and not run; the POC carries its own tiny self-check (server imports;
   route registry count == 11) and RESULT states its outcome.
