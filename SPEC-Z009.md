# SPEC-Z009 — Media Routes POC, round 3
Published 2026-11-04 by Koda. Executor: ZCode (dsh takeover still paused
by Tariq's order; decided after the POC works). Helper job D146
publishes this file to Git. Pickup: helper v6 wake (proven D144/D145)
types "Pull latest and run SPEC-Z009.md" — ordered by Tariq
2026-11-04 20:55 EST. Result channel is Git only: commits +
Z009-RESULT.md at the repo root of poc/media-routes.
Repo: tariq424/video-studio-test, branch poc/media-routes
Files in scope: media-poc/routes.py (§E also touches the POC page/server).
No Video Studio files.


PURPOSE (Tariq, 2026-11-04): every route proven in this POC goes LIVE
in Video Studio — the POC exists to weed out blockers first. This
spec's RESULT is part of the integration checklist for the real ladder.


CONTEXT (verified Nov 4, Z008-RESULT + D142 log)
Working: r2 HF, r5 Bing, r6 Meta image, r7 Meta video, r11 Blender.
Blocked: r4 (Cloudflare human wall), r8 (iframe editor), r1 (route 401
vs D142's proven 200), r3 (DeepSeek thinking-only replies).
Dormant by Tariq's order, unchanged in this spec: r9 WanGP, r10 Marble.


§A — r3: DROP DeepSeek; describe via Meta AI (Tariq, 2026-11-04 20:33 EST)
r3's only job is lightweight: image -> description + image prompt.
The DeepSeek API route keeps returning thinking-only replies (precise
blocker, but still a blocker). Tariq's ruling: Meta AI does this job,
the meta.ai profile already works end to end (r6/r7), and per Tariq
Meta has no hard limit for this.
Change to: r3 uses the existing signed-in meta profile (same
_browser("meta") pattern as r6). Upload the input image (the uploaded
file or the latest image-route output), send the standing text:
"Describe this image in detail. Then write one image-generation prompt
that would recreate it." Read the reply text; save description + prompt
to output (text file) and quote an excerpt in the card note.
Route id stays r3; card title becomes "meta-describe"; the card note
says "via meta.ai profile — DeepSeek removed from the POC".
Remove the DeepSeek API call from r3 entirely; secrets/deepseek.env is
no longer read by any route (leave the file in place, unused).
Acceptance: with an image present, r3 returns ok with a non-empty
description AND a prompt, both quoted in the RESULT.


§B — r8 Flow: DRIVE THE IFRAME EDITOR (Z008 named follow-up)
Z008 state: "New project" click works; the post-click screen holds the
editor inside an iframe (inventory quoted in Z008-RESULT: one iframe
holding textarea=1, contenteditable=1, textbox=1, none visible >20px
on the top page).
Change to: after New project, locate the frame that holds a textarea /
contenteditable (frame inventory first, the D140 way, inside frames
this time), switch into it, build the composer selector from what is
actually in the frame, type the description, submit, keep the 480s
generation wait, download the result if one appears.
If the in-frame composer still cannot be driven, fail with a blocker
quoting the IN-FRAME inventory + screenshot — not the top-page one.


§C — r1 Cloudflare: REPLICATE D142's PROVEN CALL, THEN DIFF
Hard evidence (pc-jobs results/D142-cloudflare-retest.log): D142 read
secrets/cloudflare.env (account len 32, token len 93) and its REST call
(prompt + steps only) returned HTTP 200 and saved a real 700,757-byte
image. D141's REST call with width/height returned 400 AiError 5006 —
a schema rejection, which means auth PASSED on that call too.
The Z008 route (prompt+steps) returns HTTP 401 code 10000.
Task: compare the route's outgoing request against D142's proven
request shape — URL, method, headers, body keys — WITHOUT printing the
token value anywhere. Fix any difference found. Re-run the route
through the POC (POST /api/run/r1).
If the shapes prove identical and the route still 401s while a
standalone D142-shape call in the same run succeeds, quote BOTH raw
responses in the RESULT as the blocker. Do NOT ask Tariq for a new
token unless that comparison has failed first.


§D — r4 ChatGPT: NO CODE CHANGE (waits on a human-warmed profile)
The 480s poll loop is built (Z008) and proven via r5's shared helper.
The remaining block is the Cloudflare "Verify you are human" wall on
the chatgpt profile; the fix is Tariq using that profile once via
OPEN LOGIN, in his own time — never bypassed by code.
In the acceptance run: if the wall is still there, record the blocker
and move on. If it is gone, the poll loop gets its first real run —
report the poll log either way.


§E — GUI HONESTY (Koda's add, included in the published spec)
On page load, each route card shows its LAST result from
smoke-report.json (status + seconds + output name) instead of "idle",
so the page matches the saved record. (Tariq, 2026-11-04: the cards
read "idle" after the Z008 run and only the last solo run showed —
the score looked like one pass instead of five.)
Small change to the POC page/server only; no route logic touched.


§F — OPEN LOGIN IS BROKEN TWICE: REBUILD IT AS REAL CHROME
(Tariq, 2026-11-04: the OPEN LOGIN window opens almost entirely out of
the viewport; dragged into view it shows no login — just the ChatGPT
icon.)
Root causes (Koda, from the code on this branch + the Nov 3 record):
(1) routes.py _browser() parks automation at
--window-position=-32000,-32000 (Z007); Chrome saves that position in
the profile, and the login helper launches with no position args, so
the human window restores to the buried spot.
(2) Worse: server.py's _login_helper.py opens the profile with
PLAYWRIGHT (launch_persistent_context, channel='chrome') — an
automation-driven browser. Sites refuse to do real sign-in work in it:
Google blocked it outright on Nov 3 ("this browser or app may not be
secure"), and ChatGPT serves it the Cloudflare splash — a logo, no
login. The Nov 3 sign-ins that WORKED came from Tariq's real-Chrome
script (login-poc-profiles.ps1), never from this button.
Change to: OPEN LOGIN launches REAL Chrome — plain chrome.exe with
--user-data-dir=<the profile folder>, the Preferences exit-state
repair _browser() already does, --hide-crash-restore-bubble, explicit
on-screen geometry (--window-position=60,60 --window-size=1280,900),
navigated to the site's HOME_URL. No Playwright anywhere in the login
path (Playwright stays for the automated route runs only). Same
one-window-per-site contract: Tariq signs in, closes the window, done.
Acceptance: Tariq clicks OPEN LOGIN: ChatGPT and gets a fully visible
real-Chrome window on his main display where he can pass the human
check and sign in; a following r4 run then sees the warmed profile.
This section unblocks §D: the ChatGPT warm-up is impossible until the
login path is a real, visible browser.


ACCEPTANCE (all)
- Selfcheck PASS, 11 routes.
- One RUN ALL with per-route evidence in card_note.
- r3: ok via meta.ai, description + prompt quoted; no DeepSeek call
  remains in routes.py.
- r8: composer driven inside the frame, or a blocker quoting the
  in-frame inventory.
- r1: route ok through the POC with a saved image, or the two-response
  comparison blocker described in §C.
- r4: poll log if the wall is gone; the wall blocker if not.
- Dormant r9/r10: no code changed, standard listing only.
- Z009-RESULT.md on poc/media-routes with the code commits.
