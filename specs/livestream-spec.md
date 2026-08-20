# Livestream broadcast spec — 23 Aug, 15:00–17:00

The audience-facing broadcast. **Discord is the capture layer, never the screen.** This is a
custom broadcast UI that renders captured case logs into produced segments and plays them
back. Replay-based, not real-time.

## Locked

- **Replay-based.** Each featured case is rendered into a produced video segment from its
  captured log, then played back. No raw Discord on screen — it's small and ugly; we design
  something fun and cool instead.
- **Pre-stream cases replay from 15:00.** Cases judged 14:00–15:00 are captured and rendered
  ahead of time, queued, and replayed once the stream goes live at 15:00. Cases judged
  15:00–16:00 (while live) are captured, rendered, and slotted in with a short delay.
- **Only a subset is featured.** 50–70 teams expected (fewer after drop-off); a 2-hour window
  can't fit everyone. **Selection = curated "fun picks"**: from all judged teams, feature the
  ones with a great demo video, a novel idea, or a good story — not strictly high scores.
  Target **~14–16 segments**. The feature decision is made per-case as judging completes
  (render + queue) until the target is hit.
- **No scores on stream — ever.** Scores/rankings are private. Each segment ends after the
  Q&A on a "the jury deliberates…" button; the only public reveal is the 16:45 top-six
  (names only). This keeps the announcement surprising.
- **Replay compresses time.** The 7-min live Q&A clock includes participant thinking/typing
  time. The rendered segment voices only the actual messages (~3 min), so dead air is stripped.
- **All dialogue is voiced (TTS).** Not plain text on screen.

## Segment shape (per featured team)

1. **Title card** — team number / name
2. **Demo video** — the ≤3 min human-recorded video they submitted
3. **Voiced Q&A** — judges' questions + participants' answers, rendered as a styled
   conversation with TTS
4. **Follow-ups** (if any) — judge follow-up → participant answer
5. **Transition** → next team

## TTS / voices

- The **three judges each get a DISTINCT voice** (Builder / Skeptic / Futurist). Gender mix
  is fine — some female, some male.
- **Participants** are voiced too — a shared voice or per-team voice (looser rule).
- **Foreman** voice: TBD (only if it narrates on stream).

## Capacity math

- Segment ≈ 3 min demo video + ~3 min voiced dialogue + transitions ≈ **6–7 min**.
- 2-hour window (15:00–17:00) minus stream open (~5 min) and the 16:45 top-six announcement
  (~10 min) → ~100–110 min for team segments → **~14–16 slots**.
- Feature pool = all judged teams; pick ~14–16 fun/compelling ones.

## Design direction (art direction locked, build in progress)

**"The Tribunal"** — the AI jury puts each build on trial. Leans into the courtroom language
already in the system (Foreman, jury, deliberation, verdict, gavel). Dramatic + fun, not a
generic esports overlay.

- Three judge benches, each a character with a color + distinct TTS voice:
  **Builder** (amber, practical) · **Skeptic** (cyan, probing) · **Futurist** (violet, visionary).
- Demo video on an "evidence screen"; Q&A as stylized cross-examination with nameplates.
- Gavel transitions; segments close on "the jury deliberates…" (no scores).

## Data source (already built)

The broadcast renderer consumes what the Judging Service already captures:

- `out/dialog/team_NN.md` — the visible Q&A transcript (reviews + questions + answers)
- each judge's `review` and `questions` from the blind-score docs
- the submitted demo video link (`demo_video_url`)

So this is a **rendering problem over existing data**, not a new capture problem.

## Open

- **UI build** — art direction locked ("The Tribunal"); building a sample segment. Shuen Rui
  has no specific references and has green-lit creative freedom.
- **Host / narration model** — Foreman-narrated, human host, or none.
- **Graphics package** — lower-thirds, top-six reveal visuals, overlays.
- **Playback runner** — how segments are queued and played from 15:00 (playlist / scheduler).
- **TTS voice casting** — pick the actual three judge voices + participant voice(s).
