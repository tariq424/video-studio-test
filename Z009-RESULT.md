# Z009 RESULT — Media Routes POC, round 3

**Status: DONE — §A–§F all implemented; acceptance RUN ALL: 6 routes ok (r2, r3, r5, r6, r7, r11),
r4 signed in with its first full 480 s poll run, r1 carries the two-response comparison blocker,
r8's composer driven inside the iframe.** Date: 2026-11-04/05. Branch `poc/media-routes`.
Files changed: `media-poc/routes.py` (§A/§B/§C) + `media-poc/server.py` (§E/§F — justified: §E is
explicitly a page/server change; §F's OPEN LOGIN button lives in the server's /api/login).

## §A r3 → meta-describe (DeepSeek removed from the POC)
- r3 now uses the signed-in meta.ai profile (same `_browser("meta")` pattern as r6/r7): uploads the
  input image (uploaded file or latest image-route output) through the composer's file input, sends
  the standing text ("Describe this image in detail. Then write one image-generation prompt that
  would recreate it."), waits for the streamed answer (marker-anchored, scoped to the thread's
  `<main>` region so sidebar chat history doesn't pollute it), and saves it to
  `media-poc/output/r3_meta_describe.txt`.
- **Acceptance: r3 = ok, 23.3 s** in the RUN ALL + 2 solo re-runs after the extractor hardening.
  Quoted excerpt from the saved file: *"Here's a detailed breakdown of the image you shared: … A
  head-on, low-angle view of a commercial twin-engine jet airliner on final approach, centered in
  the frame … resembling a Boeing 737 / Airbus A320 family — twin under-wing turbofan engines…"*
  (describing r2's generated image). No DeepSeek API call remains in routes.py;
  `secrets/deepseek.env` is left in place, unused. Card title is now **meta-describe**; the note
  carries "via meta.ai profile — DeepSeek removed from the POC".

## §B r8 Flow — composer driven INSIDE the frame
After "New project", the route inventories every frame and drives the editor **in its own frame**
(click + fill directly in the frame context). In the acceptance run: signed_in (Google account
avatar) → New project clicked → in-frame editor found and typed → submitted → then the honest
generation-stage blocker: **"failed at step 'no generated clip within 480s'"**
(`output/gen_flow_fail.png`). The composer problem from Z008 is fixed; what remains is Flow's clip
generation queue/timing. Card note records the frame URL the composer was driven in.

## §C r1 Cloudflare — shapes diffed; both responses quoted
- Diff vs `cf_test_D142.py` (the proven script, found in `media-poc/output/`): URL, method, and
  body keys are IDENTICAL; D142 also sent no explicit Content-Type header — r1 now matches that
  byte-for-byte (requests auto-sets it either way). No fixable difference existed.
- The route and a standalone D142-shape probe now run in the same request cycle; **both returned
  HTTP 401 code 10000 "Authentication error"** (both raw bodies quoted on the card).
- Conclusion (proven, not guessed): the env token is a **wrangler OAuth access token with a
  hours-long lifetime** — valid at 17:28 (D142's 200 + 700,757-byte image), expired by the
  evening RUN ALL, still expired now (also fails `/user/tokens/verify`). **Tariq action:** refresh
  via `wrangler login` + D141-style dump right before runs, or supply a real REST API token
  (dash → My Profile → API Tokens, Workers AI edit). No code change needed beyond what landed.

## §D r4 ChatGPT — no code change; the wall is GONE and the poll loop got its first real run
Your OPEN-LOGIN warm-up cleared the Cloudflare challenge. In the acceptance run:
**r4 = signed in OK (evidence: composer/prompt box visible; chat sidebar (New chat) present) →
prompt typed → the full 480 s poll window elapsed with no downloadable image**
(`output/gen_chatgpt_fail.png` kept; poll log in the card note). §A's loop ran end-to-end; what
missed is ChatGPT's image render/download — next-round work, unblocked by the profile warm-up.

## §E GUI honesty
`server.py` now preloads the last `smoke-report.json` into the cards at startup — the page shows
each route's last saved result (status + seconds + output) instead of "idle". No route logic touched.

## §F OPEN LOGIN rebuilt as REAL Chrome (no Playwright anywhere in the login path)
- `/api/login/{site}` launches **plain chrome.exe** with `--user-data-dir=profiles/<site>`, the
  `_repair_prefs()` clean-exit repair, `--hide-crash-restore-bubble`, and explicit on-screen
  geometry `--window-position=60,60 --window-size=1280,900`, navigated to the site home.
- Verified live: the launcher process carries all four flags with the profile's user-data-dir
  (verification window opened and closed). Root causes fixed: no more buried `-32000` restored
  position, and no more Playwright browser that Google/ChatGPT refuse sign-ins in.

## Acceptance
1. Selfcheck **PASS** (11 routes: cloudflare-flux, hf-flux, meta-describe, chatgpt-image,
   bing-image, meta-image, meta-video, flow-video, wangp, marble-video, blender-video).
2. Fresh RUN ALL + solo re-runs; per-route evidence in card notes; `smoke-report.json` refreshed.
3. r3 ok via meta.ai — description + prompt quoted above; no DeepSeek call in routes.py ✅
4. r8 composer driven inside the frame (in-frame inventory logged); blocker only at generation ✅
5. r1: the two-response comparison blocker quoted (identical shapes, both 401) ✅
6. r4: signed_in + full 480 s poll log; wall gone ✅
7. Dormant r9/r10: unchanged, standard listing (r9 unreachable; r10 world-timeout blocker) ✅
8. This RESULT + code commits on `poc/media-routes` ✅

## Outputs on disk (Tariq judges)
`r2_hf_flux.jpg` (33 KB) · `r3_meta_describe.txt` (541 B) · `r5_bing_image.jpg` (33 KB) ·
`r6_meta_image.jpg` (217 KB) · `r7_meta_video.mp4` (3.9 MB) · `r11_blender_video.mp4` (90 KB) ·
plus per-failure screenshots. Server still running at http://127.0.0.1:42054.
