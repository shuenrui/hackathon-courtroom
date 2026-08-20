# The Tribunal — broadcast UI

Full-screen replay broadcast for the hackathon livestream (15:00–17:00). Plays prepared
case segments: title card → demo video → TTS-voiced cross-examination → "the jury
deliberates…". Spec: `specs/livestream-spec.md`.

## Run it

```bash
cd broadcast
python3 -m http.server 8321
# open http://localhost:8321 in Chrome, press F for fullscreen, click CONVENE COURT
```

A laptop runs this full-screen on the venue display; venue speakers carry the audio.

## Controls (operator)

| Key | Action |
|---|---|
| Space | pause / resume |
| ← / → | previous / next case |
| H | show/hide the operator dock |
| F | fullscreen |
| M | mute |
| S | back to standby |

The dock auto-hides after 3.5 s; move the mouse to bring it back. Playback auto-advances
by default — the operator intervenes only when needed.

## Prepare segments from real judging

```bash
python3 broadcast/prepare.py \
  --judging out/judging.json \
  --answers-dir <dir with team_NN.txt answer files> \
  --teams 7,12,3            # show order; omit for all teams in ranked order
```

- Reads `out/judging.json` (run the judging pipeline first)
- Builds dialogue lines: each judge's review + questions, then the team's answers
- Generates TTS audio per line via Edge-TTS (`pip install edge-tts`; needs internet at
  prep time only — playback is fully offline)
- Voices: Builder `en-US-GuyNeural` · Skeptic `en-GB-SoniaNeural` ·
  Futurist `en-AU-NatashaNeural` · Team `en-GB-RyanNeural` (edit `VOICES` in prepare.py)
- Demo video: drop `broadcast/media/demo_NN.mp4` for team NN; without one the segment
  skips the evidence scene
- Output: `segments/playlist.json` + `segments/case_NN.json` + `segments/audio/*.mp3`

Debug a single scene: `index.html?scene=title|evidence|dialogue|close&seg=0&line=3`

## Included sample data

`segments/` and `media/` contain a prepared 3-case docket built from the repo's dummy
submissions (mock jury + synthetic answers in `sample_data/answers/`) so the app runs
immediately for rehearsal. Regenerate anytime with the command above.

## Event-day hardening (before 23 Aug)

- Self-host the three Google Fonts (venue internet is a flag already)
- Confirm demo-video source: URL links need venue internet; local files are the fallback
- Dry-run the full docket once on the actual laptop + display + speakers
