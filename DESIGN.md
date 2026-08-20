# Design system — The Tribunal (broadcast UI)

Recorded from the built world in `broadcast/` (2026-08-20). Direction was brief-pinned
("The Tribunal", locked 2026-08-18); seed roll 6d5ff76e acknowledged and superseded by the
pin. Surface mode: Experience. Product truth: PRODUCT.md.

## World

An AI courtroom at night: three AI judges put each hackathon build on trial. Dramatic and
fun, never a generic esports overlay. The audience sees a produced courtroom, never the
machinery (Discord, sheets, pipelines) and never a score.

## Palette

| Role | Value | Use |
|---|---|---|
| ink | `#0c0a08` | ground (warm near-black, mahogany glow + vignette layers) |
| ink-raised | `#171208` | raised panels |
| ivory | `#f0e6d2` | primary text, team identity |
| ivory-dim | `#b3a488` | secondary text (tinted from ground, never gray) |
| brass | `#c9973f` | institutional accent: labels, frames, buttons, gavel |
| builder | `#e0a458` | Juror One (amber) |
| skeptic | `#52d6c9` | Juror Two (cyan) |
| futurist | `#b78cff` | Juror Three (violet) |
| close-red | `#e86a5a` | CASE CLOSED stamp only |

Dark is forced by the scene: a dimmed venue room, one big display, an audience at distance.

## Type

- **Marcellus** — display: wordmark, case stamps, team names, close line. Inscriptional.
- **Archivo** — dialogue: utterances at 600 weight, large scale for distance legibility.
- **Courier Prime** — the court record: labels, dockets, stamps, operator dock. Typewriter.

Venue scale: wordmark ~8.4vw, case stamp ~12.5vw, utterance ~3.4vw (max-width 34ch).
Fallbacks: Times New Roman / Helvetica Neue / Courier New. Self-host before the event.

## Components

- **Sigil** — radial-gradient orb per judge (amber/cyan/violet), ivory for the team; ring
  inset via ::after. Sizes scale by context (bench card / bench mini / speaker plate).
- **Case stamp** — Marcellus text in a brass double frame, rotated -2.5deg, smash entrance.
- **Bench row** — four plates (3 judges + team); the speaking plate lifts 4px and glows in
  its judge color.
- **Speaker plate** — sigil + name + record-label role, border tinted per judge.
- **Evidence frame** — 16:9 black frame with brass corner brackets offset -12px.
- **Record strip** — Courier labels split left/right under a brass hairline.
- **Operator dock** — dark bar: case rail (frames with a flag marker on current) + transport.

## Motion

- **Stamp smash** (signature): scale 1.9→0.97→1 with blur clearing, ease-out-expo
  `cubic-bezier(0.19, 1, 0.22, 1)`, plus a 0.4s room shake on the stage.
- **Word arrival**: each utterance word rises 0.35em + deblurs, staggered across ~94% of the
  line's audio duration (rAF clock, pause-aware).
- **Deliberation dots**: three-dot pulse on the close line.
- Scene crossfades 0.45s. `prefers-reduced-motion` disables shake/smash/word stagger.

## Scenes

standby (wordmark + bench introductions + CONVENE COURT) → title (docket, case stamp, team)
→ evidence (demo video in frame) → dialogue (bench row, speaker plate, utterance, record
strip) → close (CASE CLOSED stamp, "the jury deliberates…") → end (court stands adjourned).

## Rules

- No scores, rankings, or verdicts on screen — ever (hard product constraint).
- Every spoken line is also visible text (TTS + captions together).
- Operator chrome stays hidden during playback (auto-hide dock; H toggles).
- Playback is offline: audio pre-generated, no runtime dependencies.
