# hackathon-courtroom

**An AI-agent courtroom for hackathon judging.** Built for the Devin × Claw Collective × Qwen Hackathon (*#BuildForMsia*, 23 August 2026, Kuala Lumpur) — and it ran the real show: 40+ submitted cases judged by a panel of LLM jurors over Discord, every session voiced and livestreamed as it happened.

Two systems live in this repo:

1. **The Judging Service** — deterministic pipeline that turns submissions into sealed scores and a shortlist. Reliability-critical plumbing is plain code; the LLM only does the talking.
2. **The Live Broadcast** — a static website that replays each judged case as a voiced group-chat drama. From the moment a verdict lands in Discord to the case playing on screen: ~3 minutes, zero human steps.

```
Google Form ──► Sheet ──────────────► Judging Service (deterministic)
                                        ├─ dedupe · sanitize (injection defence)
                                        ├─ smoke-test the live URL
                                        ├─ 3 juror personas score BLIND (parallel LLM calls)
                                        └─ aggregate · shortlist · write-back to Sheet
Discord #submissions ──► team pings the Foreman bot
                          └─► private case thread: jury + team
                               ├─ 7-minute shared clock, Q&A in-thread
                               ├─ jury deliberates (hidden from the team)
                               └─ verdict posted  ◄── the trigger for everything below
Watcher (polls every 60s) ──► pipeline
                          ├─ download the thread log
                          ├─ log → dialogue transcript
                          ├─ ElevenLabs: one voice per character
                          └─ segment + playlist (local AND public site)
Static site (nginx on ifhost VM, or any static host)
                          └─► player polls the playlist, plays each case
                               with typing indicators, demo videos, sealed verdict card
```

## The user flow — three experiences, one system

**The team.** You finish building and submit the Google Form — problem, solution, live URL, demo video. Your captain then pings the Foreman in `#submissions`: *"done submitting, team X"*. Within seconds a private thread `case-T##` appears under `#cases` with your team and the three jurors. The Foreman opens the bench, a 7-minute shared clock starts with the first question, and the cross-examination begins — The Builder pokes at whether the demo actually runs, The Skeptic at whether anyone will pay for it, The Futurist at whether the agent truly improvises. You answer right there in the thread; "not built yet" is a legal answer. When the clock hits zero the court steps out — you're removed from the thread while the jury deliberates in private — and the verdict is posted back. Minutes later, your session is playing on the livestream as a voiced drama, and your scores land sealed in the sheet until the top-six announcement.

**The audience.** Open the broadcast URL (or watch the stream). Each case plays as a group-chat replay from the participant's seat: the team's demo video first, then the dialogue — judges on the left, team on the right, typing indicators, every line voiced, scores never shown. The verdict arrives as a sealed card. Cases auto-advance; when a new verdict lands somewhere in Discord, the next case simply appears a few minutes later. There is no schedule — the bench plays whatever has been judged.

**The operator.** Arrive, plug in, run `./scripts/event_start.sh` — done. From there the system is autonomous: verdict → voiced → queued → public, ~3 minutes per case, zero clicks. You watch one log (`tail -f out/broadcast_watch.log`) and intervene only if it yells: a manual re-upload command for a failed push, or the skip-case button on the stream screen to move things along. The screen itself can live on an entirely different laptop — it's just a browser on the public URL.

## How the repo is structured — three layers

```
LAYER 1 — THE BRAIN      judging/ · prompts/ · schemas/ · config.json
          Deterministic plumbing + LLM judgment. Intake, dedupe, injection
          defence, smoke tests, three sealed persona prompts scoring blind,
          aggregation, shortlist, sheet write-back. The jury gets senses too:
          headless-Chromium browsing of the live build, and local Whisper
          transcription of demo videos (no audio ever leaves the machine).
          Nothing here performs; it just has to be right.

LAYER 2 — THE COURTROOM  judging/discordx/ · foreman/ · specs/
          Where teams actually meet the jury: four Discord bots, private
          case threads, the Q&A clock, deliberation, the verdict line.
          The verdict post is the contract between this layer and the next.

LAYER 3 — THE STAGE      broadcast/ · scripts/ · broadcast_host/
          The public show. A static site with no backend — the automation
          writes files, the player polls and plays. Everything the audience
          sees lives here; everything that fetches/voices/uploads a case
          lives in scripts/.
```

Data crosses the layers as plain files — a case's journey:

```
thread log            out/discord_logs/case-T07.log        (layer 2 → 3)
dialogue manifest     broadcast/sources/case_T07.json      (who says what)
voiced clips          broadcast/sources/audio/case_T07_*.mp3
player bundle         broadcast/segments/case_T07.json     (+ team metadata)
the queue             broadcast/segments/playlist.json     (completion order)
```

### File map

```
judging/                the judging service (intake → scores → shortlist)
judging/discordx/       Discord transport: 4 bots, case threads, Q&A clock, verdict flow
prompts/                sealed persona prompts: rubric + 3 jurors + Foreman
schemas/                JSON schemas the jurors must satisfy (blind score, reflection)
specs/                  form/sheet/discord/livestream specs + event runbook
docs/                   GETTING_STARTED (full wiring) · VOICE_SETUP (STT in, TTS out)

broadcast/              THE FRONTEND — the broadcast website
  index.html            single-screen chat-replay UI (Swiss-poster design)
  styles.css            brand system: monochrome, one accent, Inter 900 + Plex Mono
  app.js                Web Audio voice engine, playback, live-queue polling, video stage
  prepare.py            zero-setup demo generator (sample cases + free edge-tts voices)
  sample_data/          demo content for prepare.py

scripts/                the event-day automation
  broadcast_watch.py    daemon: polls Discord for verdicts, feeds the pipeline
  broadcast_pipeline.py one case end-to-end: log → transcript → voice → segment → upload
  discord_log_to_transcript.py   Discord log → speaker-tagged dialogue manifest
  elevenlabs_synth.py   ElevenLabs TTS with caching, per-voice speed, speaker filters
  edge_synth.py         free edge-tts fallback (unlimited, lower quality)
  build_segments.py     transcript + sheet metadata → player-ready segments
  broadcast_upload.py   additive per-case upload to the public site
  dump_discord_logs.py  raw Discord API log downloader
  event_start.sh        ONE COMMAND to arm everything on event day

broadcast_host/         ifhost app definition (nginx config + machine spec)
deploy_broadcast.sh     full-site deploy / recovery push
deploy/                 Orange Pi migration: bundle, systemd unit, device runbook
foreman/                the Foreman's soul (persona files for a Hermes/OpenClaw instance)
```

## Quickstart — zero accounts needed

```bash
pip install -r requirements.txt

# 1. Judge three dummy submissions with mock jurors (no API keys)
python3 -m judging.service run --intake tests/dummy_submissions.json --mock

# 2. Generate the demo broadcast (free edge-tts voices) and serve it
python3 broadcast/prepare.py --judging out/judging.json \
        --answers-dir broadcast/sample_data/answers
python3 -m http.server 8321 --directory broadcast
# open http://localhost:8321 and press PLAY
```

## Running it for real

The full wiring guide — Discord bots, jury model, ElevenLabs voices, Google Sheets intake, hosting, event-day ops — lives in **[docs/GETTING_STARTED.md](docs/GETTING_STARTED.md)**. Voice deserves its own page: **[docs/VOICE_SETUP.md](docs/VOICE_SETUP.md)** covers the STT side (local Whisper — how the jury hears the demos) and the TTS side (casting, models, budget, swaps — how the court speaks).

Event-day startup on the machine running the pipeline:

```bash
./scripts/event_start.sh
# checks internet · starts local server + watcher · arms caffeinate
```

## Design decisions worth knowing

- **Scores never leak.** Jurors return two layers: private scores (strict JSON → sheet, never posted) and a visible review. The dialog layer strips anything score-shaped before it touches a team-visible surface; verdicts render as sealed cards on the broadcast.
- **Deterministic plumbing, LLM talking.** Dedupe, clocks, retries, aggregation, write-back — all plain code. The model only generates dialogue and judgment.
- **The broadcast is 100% static.** No backend. The "live" behavior is the pipeline writing files and the player polling the playlist. You can host it on anything that serves files.
- **One case at a time, by design.** The courtroom shows one case at a time; the pipeline matches the spectacle.
- **The jury learns.** After each case, a reflection pass distills transferable lessons into a knowledge ledger that sharpens later questioning — never the rubric, never the current case's evidence.
- **The jury gets senses, locally.** Jurors can't watch, so the system browses the live build headlessly and transcribes demo videos with a tiny on-device Whisper model — the transcript joins the evidence bundle, and no audio ever touches a cloud API.

## A note from the builder

I built this for one event and iterated my way there — a cinematic "courtroom camera" UI that I threw away for a group-chat replay, a local-only server that became a public site, Turbo voices swapped for v3 character voices mid-rehearsal, a `push` that wiped the site teaching me to upload additively. Every scar in this repo came from a rehearsal catching something real. What's left is the shape that survived: boring where it must be reliable, theatrical where it's allowed to be. If you're building something like this — start with the mock dry run, rehearse until it's boring, and keep the spectacle one layer above the plumbing.

## Requirements

Python 3.11+. `requirements.txt` pins the runtime deps (requests, jsonschema, gspread, discord.py, edge-tts, faster-whisper, yt-dlp). Local demo-video transcription also needs `ffmpeg` on the box. ElevenLabs hosting of the broadcast is optional — see the getting-started guide.
