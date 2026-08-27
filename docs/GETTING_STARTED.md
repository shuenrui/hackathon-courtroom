# Getting Started — from zero to a live judged-and-broadcast hackathon

This guide assumes nothing. By the end you'll have: a Discord courtroom where LLM jurors question real teams, scores written to a Google Sheet, and every closed case playing as a voiced chat replay on a public website — automatically.

Work through it in order; each step builds on the last.

---

## Step 0 — What you need

| Thing | Why | Cost |
|---|---|---|
| A Discord server | the courtroom lives here | free |
| An LLM endpoint (OpenAI-compatible) | the jurors' brains | per-token |
| Google Forms + Sheets + a service account | intake + score write-back | free |
| An ElevenLabs account | the voices | Creator tier recommended (~10k chars per case) |
| Any static host (we used ifhost) | the broadcast site | varies |

```bash
git clone https://github.com/shuenrui/hackathon-courtroom.git && cd hackathon-courtroom
pip install -r requirements.txt
cp .env.example .env                     # fill it in as you go
cp config.example.json config.json       # then put YOUR ids into config.json
```

`config.json` is gitignored on purpose — it holds your guild/channel/spreadsheet IDs. The tracked `config.example.json` is the template; never commit your filled-in copy.

---

## Step 1 — Discord: four bots, one courtroom

The jury is four Discord-presence bots. Teams interact with real-looking judges, not one bot wearing hats.

1. At https://discord.com/developers/applications create **4 applications**: a Foreman (judge lead + MC) and three jurors.
2. For each: Bot → Reset Token → copy the token into `.env`:
   ```
   DISCORD_TOKEN_FOREMAN=...
   DISCORD_TOKEN_JUROR_ONE=...      # The Builder — does the demo actually work
   DISCORD_TOKEN_JUROR_TWO=...      # The Skeptic — is the problem real and viable
   DISCORD_TOKEN_JUROR_THREE=...    # The Futurist — does the agent truly improvise
   ```
3. Enable the **Message Content Intent** for each bot (Bot settings page) — without it they can't read team answers.
4. Invite all four bots to your server (OAuth2 → URL Generator → scopes `bot`, permissions: send messages, create/manage threads, read message history).
5. Create two channels: `#submissions` (teams ping here) and `#cases` (case threads appear here). Put their channel IDs plus the guild ID into `config.json` (`discord` block), mapping each identity to its token env var.

**How the flow works** (`judging/discordx/`):

```
team submits form → pings the Foreman in #submissions ("done submitting, team X")
  → transport resolves the team name against the intake sheet
  → creates PRIVATE thread case-T## under #cases, adds 3 jurors + the pinging participant
  → 7-minute shared clock starts with the first question
  → jurors ask questions; team answers in-thread (recorded)
  → clock hits zero → jury deliberates (team is removed from the thread)
  → verdict posted in the thread  ← this exact line triggers the broadcast
```

The verdict line format is the contract: `=== VERDICT T## ...` — the watcher greps for it. Don't change one without the other.

Test the transport without sending anything real:

```bash
python3 -m judging.discordx --dry-run
```

---

## Step 2 — The jury's brain

Jurors are three **sealed persona prompts over one model** (`prompts/juror_one.md` … `juror_three.md` + `prompts/rubric.md`). The 60-pt rubric: completeness 20, agent mastery 10, problem fit 10, solution quality 10, novelty 10.

Any OpenAI-compatible endpoint works. `config.json`:

```json
"qwen": {
  "base_url": "https://your-endpoint/v1",
  "api_key_env": "QWEN_API_KEY",
  "model": "your-model-id"
}
```

Each juror call returns strict JSON (validated against `schemas/blind_score.schema.json`): **private scores** (→ sheet, never posted) and a **visible review + up to 3 questions** (→ team thread). Anything score-shaped is stripped before posting — a leaked `7/10` becomes `[score held back]`.

### Giving the jury senses

The jurors can't watch — so the system gives them eyes and ears instead:

- **Eyes**: a headless-Chromium browse tool renders the team's live URL (JS SPAs included) and reports what's actually on the page, so "the demo works" is checked, not taken on faith.
- **Ears**: `judging/transcribe.py` transcribes the team's demo video **locally** — yt-dlp pulls the audio (HTTPS YouTube only, ≤5 min, ≤100MB), a `faster-whisper` tiny model (CPU, int8) transcribes it on-device, and the text lands in the form's *Video Transcript* column → the jurors' evidence bundle. No audio ever leaves the machine; there is no cloud speech API in this pipeline.

`judging/transcribe_watcher.py` runs this as a daemon: it watches the intake for responses with a blank transcript and fills them from the demo video. Needs `ffmpeg` on the box. Deployed as a service on the event machine (`deploy/transcribe-watcher.service`). Full detail in [VOICE_SETUP.md](VOICE_SETUP.md), Part 1.

---

## Step 3 — Intake: form → sheet → service

1. Build your Google Form. The field mapper (`judging/blackboard.py`, `FIELD_RULES`) matches header substrings, so your titles can carry suffixes ("Problem Statement (Max 150 words)"). Distinctive cores it looks for: `problem statement`, `demo video`, `project url`, `github`, `team name`, `team number`, `solution`, `email`, `track`.
2. Create a **service account** (Google Cloud → IAM → service account → JSON key). Share the spreadsheet with the service account email as **Editor**. Key file path + spreadsheet ID go in `config.json` (`sheets` block). The key file itself is gitignored — never commit it.
3. The service owns three tabs: `Form responses 1` (read), `Judging Sheet` (scores — sole writer), `Shortlist` (sole writer). Layout: `specs/sheet-spec.md`.

**Gotcha learned the hard way:** if the service caches its own team registry, hand-editing the Judging Sheet gets overwritten on the next sync. The service's state is the source of truth — clean up there, not in the sheet.

---

## Step 4 — Voices

This is what makes the broadcast feel like a show. Every speaker gets a distinct voice; the config is one file: `broadcast/elevenlabs_voices.json`.

```json
{
  "engine": "elevenlabs",
  "model_id": "eleven_v3",
  "voices": {
    "foreman":     { "voice_id": "...", "name": "...", "speed": 1.5 },
    "juror_one":   { "voice_id": "..." },
    "juror_two":   { "voice_id": "..." },
    "juror_three": { "voice_id": "..." },
    "team":        { "voice_id": "..." }
  }
}
```

The short version: cast voices like characters (audition 3–4 candidates per role with one signature line), use `eleven_v3` for the show, budget ~10k chars per case × 1.5 for re-voices, and keep the free edge-tts fallback armed so a case is never silent.

The full treatment — casting workflow, voice sources, model trade-offs, budget math, per-voice speed, mid-event voice swaps, and the STT side (how the jury hears the demos) — lives in **[docs/VOICE_SETUP.md](VOICE_SETUP.md)**.

---

## Step 5 — How the dialogue works (log → screen)

The broadcast is a **voiced group-chat replay** rendered from the Discord record:

```
case-T07.log                       raw thread dump (timestamps, authors, text)
  ↓ scripts/discord_log_to_transcript.py
broadcast/sources/case_T07.json    entries: {speaker, kind, text, ts, tts?, audio?}
  ↓ scripts/elevenlabs_synth.py    (one MP3 per tts-eligible line)
broadcast/sources/audio/*.mp3
  ↓ scripts/build_segments.py      (+ team name/one-liner/demo link from the sheet)
broadcast/segments/case_T07.json   the player-ready bundle
  + segments/playlist.json         the queue, completion order
```

Rules baked into the converter:

- Authors map to speakers by identity (juror bots → their roles; humans → `team`).
- **Deliberation is excluded** — everything after the court steps out never reaches the transcript.
- **Score-bearing foreman lines go silent** — the verdict renders as a sealed card instead of being spoken.
- The team's demo video link (from the sheet's `demo video` column) plays before the dialogue — YouTube embeds auto-advance when they end.

The player (`broadcast/app.js`) is a single Web Audio context (unlocked by the play gesture so every line is guaranteed audible), typing indicators scaled to message length, and a standby loop that polls the playlist every 15s — when a new case lands, it plays next. Controls: play/pause (Space), restart (R), **skip case (N)**, mute (M), fullscreen (F).

---

## Step 6 — The website

`broadcast/` is the entire frontend — no framework, no build step:

- `index.html` — one screen: header, chat column, control bar
- `styles.css` — the brand system (Swiss-poster logic: monochrome, one accent, left-column grid)
- `app.js` — voice engine + playback + live queue

Serve it locally: `python3 -m http.server 8321 --directory broadcast`.

**Cache-busting discipline**: assets are referenced with `?v=N`. Bump the version in `index.html` whenever you change `app.js`/`styles.css`, or browsers will happily keep playing your old bug. JSON fetches are cache-busted at runtime; audio filenames are immutable per case.

---

## Step 7 — Hosting it publicly

The site is static, so any file host works. We used **ifhost** (Fly.io VMs + nginx):

```bash
ifhost init --app your-broadcast --port 80 --memory 256   # once
ifhost deploy --yes                                        # boot the VM
ifhost machines install --app your-broadcast nginx         # once
./deploy_broadcast.sh                                      # full push + nginx + verify
```

Two upload modes, deliberately separate:

| Mode | Script | Semantics |
|---|---|---|
| **Full deploy** | `deploy_broadcast.sh` | `machines push` — **replaces** `/app` with a playlist-driven stage. Use for initial deploy, recovery, and shipping UI changes. |
| **Per-case upload** | `scripts/broadcast_upload.py` | tar → `machines write` → extract — **additive**, never wipes existing cases. Audio batched into ≤8MB tars (write caps at 10MB), playlist uploaded LAST so the player never sees a case before its files exist. |

That split came from a real incident: a `push` used for a per-case update silently replaced the whole site. Additive for data, replacing for deploys — don't cross the streams.

Any other host works: point the pipeline's upload step at your transport (rsync, S3, Pages) and keep the two rules — additive data updates, playlist last.

---

## Step 8 — Event day

One command on the machine running the pipeline:

```bash
./scripts/event_start.sh
```

It verifies the public site, starts the local server + the watcher daemon, and arms `caffeinate` (the laptop must not sleep — keep it plugged in, lid open or on an external display).

From there it's autonomous:

```
verdict lands → ≤60s the watcher notices → ~2min pipeline → case plays on screen
```

Monitoring: `tail -f out/broadcast_watch.log`. Failure modes and their fixes:

| Symptom | Cause | Fix |
|---|---|---|
| Player: ERROR / PLAYLIST NOT FOUND | segment fetch failed mid-queue | hard refresh; check the public segment URLs |
| Case queued locally but not public | upload failed (logged as WARNING) | `python3 scripts/broadcast_upload.py case_T##` |
| Nothing new appearing | watcher dead / internet down | re-run `event_start.sh` |
| Wrong team names on screen | numbering source shifted | check `build_segments.py:sheet_teams` numbering source |

The stream screen is just a browser on the public URL in fullscreen — it can live on a completely different laptop than the pipeline.

---

## Step 9 — After the event

- **Archive**: bundle the runtime state before touching anything (`deploy/bundle.sh` is the Orange Pi migration pattern — same idea works for any move: tar the scripts + config + state, unbundle on the target, verify with a mock run).
- **Privacy before open-sourcing**: real case data (team names, Q&A, voiced audio) lives in `broadcast/segments/case_T*.json` and `broadcast/sources/` — both gitignored here. Audit your own repo with a secret scan before making it public; `.env`, service-account keys, and bot tokens must never be committed.
- **The demo path** (`broadcast/prepare.py` + `sample_data/`) regenerates playable sample cases with free voices, so strangers can press PLAY without any of your event data.
