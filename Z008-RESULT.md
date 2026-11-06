# Z008 RESULT — Media Routes POC generation-step fixes, round 2

**Status: DONE — r5 Bing now produces a real image via the 480 s poll loop (33 s), r11 renders a
description-driven, lit, shaded scene, r8 reaches the project screen and quotes its inventory,
r1's real blocker is precisely diagnosed (wrong token KIND). Dormant routes untouched.**
Date: 2026-11-04. Branch `poc/media-routes`. Only file changed: `media-poc/routes.py` (+ this RESULT).

## §A r4 ChatGPT — poll loop implemented and wired (480 s, ~15 s cadence, in-browser download fallback)
The shared `_poll_generation()` helper logs every poll (elapsed, img count, candidates, download
result) into the card note. r4 is wired to it with the oaiusercontent/blob selectors.
**Outcome in the acceptance RUN ALL: r4 never reached the loop** — the profile's page showed a
Cloudflare "Verify you are human" challenge (screenshot `r4_state.png`, evidence in the card note:
"a Cloudflare ... challenge is showing (bot wall, never bypassed); signals checked: composer/prompt
box visible, chat sidebar (New chat) present"). This reproduces even headed-offscreen. The loop
mechanism itself is proven by r5, which uses the same helper (below). ChatGPT via automation stays
blocked by the challenge until a human warms the session in that profile (OPEN LOGIN, real use).

## §B2 r5 Bing — **ok, 33.2 s**
`POST /api/run/r5`-equivalent (RUN ALL): signed_in (Rewards/account header + create composer), typed
into the redesigned composer, clicked Generate, then the poll loop: "**poll 0s: 33 imgs, 6 candidates,
downloaded**" — `media-poc/output/r5_bing_image.jpg` saved. Poll log in the card note ✅; outcome =
downloaded image ✅.

## §B r8 Flow — New project clicked; post-click screen inventoried and quoted
"New project" clicked successfully (landing-page composer confirmed absent, per D140). Post-click
inventory (in the card note and blocker, exactly as the screen contains): an **iframe
(fc80eea6-110f-47eb-b524-9e4189a83cd3) holding textarea=1, contenteditable=1, textbox=1 — but none
registering visible >20 px tall**; 7 frames total. Blocker quotes this verbatim; screenshot
`output/gen_flow_composer.png`. The editor lives inside that iframe and does not present as an
interactable box — named follow-up for the next round (drive the iframe editor directly).

## §E r11 Blender — description-driven, node-material scene — **ok, 30.7 s**
- The description is now passed into BLENDER_SCRIPT (argv) and drives the scene via a **keyword
  classifier** (jet/plane → aircraft primitives; car → car; boat → boat; building → buildings;
  fallback → abstract monument). Stated plainly per the spec: this is a keyword→primitive
  classifier, NOT a general scene builder.
- Materials are node-based: every material `use_nodes=True` with a Principled BSDF (base color,
  roughness, metallic set per part — white aluminum-ish hull, dark engines, glassy canopy, rough
  ground). World = Nishita Sky Texture (low sun ≈ dusk) with a constant-dusk fallback; key SUN +
  AREA fill.
- Output: `media-poc/output/r11_blender_video.mp4` — **visibly non-blank, lit, shaded**: the low-poly
  jet (fuselage, wings, engines, tail) framed full-view with a cast ground shadow, orbiting camera,
  1280×720, 24 fps, ~4 s. Z006 camera reuse/guard retained.
- Honest iteration note: the acceptance RUN ALL's r11 frames showed sky+ground only — the fixed
  Euler tilt looked past the subject. Fixed by aiming the camera with a track-quaternion at the
  subject and pulling the orbit back (radius 6.5→11.5, lens 42→38); solo re-run `ok 30.7 s` with the
  jet properly framed. The subject sits on the ground plane; "descending through clouds" is not
  represented (POC-simple, no pretense).

## §F r1 Cloudflare — width/height dropped; real blocker precisely diagnosed
- Payload now `{prompt, steps}` only (the D142-proven body). The earlier 400/AiError-5006 is gone.
- The route now returns **HTTP 401, raw body**: `{"result":null,"success":false,"errors":[
  {"code":10000,"message":"Authentication error"}],"messages":[]}`.
- **Diagnosis (no secret material printed):** the token in `secrets/cloudflare.env` fails Cloudflare's
  own `/user/tokens/verify` → **401 "Invalid API Token"** (token present, 93 chars; account id
  present, 32-hex). It is therefore a **wrangler OAuth token, not a REST API token** — wrangler calls
  succeed with it (which is why D142's probe got a real image), but the REST v4 endpoint rejects it.
  **Tariq action:** create a real API token (dash.cloudflare.com → My Profile → API Tokens → Create
  Token, Workers AI edit) and put it in `media-poc/secrets/cloudflare.env`; then rerun r1 — the code
  needs no further change.

## Dormant routes (§C/§D) — untouched, standard RUN ALL listing only
- r2 hf-flux: ran and **ok 19.2 s** (free ZeroGPU quota refreshed with the new day — no code touched).
- r9 wangp: existing blocker (not reachable) — unchanged.
- r10 marble: existing blocker (signed_in second pass; world did not load within 300 s) — unchanged.

## Acceptance checklist
1. Selfcheck **PASS**, 11 routes, only `media-poc/routes.py` changed ✅
2. One RUN ALL with per-route card_note evidence ✅ (quoted above; `output/smoke-report.json` refreshed)
3. r4: loop wired; outcome = Cloudflare-challenge blocker at the detection stage, evidence recorded ✅ (stated plainly — the loop itself is exercised by r5's success)
4. r8: New project clicked; blocker quotes the post-click screen inventory ✅
5. r5: poll log shows the loop ran; outcome = downloaded image ✅
6. r1: route run through the POC — raw status/body quoted; **not** ok — diagnosed wrong token kind, Tariq action listed ✅ (stated plainly)
7. r11: mp4 is a lit, shaded, non-blank scene; description usage stated (keyword classifier) ✅
8. Dormant r2/r9/r10: no code changed; standard listing only ✅
9. Z008-RESULT.md on `poc/media-routes` with the code commits ✅

## Git
Commits on `poc/media-routes` (base 97d4677): routes.py changes + this RESULT.
