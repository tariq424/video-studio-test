# SPEC-Z007 — POC fix: browser-route sign-in detection false-negative + first generation attempt (r4, r5, r6, r7, r8, r10)


Repo: tariq424/video-studio-test, branch `poc/media-routes`.
Working checkout: your own POC checkout (F:\code\codex-render-work\zcode-z5-poc),
the same one Z005/Z006 use. Base: current head of `poc/media-routes`
(0c95216 at spec time — SPEC-Z006). If Z006 has landed by the time you start,
pull it first; Z007 must NOT touch BLENDER_SCRIPT or r11.
Files: `media-poc/routes.py` only. (`media-poc/server.py` only if a state
field genuinely must change — justify it in the RESULT if so. There is NO
media-poc/app.py; do not create one.)


AMENDED Nov 3, 2026 (Koda, at Tariq's direction; supersedes the D126-published
text — Z007 had not started, so this file was updated in place): adds §C
(deepseek-describe parser regression) and §D (Restore-bubble suppression) to
the original sign-in detection + generation scope (§A/§B unchanged). New
evidence since first publication: Tariq hand-fixed the chatgpt profile
(real-Chrome launch on the profile, waited out the Cloudflare check — it now
shows his chats) and hand-patched all 5 profiles' exit state; a fresh RUN ALL
still returned every browser blocker, plus the §C regression below.


## The problem (verified from the code and a live RUN ALL, Nov 3, 2026)


1. There is NO positive sign-in check in the current code. `_login_page_detected()`
   looks for generic "Log in" / "Sign up" buttons plus per-site URL markers;
   if that does not fire, EVERY browser route then unconditionally calls
   `_unconfirmed(...)`, which raises Blocker("could not confirm the sign-in
   state — treat as NOT SIGNED IN ... layout not matched by defensive
   selectors"). Signed in or not, the result is always that blocker. That was
   Z005's plumbing-by-design; this spec is the follow-up pass.
2. Live RUN ALL (Nov 3) against profiles Tariq had just signed in by hand:
   r4 chatgpt-image blocker 5.5s, r6 meta-image 9.9s, r7 meta-video 7.4s,
   r8 flow-video 10.1s, r10 marble-video 10.2s — all the unconditional
   "could not confirm" blocker above.
3. r5 bing-image blocker 8s with the OTHER message — "sign-in needed — use
   OPEN LOGIN for the Bing Image Creator profile
   (media-poc/profiles/Bing Image Creator)" — even though Tariq's screenshot
   shows bing.com/images/create signed in as Tariq / tarrigg@gmail.com with
   Sign out visible. So for Bing, `_login_page_detected()` FALSE-POSITIVES on
   a signed-in page (a generic Log in / Sign up element somewhere on the page
   is the likely cause — diagnose it, do not guess: log which selector or URL
   marker matched). Two more defects in that same message: the profile path
   is wrong (the real folder is `media-poc/profiles/bing` — `_not_signed_in()`
   interpolates the DISPLAY name into the path), and the other routes'
   `_unconfirmed` messages say "browser profile" instead of the site's real
   folder. All blocker messages must use the real folder names:
   chatgpt, bing, meta, flow, marble.
4. Profile state on the PC (helper jobs D122/D124/D125, Nov 3): all 5 profile
   folders exist with Local State + Cookies (chatgpt 128.8 MB, bing 31.6 MB,
   meta 36.0 MB, flow 125.1 MB, marble 160.1 MB), and the stale Playwright
   login helpers were cleaned — nothing is holding any profile now. The one
   automated probe was inconclusive (it ran on a Python without playwright),
   so prove sign-in state with the POC's own venv Python, from the POC code
   itself — not with a system-Python probe.


## Expected behavior


### A. Real sign-in detection (replaces the unconditional `_unconfirmed`)
Add one shared check used by r4–r8 and r10, returning (state, evidence) with
state in {signed_in, login_wall, unknown}, and put the evidence string into
ctx["card_note"] on EVERY browser-route run, pass or fail:
- login_wall ONLY on strong evidence: the final URL is on an auth/login host
  or path for that site (auth.openai.com, login.live.com, login.facebook.com,
  accounts.google.com sign-in, World Labs auth), OR a visible password input,
  OR a primary "sign in to continue" wall. A generic Log in / Sign up button
  or link ANYWHERE on the page is NOT enough by itself (that is the Bing bug).
- signed_in on ANY solid positive evidence. Implement at least two independent
  signals per site where the page offers them, e.g.:
  - chatgpt: the composer / prompt box is visible; an account avatar or
    account-menu button is present.
  - bing: the Rewards button or account avatar in the header; "Sign out"
    reachable in the account menu; the create prompt box is visible.
  - meta: the meta.ai composer / prompt input is visible; an account avatar.
  - flow: the Flow editor UI (prompt box / create UI) is present; the Google
    account avatar.
  - marble: the Marble app UI (create / worlds) is present; an account
    avatar or menu.
- unknown (no wall, no positive evidence): settle longer and retry the check
  ONCE; then save a state screenshot to media-poc/output/<route>_state.png
  plus the final URL and the first ~500 chars of page text into the card note,
  and only then raise a blocker worded as "state unknown" — clearly distinct
  from "sign-in needed" — naming which signals were checked and matched none.
- The old unconditional "could not confirm ... layout not matched by
  defensive selectors" blocker must be GONE from every route.


### B. Then actually attempt generation (first pass, best-effort)
A signed_in verdict must lead to a real generation attempt — detection alone
is not the finish line:
- Use ctx's desc as the prompt (and the route's existing image fallback chain
  where a video route needs a source image). Per site: focus the prompt
  input, type at human pace, submit, wait a generous timeout for the result,
  then download/save it into media-poc/output/ as r4_chatgpt_image.jpg,
  r5_bing_image.jpg, r6_meta_image.jpg, r7_meta_video.mp4, r8_flow_video.mp4,
  r10_marble_video.mp4, and return that Path like the other routes do.
- If a generation step fails, screenshot the page state (as r6 already does)
  and raise a precise blocker naming the failed step — e.g. "signed in OK
  (evidence: account avatar); prompt box not found". The signed-in evidence
  must still be recorded, so the detection fix is provable even where a
  site's generation UI resists automation.
- Marble (r10): attempt ONCE only — no retry loops that could consume extra
  free generations.


### C. deepseek-describe (r3) parser regression — ADDED by the amendment
r3 was `ok` (~5.4s) in the Z005 runs and in Tariq's Nov 3 morning run; in his
latest RUN ALL it regressed to blocker (~5.3s): "could not parse reply ..."
with the raw reply snippet showing a `"thinking"` field — DeepSeek's
response now carries thinking content the parser does not expect. Fix
r3_deepseek_describe's reply handling so it is robust to the CURRENT reply
shapes:
- Diagnose first: record the raw response's structure (content block types /
  top-level keys only — never the API key) in the RESULT before changing code.
- Content blocks of type "thinking" must be ignored for parsing purposes; the
  description/prompt comes from the text content. Also accept `content`
  returned as a plain string, not only a list of blocks.
- Fix the error-path bug visible in the current code: a Blocker raised inside
  the parse try block (e.g. "model returned no text") is caught by the generic
  `except` and re-wrapped as "could not parse reply". A precise blocker must
  survive as itself — re-raise Blocker untouched.
- Keep everything else about r3 (endpoint, model default deepseek-flash, the
  JSON/fenced/regex/conversational extraction ladder) unchanged.


### D. Kill the Chrome "Restore pages?" bubble permanently — ADDED by the amendment
The headless route runs exit Chrome uncleanly, so the profiles keep recording
a crashed exit and later launches can surface the Restore bubble (Tariq
hand-patched all 5 profiles' Preferences exit state on Nov 3; the routes must
stop re-breaking it). In `_browser()`, apply Tariq's proven pipeline pattern
(login-all-profiles.ps1 v2.3):
- Before launch, if the site's profile is not in use, repair
  `profiles/<site>/Default/Preferences`: set `"exit_type":"Normal"` and
  `"exited_cleanly":true`, raw-text flips only, everything else untouched;
  skip silently if the file is missing or locked.
- Add the launch arg `--hide-crash-restore-bubble` to the Chromium launch
  (both headless and headed paths). If you add any further restore/infobar
  flags, verify each against the installed Chrome version and list in the
  RESULT exactly which flags are in the final code.


### Out of scope — do not touch
r1 cloudflare (waits on Tariq's secrets/cloudflare.env), r2 hf-flux,
r9 wangp, r11 blender (that is Z006), the OPEN LOGIN helper in server.py,
and the 11-route registry count. (r3 is in scope ONLY for §C.)


## Acceptance — all reported in Z007-RESULT.md at the repo root of this branch
1. `python selfcheck.py` passes (11 routes).
2. Restart the POC server from the updated code, run a fresh RUN ALL, and
   save a screenshot of the 42054 cards afterwards as
   media-poc/output/z007_after_runall.png; quote the /api/state summary for
   r4–r10 in the RESULT. (The "before" state is the Nov 3 RUN ALL quoted
   above — cite it, no need to reproduce it.)
3. Per site (chatgpt, bing, meta, flow, marble): the RESULT states the
   detection verdict (signed_in / login_wall / unknown) and the EXACT
   evidence string logged. Success bar: no route ends in the old
   unconditional "could not confirm" blocker, and no "sign-in needed"
   verdict is issued for a profile where positive evidence exists —
   Bing above all.
4. Per browser route: either an output file (report its name and size) or a
   precise step-level blocker with the signed-in evidence still recorded.
5. Blocker messages show the real profile folder paths (profiles/bing, etc.).
6. Commits + Z007-RESULT.md pushed to `poc/media-routes`. Only routes.py
   changed (server.py only if justified in the RESULT).
7. (§C) In the same fresh RUN ALL: r3 deepseek-describe ends `ok` again with
   a real description + prompt in its output JSON, run against a reply that
   includes thinking content; the RESULT quotes the diagnosed response
   structure (block types / keys) that the fix handles.
8. (§D) After the RUN ALL, every profile's Default\Preferences shows
   exit_type Normal / exited_cleanly true (quote the check), and the RESULT
   lists the final launch args added for restore-bubble suppression.
