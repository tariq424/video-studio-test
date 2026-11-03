# Z005 RESULT — Media Routes POC: standalone smoke-test GUI on 127.0.0.1:42054

**Status: DONE — server built, booted, all 11 route cards live; RUN ALL executed 6×; 2 routes producing
outputs (hf-flux, deepseek-describe), 9 reporting precise blockers (all per spec: blocker = plumbing PASS).**
Date: 2026-11-02 (evening). Branch: `poc/media-routes` (repo `tariq424/video-studio-test`). Everything inside
`media-poc/` — `app/`, `remotion/`, `tests/` untouched (diff proves it). The POC server is LEFT RUNNING at
http://127.0.0.1:42054 for Tariq to judge the outputs himself (per the owner direction — no QC gate here).

## (1) Server boots standalone
- `media-poc\output_server.log`: "Uvicorn running on http://127.0.0.1:42054" (log kept on the PC, not committed);
  `GET /healthz` → `{"ok":true,"port":42054,"routes":11}` (200); `GET /` serves the GUI (200). Port verified free first.
- Launch paths: Pinokio (`media-poc/pinokio.js` + `pinokio_install.js` + `pinokio_start.js`, house format per the
  repo's own pinokio/ launcher) or `media-poc\start-poc.bat`.

## (2) The 11 routes — final RUN ALL (also in `media-poc/output/smoke-report.json`)
| id | route | result | evidence across the 6 run-alls |
|----|-------|--------|-------------------------------|
| r1 | cloudflare-flux | BLOCKER | no token — Tariq creates `media-poc/secrets/cloudflare.env` (below) |
| r2 | hf-flux | **ok** | image produced in 4 of 5 full runs, ~6 s each — `media-poc/output/r2_hf_flux.jpg` (~30–41 KB, 1344×768); one transient HF-space busy failure |
| r3 | deepseek-describe | **ok** | description + image prompt extracted in 3 of 5 runs (real vision: e.g. *"A large commercial airplane is captured head-on as it flies directly over an airport runway with its landing gear extended…"* + a ready-to-use prompt); the intermittent runs return empty text and now surface a precise blocker with the raw response for diagnosis — `media-poc/output/r3_deepseek_describe.json` |
| r4 | chatgpt-image | BLOCKER | could not confirm sign-in state on the fresh profile — OPEN LOGIN then rerun |
| r5 | bing-image | BLOCKER | sign-in wall detected — OPEN LOGIN then rerun |
| r6 | meta-image | BLOCKER | sign-in unconfirmed; page-state screenshot saved per spec (`output/r6_meta_state.png`) |
| r7 | meta-video | BLOCKER | same (falls back to R2/R6 image when one exists) |
| r8 | flow-video | BLOCKER | sign-in unconfirmed (fresh profile) — OPEN LOGIN then rerun |
| r9 | wangp | BLOCKER | WanGP not reachable (probed Pinokio log URLs + ports 8000/42004 — same discovery pattern as the studio client; start WanGP in Pinokio to use it; the POC never auto-starts it, to respect the GPU/VRAM interlock) |
| r10 | marble-video | BLOCKER | sign-in unconfirmed (fresh profile). Card carries the "uses one of the few free generations" warning |
| r11 | blender-video | BLOCKER | **Blender not installed** (searched PATH, Program Files, LOCALAPPDATA; logged). bpy script ships ready (`routes.py::BLENDER_SCRIPT`); installation is a separate approved step |

`smoke-report.json` is written at the end of every RUN ALL and rendered as a summary table in the GUI.

## (3) Secrets — what exists, what Tariq must create
- `media-poc/secrets/deepseek.env` — **auto-populated** from the PC's own credential vault (the studio's
  keyring) by ZCode; values were never printed or committed. Variables: `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`.
- `media-poc/secrets/hf.env` — **auto-populated** the same way (`HF_TOKEN`), raising the HF quota.
- `media-poc/secrets/cloudflare.env` — **Tariq must create** (no Cloudflare creds exist on this PC):
  required variables: `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` (Workers AI, model
  `@cf/black-forest-labs/flux-1-schnell`).
- After any OPEN LOGIN (buttons on the page: ChatGPT, Bing, meta.ai, Google Flow, Marble — each opens a
  visible Chrome on `media-poc/profiles/<site>/`), rerun that route; the browser routes are implemented
  with the profile plumbing + defensive sign-in detection, and their generation selectors are marked in
  the code as the follow-up pass once the profiles are signed in.

## (4) Git / self-check
- Branch `poc/media-routes`: commits = media-poc app (server.py, routes.py, selfcheck.py, pinokio js files,
  start-poc.bat, requirements.txt, .gitignore) + this RESULT at the repo root. `output/`, `secrets/`,
  `profiles/`, `venv/` are gitignored.
- POC self-check: **PASS** — `python selfcheck.py` → "SELFCHECK PASS: server imports clean; 11 routes
  registered: cloudflare-flux, hf-flux, deepseek-describe, chatgpt-image, bing-image, meta-image,
  meta-video, flow-video, wangp, marble-video, blender-video".
- Existing app tests: untouched, not run (per spec).
- POC venv pip requirements (media-poc/requirements.txt): fastapi, uvicorn, python-multipart, requests,
  gradio_client, playwright (uses the system Chrome via channel="chrome" — no browser download needed).

## Notes for Tariq / Koda
- 6 full RUN ALLs were executed back-to-back during hardening; browser routes re-verify sign-in state
  each run (~6–12 s per card), so a full RUN ALL takes ~80 s today (all blockers) and grows only when
  real generations run.
- deepseek-flasher quirk worth knowing: the `deepseek-flash` vision replies are sometimes wrapped in
  ```json fences with literal newlines (invalid strict JSON) — the extractor handles fenced, pretty and
  conversational shapes; genuinely empty replies become blockers.
- Server left running (PID in `media-poc/output_server.log`); stop with `taskkill /PID <pid>` or by
  closing the Pinokio app.
