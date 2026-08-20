# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Plain static HTML/CSS/JS — no framework, no build step. Confirmed by Shuen Rui (2026-08-18): one folder that opens full-screen in Chrome. Chosen for venue robustness (nothing to install, nothing to break).

## Users

- Primary: the hackathon audience in the room (participants, mentors, spectators) watching the big screen during the 15:00–17:00 livestream window.
- Secondary: the playback operator at the laptop driving the screen, who can pause/skip at any time.

## Product Purpose

Turn captured AI-judging case logs into audience entertainment: a full-screen "broadcast" that plays back each featured case — title card → demo video → TTS-voiced Q&A between three AI judges and the team. Success = the audience experiences judging as a show, and the event never displays raw Discord or private scores.

## Positioning

A replay broadcast over a real AI jury's logs — three distinct AI judge personas (Builder / Skeptic / Futurist) interrogating real builds, each with its own voice. Not an overlay, not a slideshow: a produced courtroom drama generated from real judging data.

## Operating Context

- Event: Devin x Claw Collective x Qwen Hackathon ("Build with AI Agents"), 23 Aug 2026, Microsoft MPR Tioman 1–3, Menara Shell, Kuala Lumpur. Stream window 15:00–17:00; cases judged live in Discord 14:00–16:00.
- A laptop runs the app full-screen (Chrome) → venue display; venue speakers carry TTS + video audio.
- Segment bundles are prepared from the Judging Service outputs (`out/dialog/team_NN.md`, blind-score docs) by a prep step; the web app plays them back. Cases judged 14:00–15:00 are queued and replayed from 15:00; cases judged during the stream are slotted in with a short delay.
- Playback: auto-play by default; operator can pause/skip at any time via hidden controls.

## Capabilities and Constraints

- Segment flow: title card → demo video (submitted link) → TTS-voiced Q&A (judge questions, team answers, follow-ups) → close on "the jury deliberates…" → next.
- TTS audio is pre-generated per line (proposed engine: Edge-TTS — free, no key); the three judges get distinct voices (gender mix fine); participants voiced with a shared or per-team voice.
- Hard constraint: NO scores, rankings, or verdicts on screen — ever. The only public reveal is the 16:45 top-six (names only), which is a separate scene.
- ~14–16 featured segments per event ("fun picks", curated from all judged teams).
- Demo videos arrive as URLs — venue internet needed; local-file fallback is an open item.
- Open: host/narration model; top-six announcement scene graphics.

## Brand Commitments

- Art direction locked: **"The Tribunal"** — an AI courtroom. Judge identities: Builder (amber, practical), Skeptic (cyan, probing), Futurist (violet, visionary). Gavel motif for transitions.
- Event: Devin x Claw Collective x Qwen Hackathon — "Build with AI Agents".

## Evidence on Hand

- Real data shapes: `out/dialog/team_NN.md` transcripts and blind-score docs with judge `review` + `questions` (see `tests/dummy_submissions.json` and the mock pipeline in `judging/`). Sample builds use mock transcripts — real team content only exists on event day. Do not fabricate real team names or claims; sample content is synthetic.

## Product Principles

1. The show never leaks the scoreboard — drama without numbers.
2. Replay is a feature: captured logs let us strip dead air and produce every moment.
3. Venue-robust over clever — plain HTML, pre-generated audio, no runtime dependencies.
4. The judges are characters — consistent voice, color, and temperament per judge.
5. The audience sees a produced courtroom, never the machinery (Discord, sheets, pipelines).

## Accessibility & Inclusion

- Big-screen legibility from a distance: high contrast, large type.
- Every spoken line is also shown as visible text (TTS + captions), so the show still works if audio fails.
