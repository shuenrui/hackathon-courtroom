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
  can't fit everyone. Proposed selection: shortlist + alternates + contested cases.
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
- 2-hour window (15:00–17:00) → **~17 slots**.
- Expected feature set (shortlist 6 + alternates 2 + contested ≈ 8–12) → fits with buffer.

## Data source (already built)

The broadcast renderer consumes what the Judging Service already captures:

- `out/dialog/team_NN.md` — the visible Q&A transcript (reviews + questions + answers)
- each judge's `review` and `questions` from the blind-score docs
- the submitted demo video link (`demo_video_url`)

So this is a **rendering problem over existing data**, not a new capture problem.

## Open

- **Selection rule** — confirm which teams get featured (proposed: shortlist + alternates +
  contested).
- **UI design** — awaiting Shuen Rui's reference images; then design the broadcast look.
- **Host / narration model** — Foreman-narrated, human host, or none.
- **Graphics package** — lower-thirds, top-six reveal visuals, overlays.
- **Playback runner** — how segments are queued and played from 15:00 (playlist / scheduler).
