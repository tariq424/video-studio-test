---
name: storyboard
description: Style-locked storyboard for a Video Studio job or beat - one new AI picture every ~4 s of narration, all in the video's own locked visual style, from the image services (Cloudflare first; never WanGP). Use when the user asks to storyboard a beat or a job, wants more pictures / a faster picture pace in the same look, or a beat's pictures don't match each other. Not for stock searches, narration, or rendering.
---

# Storyboard (Video Studio)

Our own engine, adapted from a public "content engine" prompt's visual half: lock ONE visual style from real source frames,
cut narration into ~4 s pieces, write a standalone prompt per piece that restates the style. No channel analysis, no script
writing: the script already exists in the job.

## Mode

**Autonomous by default.** Make every decision yourself and never stop to ask: pick the job, pick the beats, accept or fix the
style, judge the prompts, generate, report. Use best judgement; log each decision in one line in the final report.

**Checking before generating is the editor's job, not this skill's.** In the video editor the Storyboard button has a
"check prompts first" tick-box: ticked, it shows the style and every prompt on the beat and generates only when the user
presses Generate (`{"action":"storyboard","check":true}`, then `{"action":"storyboard","go":true}`). Point the user there if
they want to vet prompts. Only if the user explicitly asks this skill to go step by step, run the states one per turn and
wait for each reply (`status` = current state, `restart` = state 1).

## Facts

- Live app: Video Studio test bed on http://127.0.0.1:42020, repo `F:\code\video-studio-test`, jobs in `F:\videos_test\jobs`.
- Code: `app/studio/storyboard.py` (style lock, pieces, prompts, generation). Files per job: `short/storyboard/style.json`,
  `short/storyboard/<beat>.json`.
- Plan without generating (free, no GPU): `app\env\Scripts\python.exe scripts\storyboard_plan.py <job_id> [b2 b4 ...]`
- Generate for a beat through the app (so the GPU interlock and the editor see it):
  `curl -s -X POST -H "Content-Type: application/json" -d "{\"action\":\"storyboard\"}" http://127.0.0.1:42020/api/jobs/<job_id>/review/<beat>`
  Then poll `GET /api/jobs/<job_id>/review` until `beats.<beat>.busy` is empty; the pictures are options on that beat.
- Pipeline use is separate: setting `storyboard_rung` (default false) storyboards beats with no stock and no source clip that
  need 2+ pictures. Do not switch it on unless the user asks.

## States

1. **Job** - the job the user named, else the most recent finished Short (`GET /api/jobs`, first with status finished and
   a short_output). Do not start a new job.
2. **Beats** - the beats the user named. Else choose: beats whose pictures are headline cards, graphics fallbacks, a single
   held picture for 15 s or more, or were replaced by story QC (`qc/*.story.json` flagged / `story_repair`). Skip the CTA
   beat and beats made from the source clip or the creator's own footage. At most 4 beats unless asked.
3. **Style lock** - run the plan script once; read `style.style.json`. Accept it if it came from source frames and reads like
   the source. If it says `default`, or describes on-screen graphics/text instead of footage, keep the default documentary
   style (delete `short/storyboard/style.json` only if it is clearly wrong, then re-run).
4. **Prompts** - from the plan output, check every prompt: stands alone (subject, setting, camera, light, mood, action),
   restates the style, matches its piece, stays in the story's place, has no real/named people, flags or maps from outside the
   story, no text/logos. If a beat fails, drop that beat (say why) rather than generate bad pictures.
5. **Generate** - POST `storyboard` for each kept beat, one at a time; wait for each to finish.
6. **Report** - per beat: pieces, pictures made, which service, anything dropped and why. Tell the user the options are on
   the beat in the editor (tick them in play order, then Apply). Never apply them to the video yourself unless asked.

## Rules

- Never WanGP, never Google image services (the code already excludes them). Cloudflare is ~5 s per picture.
- Never click CAPTCHAs or sign-in walls; a service that needs a human is skipped by the code.
- Pictures are GENERATED and tagged as such; keep that tag.
- One beat at a time; never queue work while a beat is busy.
