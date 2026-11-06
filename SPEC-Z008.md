# SPEC-Z008 — Media Routes POC generation-step fixes, round 2
Published 2026-11-04 by Koda. Executor: ZCode (Tariq, 2026-11-04: "pause
dsh for now, just work with ZCode" — the dsh takeover question is decided
only after the POC works). Helper job D143 publishes this file to Git.
Scope (Tariq, 2026-11-04 19:29 EST): fix ONLY r4 ChatGPT, r8 Flow, r5 Bing,
r11 Blender, r1 Cloudflare. All other routes stay DORMANT (no code work,
no runs spent on them): r9 WanGP, r10 Marble, r2 HF. In the acceptance
RUN ALL those dormant routes are EXPECTED to fail with their existing
blockers — that does not fail this spec; they stay on the radar for a
future round.
Media Routes POC — generation-step fixes, round 2
Repo: tariq424/video-studio-test, branch poc/media-routes
File in scope: media-poc/routes.py ONLY (plus output evidence files). No Video Studio files.


CONTEXT (verified Nov 3–4)
Z007 proved sign-in on all 5 browser sites. Meta image+video work end to end.
The remaining routes fail at the generation step, not at sign-in.
Tariq's decisions below (2026-11-04) govern this spec.


§A — r4 ChatGPT: LONGER POLL, NOT A FIXED 180s CUT-OFF (Tariq)
Tariq's hypothesis: generation/render may simply take longer than the current wait,
so the download step ran before the image was ready.
Current code: wait_for_selector(img, timeout=180000) once, then one download attempt.
Change to: poll in a loop for up to 480s — every ~15s check for a generated image;
when one appears, try the download; if the download returns nothing, KEEP POLLING
(image may still be rendering / src may still be a placeholder) instead of failing
on the first empty attempt. Log each poll (elapsed, img count) into card_note.
Fail only after the full window with no downloadable image; keep the gen-fail
screenshot path. Note for the executor: the current download uses plain
requests.get on the img src, outside the browser — if a poll finds the image but
requests still returns nothing, try fetching the bytes inside the browser
context (page.evaluate fetch / screenshot of the img element) before failing.


§B — r8 Flow: FIND THE REAL COMPOSER (D140 evidence IN HAND, 2026-11-04)
D140-flow-debug (helper, read-only, ran 2026-11-04) screenshot + DOM inventory:
on the Flow landing page (https://flow.google.com/) there is NO visible
textarea / input / contenteditable / role=textbox — only one hidden 0x0
textarea. There IS a visible "add / New project" button (x=544 y=536
w=192 h=128, text "add\nNew project"); body text includes "New project".
Conclusion: the composer is NOT on the landing page — it appears only after
starting/opening a project. That is why Z007's r8 found no box.
Current code picks the first visible "textarea" or "[contenteditable='true']" —
too generic, and it never does the project step.
Change to: click "New project" first, then hunt for the composer on the
resulting screen (inventory that screen's textareas / contenteditables /
iframes the same way D140 did, and build the selector from what is actually
there). If the composer still cannot be found after New project, screenshot
that screen to output/ and fail with a blocker quoting what WAS found.
Keep the 480s generation wait after a successful submit.


§B2 — r5 Bing: LONGER POLL FOR THE RESULTS GRID (added 2026-11-04, Tariq)
Z007 state: profile reads signed_in (the wrong-folder sign-in bug was fixed
in Z007), Create/Generate was clicked, but no results grid appeared within
the 180s wait. No fix has been tried for this generation step yet.
Change to: same pattern as §A — poll for the results grid / generated images
for up to 480s, checking ~every 15s, logging each poll (elapsed, grid/image
count) into card_note; when images appear, download the first one >20,000
bytes. Fail only after the full window, with the gen-fail screenshot kept.


§C/§D — DORMANT (Tariq, 2026-11-04 19:29 EST): r10 Marble and r9 WanGP are
OUT of this spec. No code changes, no start/stop wiring, no attempts spent on
them in the acceptance run. They stay in the route list as-is and simply
report their existing blockers. (Earlier same-day directions — Marble
fail-and-fall-through, WanGP on-demand load/unload — are parked with them
and revive only on Tariq's word.)


§E — r11 Blender: USE THE DESCRIPTION + PHOTOREAL MATERIALS (Tariq + code fact)
Code fact (Koda, verified in routes.py 2026-11-04): r11 currently IGNORES the
description entirely — BLENDER_SCRIPT builds one fixed low-poly jet (cylinder +
cube wings, flat diffuse_color only, no node materials, no textures) and orbits a
camera around it. That is why the output looks blank/crude. Blender MCP was NOT
used (direct blender.exe -b -P script; MCP route was verified in S12, never
installed).
Change to:
 1. Pass the description into the script (argv) and build the scene FROM it at the
    simple level this POC can honestly do (subject primitives chosen by keyword
    class is acceptable IF the RESULT notes say so plainly — no pretending it is
    a general scene builder).
 2. Materials via nodes: every material use_nodes=True with a Principled BSDF
    (set base color, roughness, metallic properly) — the photoreal-material step
    Tariq flagged — plus a real world: HDRI-style sky via Sky Texture / gradient
    world nodes, a key SUN + fill, and ground with roughness variation.
 3. Keep the camera-orbit render, 1280x720, 24fps, ~4s, and the Z006 camera fix.
Acceptance for §E is a visibly non-blank, lit, shaded scene — Tariq judges it.


§F — r1 Cloudflare: SMALL CODE FIX (facts updated 2026-11-04 evening)
Setup is DONE: helper job D141 wrote media-poc/secrets/cloudflare.env from
Tariq's wrangler login (in-process, token never logged). D142 then proved
the direct Workers AI call: HTTP 200, real FLUX image saved
(output/r1_cloudflare_test2.png, 700,757 bytes). The token is accepted.
The remaining r1 problem is in the POC's own code: it sends width/height
fields, and FLUX-1-schnell REJECTS them — HTTP 400, AiError code 5006
("Additional or unevaluated properties '/width, /height' not allowed").
Change to: drop width/height from the r1 request body (prompt + steps
only, as in the proven D142 call). Then prove the ROUTE end to end through
the POC (POST /api/run/r1) and capture the raw status/body in the RESULT —
both D141 and D142 route probes came back empty/incomplete, so the route
itself is still unproven until this run.
r2 HF: DORMANT (Tariq, 2026-11-04 19:29 EST) — no code change, no PRO
purchase. Facts on record if revived: free ZeroGPU 5 min/day; PRO $9/month
= 40 min/day; Cloudflare free gives ~170 images/day of the same model.


ACCEPTANCE (all)
- Selfcheck PASS, 11 routes, only routes.py changed.
- One RUN ALL with per-route evidence in card_note.
- r4: poll log shows the loop ran; outcome is either a downloaded image or a
  blocker that states the full window elapsed.
- r8: "New project" clicked first; composer found on the post-click screen
  (named selector/frame in the note), or a blocker quoting what that screen
  actually contains.
- r5: poll log shows the loop ran up to 480s; outcome is either a downloaded
  image or a blocker stating the full window elapsed.
- r1: route run through the POC returns ok with a saved image (not just the
  direct API) — raw status/body quoted in the RESULT.
- r11: output mp4 is a lit, shaded, non-blank scene; RESULT states how the
  description was used.
- Dormant routes (r2, r9, r10): no code changed, no attempts beyond the
  standard RUN ALL listing of their existing blockers.
- Z008-RESULT.md on poc/media-routes with the code commits.


PICKUP NOTE
Pickup: Tariq types "Pull latest and run SPEC-Z008.md" into ZCode (the
standing wake stop stands — no helper wake is queued). Result channel is
Git only: commits + Z008-RESULT.md at the repo root of poc/media-routes.
