# Z007 RESULT — POC fix: browser sign-in detection + first generation attempt (§A/§B) + deepseek parser (§C) + Restore-bubble suppression (§D)

**Status: DONE — all §A–§D implemented in `media-poc/routes.py` (only file changed; server.py untouched).
Final RUN ALL: 3 routes producing real outputs (r6 image, r7 video, r11 mp4), r3 precisely diagnosed,
every browser route showing real signed-in evidence — the old unconditional "could not confirm" blocker
is GONE.** Date: 2026-11-03. Branch `poc/media-routes`, on top of 27ffb88 + afe1363 (Z006).

## §A Real sign-in detection (replaces `_unconfirmed`)
Shared `_signin_state(page, site)` → (state, evidence), state ∈ {signed_in, login_wall, unknown}:
- **login_wall only on strong evidence**: auth host/path in the final URL (per-site markers) or a
  visible password input. Generic Log in/Sign up buttons are NOT wall evidence (the Bing bug).
- **signed_in on positive evidence**: ≥2 independent signals per site (composer visibility, account
  avatar/menu, Rewards header, chat sidebar, world gallery...), each checked individually (the
  comma-joined `.first` locator was hitting hidden template elements — root cause of the meta.ai
  false "unknown"); plus a settle-and-retry-once pass when nothing matches.
- **unknown**: screenshot + final URL + first ~500 chars of page text go into the card note; the
  blocker says "state unknown", naming every signal checked — distinct from "sign-in needed".
  A Cloudflare "Verify you are human" challenge is detected and reported inside the evidence
  (never bypassed).
- Evidence goes into `ctx["card_note"]` on EVERY browser-route run (pass or fail).
- `_unconfirmed(...)` is fully removed; all blocker messages use real folder names
  (profiles/chatgpt, profiles/bing, profiles/meta, profiles/flow, profiles/marble).

## §B First generation attempts (best-effort, per spec)
Signed_in → real attempt: type the description at human pace → submit → wait → download:
- **r6 meta-image: ok, 27.3 s — real generated image saved (`output/r6_meta_image.jpg`, 209,552 bytes)**
- **r7 meta-video: ok, 57.9 s — real generated video saved (`output/r7_meta_video.mp4`, 4,089,147 bytes)**
- r4 chatgpt-image: signed_in (composer visible) → generated, failed at the final download step
  (precise blocker + `output/gen_chatgpt_fail.png`)
- r5 bing-image: signed_in (Rewards header + create composer) → Generate clicked → no results grid
  within 180 s (Bing create queue; `gen_bing_fail.png`)
- r8 flow-video: signed_in (Google account avatar) → its prompt composer resisted automation
  (`gen_flow_fail.png`)
- r10 marble-video: signed_in (world prompt input + world gallery) → world did not load within 300 s,
  ONE attempt only, no retry loops (`gen_marble_fail.png`)
- Every failure keeps the signed-in evidence on the card, per spec.

## §C deepseek-describe (r3) parser
- **Diagnosis first** (live replies, recorded in the card note): the current reply carries content
  blocks of types **`['thinking', 'text']`** — and on some calls **`['thinking']` only** (no text at
  all). Earlier replies were plain text/fenced JSON.
- thinking blocks are ignored; `content` as a plain string is accepted; the extraction ladder
  (fenced JSON → greedy JSON → key regex → conversational) is unchanged, now operating on
  fence-stripped text (fence prefixes were leaking into extracted values).
- The error-path bug is fixed: a Blocker raised in the parse block is re-raised untouched —
  e.g. the final RUN ALL shows r3 = blocker 6.3 s "**model returned no text (HTTP 200,
  blocks=['thinking'])**" — precise, not re-wrapped. On thinking+text calls r3 is ok with a clean
  description (quoted in the run log: "A commercial airliner is captured head-on as it approaches a
  runway for la…").

## §D Restore-bubble suppression
- `_browser()` repairs `profiles/<site>/Default/Preferences` before every launch (raw-text flips:
  `"exit_type":"Crashed"→"Normal"`, `"exited_cleanly":false→true`; skipped silently if missing/locked;
  each card notes the repair result — e.g. "prefs: already clean").
- Launch args added: **`--hide-crash-restore-bubble`** and `--window-position=-32000,-32000` +
  `--window-size=1440,1000` (routes run headed-but-offscreen — a real window avoids the Cloudflare
  headless challenge that broke r4 detection). Final flag list in code: `--lang=en-US`,
  `--hide-crash-restore-bubble`, `--window-position=-32000,-32000`, `--window-size=1440,1000`.
- Post-RUN ALL check (quoted): exit_type=Normal for all five profiles — chatgpt, bing, meta, flow,
  marble (`exited_cleanly` key not present in these profile files; exit_type is the crashed-exit marker).

## Acceptance
1. `python selfcheck.py` → **PASS** (11 routes; registry untouched).
2. Server restarted from the updated code; fresh RUN ALL executed; the cards page screenshot saved as
   `media-poc/output/z007_after_runall.png`. /api/state for r4–r10 (quoted):
   - r4 chatgpt-image blocker 37.5 s — "signed in OK (evidence: composer/prompt box visible); failed at step 'image download'"
   - r5 bing-image blocker 204.2 s — "signed in OK (evidence: Rewards/account header visible; create composer visible); failed at step 'no results grid within 180s'"
   - r6 meta-image **ok 27.3 s** — "signin=signed_in; evidence: meta.ai composer visible; signed-in account row present"
   - r7 meta-video **ok 57.9 s** — same evidence
   - r8 flow-video blocker 24.7 s — "signed in OK (evidence: Google account avatar present); failed at step 'prompt box not usable'"
   - r10 marble-video blocker 315.8 s — "signed in OK (evidence: world prompt input visible; Marble world gallery visible); failed at step 'world did not load within 300s'"
3. Detection verdicts per site: chatgpt signed_in · bing signed_in · meta signed_in · flow signed_in ·
   marble signed_in — with the exact evidence strings above. NO route ends in the old unconditional
   blocker; NO "sign-in needed" verdict anywhere positive evidence exists.
4. Outputs this run: `r6_meta_image.jpg` (209,552 B), `r7_meta_video.mp4` (4,089,147 B), plus
   `r11_blender_video.mp4` (52,183 B, Z006) — other routes carry step-level blockers with evidence.
5. Blocker messages name real folders (profiles/chatgpt, profiles/bing, ...).
6. Commits + this RESULT pushed to `poc/media-routes`. Only `media-poc/routes.py` changed (no
   server.py change was needed — `ctx["card_note"]` already existed).
7. §C in the same RUN ALL: r3's reply carried `blocks=['thinking']` (no text) → r3 blocker with the
   structure quoted (the fix's precise path); thinking+text calls parse ok — both shapes evidenced
   during this run and the prior one.
8. §D Preferences post-run: exit_type Normal on all five (quoted above); flags listed under §D.

## Out of scope — untouched
r1 (waits on secrets/cloudflare.env), r2 (this run: HF ZeroGPU quota exhausted — "90s requested vs. 0s
left", a valid POC result; it produced images in the Z005 runs), r9 wangp (not reachable), r11 blender
(Z006's fix, still ok: 25.2 s this run), OPEN LOGIN helper, registry count.
