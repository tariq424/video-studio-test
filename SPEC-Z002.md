# SPEC-Z002

Distribution: Git copy for ZCode (Tariq's rule, Nov 1, 2026 — ZCode reads Git only, not Google Docs). Human-readable mirror: Koda's "ZCode - Spec Queue" Google Doc.
Result protocol: push Z002-RESULT.md to the branch named in this spec, together with your commits. No RESULT file = not done.

---

SPEC Z002 — Video Studio fit gate: loosen near-match rejections (S8 finding)

Status: OPEN. Repo: video-studio-test. Branch: codex/msg038-smoke (TEST BED ONLY — production is frozen; nothing merges without Tariq's order). Component: the narration-fit / relevance gate exercised by smoke test S8 (the vision relevance check at clip-picking time).

Background: in S8 the gate worked — it accepted the locked Horseshoe Bay beat and correctly rejected a mosque clip against Dockyard narration — but it also rejected BOTH genuine Arts Centre pictures over wording quibbles ("glass doors" vs "glass-doored studios"). Expected behavior after the fix: wording-level variants of the same subject do not by themselves reject a genuine match; true subject mismatches still reject, with the reason logged; locked-subject beats behave exactly as before; ladder order and fail-open behavior unchanged.

Acceptance (all on the test specimens, port 42022): (1) both genuine Arts Centre images now PASS the gate; (2) the mosque clip vs Dockyard narration still REJECTS, reason logged; (3) the Horseshoe Bay locked beat still accepted; (4) the Video Studio suite shows no new failures beyond the one known environment failure (tests/test_setup_worker.py::test_bash_syntax, WSL); (5) the RESULT lists before/after verdicts for all three specimens. Bounds: matching/threshold logic only. QC v9 (qc.py) is Koda-owned and OUT of scope — do not edit it.
