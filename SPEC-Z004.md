# SPEC-Z004

Distribution: Git copy for ZCode (Tariq's rule, Nov 1, 2026 — ZCode reads Git only, not Google Docs). Human-readable mirror: Koda's "ZCode - Spec Queue" Google Doc.
Result protocol: push Z004-RESULT.md to the branch named in this spec, together with your commits. No RESULT file = not done.

---

SPEC Z004 — Sync the feature branches to the public mirror repos (NO merge to any main)

Status: OPEN — AMENDED Nov 1, 6:10 PM (Tariq's decision: NEWSROOM HALF CANCELLED, Video Studio half only — read the AMENDMENT at the end of this Doc before running). Ordered by Tariq, Nov 1, 2026. This spec replaces any merger work: the merge to production main is STOPPED until S4's real YouTube Studio delete flow is proven (SPEC Z003). Do not write or start any merger spec or merge.

Task: push the current feature branches to the corresponding PUBLIC mirror repos, as branches with the SAME names and the EXACT SAME commits, so each mirror branch shares history with its source branch and future syncs fast-forward.

- Video Studio: branch codex/msg038-smoke in tariq424/video-studio-test (head 003b7a4 at spec time) -> the same branch in tariq424/video-studio-test-public. This carries the verified S8 narration-fit gating (commits 3b18209 + 000520c) and the rest of the stacked branch (suite: 144 passed, 4 skipped, 1 known WSL environment failure). The source repo is itself public, so identical commits expose nothing new.

- Newsroom: branch koda/light-theme-source-note in tariq424/newsroom (head 331d37f at spec time) -> the same branch in tariq424/newsroom-public. This carries the verified S9 CHANNEL-tag parser (commit 6202d60), the S4 delete-contract fix (966b347) and the S5 panels (ae50e7a); suite 40 passed, 4 skipped.

HARD BOUNDS:

- Do NOT merge anything into main/master of any repo, public or private. Do NOT touch the live PC checkouts or any running server.

- No force-push over diverged history: if a same-named branch already exists on a mirror with different history, STOP that half and write BLOCKED with the details.

- SECRETS STOP: before pushing the Newsroom half, scan the branch's file contents for anything that must never be public — an API key or token, a password, a private key, Tariq's personal email or phone number inside file content, or a Google Doc ID. If you find one, STOP that half and write BLOCKED naming the file (do not quote the secret). Commit-history metadata (author name/email on commits) is expected and accepted by Tariq's order — content secrets are not.

KODA NOTE (context, not a counter-order): Tariq's Oct 28 standing rule was that public mirrors are SANITIZED SNAPSHOTS (mirror_public.sh; scrubbed copies, never raw private history). Tariq's Nov 1 order for THIS spec explicitly supersedes that rule for these two branches — exact same commits is what he asked for, so the branches are linked. Follow this spec; if the secrets scan trips, the BLOCKED path above governs.

Acceptance (evidence in the RESULT, all of it checkable by Koda from Git):

1. For EACH mirror repo: the branch exists there and its pre-result head SHA is IDENTICAL to the source branch head (003b7a4 / 331d37f, or the newer actual heads if the branches advanced before you ran — report the real SHAs from git ls-remote on both sides).

2. Ancestor proof: git merge-base --is-ancestor 3b18209 <VS branch head> and git merge-base --is-ancestor 6202d60 <Newsroom branch head> both true (the S8 and S9 fixes are inside the synced history).

3. No main moved: report the main-branch SHA of all four repos before and after — unchanged.

4. RESULT via Git only (you cannot write to this Doc): one file Z004-RESULT.md committed on top of EACH mirrored branch in the public repos (this one extra commit per branch is expected; inside it, state the synced head SHA it sits on, the ls-remote pairs, the ancestor checks, and the before/after main SHAs). If either half BLOCKED, the RESULT file on the completed half says so, and the blocked half's reason goes in a Z004-RESULT.md on the SOURCE branch instead — Koda reads Git either way.

---

AMENDMENT TO SPEC Z004 — Tariq's decision, Nov 1, 2026, 6:10 PM (read before running Z004)

The NEWSROOM half of Z004 is CANCELLED. Do NOT push branch koda/light-theme-source-note — or any branch from the private newsroom repo — to newsroom-public, with exact commits or in any other form, under this spec. newsroom-public stays exactly as Tariq's Oct 28 rule set it: SANITIZED SNAPSHOTS ONLY, produced by the PC mirror script (mirror_public.sh) when Tariq orders a mirror refresh. The S9 parser code reaches newsroom-public only through that sanitized snapshot process — it is not part of Z004.

What remains of Z004 is the VIDEO STUDIO half only, exactly as written: push branch codex/msg038-smoke from tariq424/video-studio-test to the same branch in tariq424/video-studio-test-public, exact same commits, no merge to any main.

Acceptance shrinks accordingly: (1) ls-remote evidence that video-studio-test-public has codex/msg038-smoke with its pre-result head identical to the source head (003b7a4 at spec time, or the actual current head — report both SHAs); (2) ancestor proof that 3b18209 (the S8 fit-gate commit) is inside the synced history; (3) main SHAs of video-studio-test and video-studio-test-public before/after, unchanged — and state in the RESULT that the two Newsroom repos were not touched at all; (4) Z004-RESULT.md committed on top of the mirrored branch in video-studio-test-public (the one expected extra commit), carrying the evidence above.
