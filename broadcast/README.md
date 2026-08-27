# broadcast/ — the livestream player

Single-screen **group-chat replay** of judged cases, participant POV: team messages on the right, the jury on the left, voices on every line, demo video before the dialogue, verdict rendered as a sealed card. No framework, no build step.

```
index.html    one screen: header · chat column · control bar
styles.css    brand system — Swiss-poster logic: monochrome, one accent, left-column grid
app.js        Web Audio voice engine · playback · live-queue polling · video stage
prepare.py    zero-setup demo generator (sample cases, free edge-tts voices)
segments/     player-ready case bundles + playlist.json (real case_T* data is gitignored)
sources/      transcripts + generated audio (gitignored)
assets/       partner logos + jury avatar images
```

## Run the demo (no accounts needed)

```bash
python3 broadcast/prepare.py --judging out/judging.json \
        --answers-dir broadcast/sample_data/answers
python3 -m http.server 8321 --directory broadcast
# open http://localhost:8321 → PLAY
```

## Controls

| Key | Action |
|---|---|
| Space | play / pause |
| R | restart current case |
| N | **skip to next case** |
| M | mute |
| F | fullscreen |

## Live behavior

When the queue runs out the player shows STANDBY and polls `segments/playlist.json` every 15s; new cases (staged by `scripts/broadcast_watch.py` + `scripts/broadcast_pipeline.py`) play automatically. Broken segments are skipped, never fatal.

Wiring, voices, hosting, event-day ops: see `docs/GETTING_STARTED.md` at the repo root.
