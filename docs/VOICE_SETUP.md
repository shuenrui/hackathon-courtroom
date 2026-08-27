# Voice Setup — STT in, TTS out

Two audio pipelines run through this system, in opposite directions:

| Direction | Pipeline | Purpose |
|---|---|---|
| **STT — sound in** | demo video → local Whisper → transcript → evidence bundle | gives the jury *ears*: they can't watch the demo, so they read what was said in it |
| **TTS — sound out** | dialogue manifest → ElevenLabs → voiced clips → broadcast | gives the court *a voice*: every judged case plays as spoken drama on the stream |

Both are built around one rule each: STT never leaves the machine; TTS never blocks the show.

---

## Part 1 — STT: how the jury hears the demos

### What it does

Teams submit a short demo video (YouTube, ≤1.5 minutes by form rules). Jurors can't watch video — so `judging/transcribe.py` turns it into text that joins their evidence bundle:

```
YouTube URL ──► yt-dlp pulls the audio (WAV)
             ──► faster-whisper transcribes it
             ──► text written to the form's "Video Transcript" column
             ──► evidence.py puts it in every juror's bundle
```

### The stack

- **yt-dlp** — audio download with hard guardrails: HTTPS YouTube URLs only (validated), `duration <= 300`, `max-filesize 100M`, socket timeouts, 2 retries. A malicious or broken URL wastes at most a bounded download, nothing more.
- **faster-whisper, `tiny` model, CPU, int8** — deliberately the smallest model. Demo clips are short and the transcript only needs to carry *what the team claims the product does*; tiny runs in seconds per clip on a laptop/Pi and never becomes the bottleneck. If your demos are longer or noisier, step up to `base`/`small` — the call site is one line in `get_model()`.
- **ffmpeg** — required on the box (audio extraction).

### Privacy posture

The whole chain is local. No audio bytes touch a cloud speech API — the only network hop is downloading the public YouTube video the team already published. This mattered for the event: teams demo real ideas, and the transcription path was never allowed to become a data leak.

### Operating it

```bash
python3 -m judging.transcribe_watcher --loop
```

The watcher polls the intake for responses whose Video Transcript is blank and fills them from the demo video — so a team that submits without transcribing still gets heard. On the event machine it runs as `deploy/transcribe-watcher.service`. Failures post a Foreman note to #submissions (best-effort) and never kill the watcher.

---

## Part 2 — TTS: how the court speaks

The broadcast voices every line of every case — foreman, three jurors, and the team. This is the part we iterated on hardest, and almost everything below is a lesson from a rehearsal.

### 1. Casting — pick characters, not voices

One voice per courtroom role, and cast them like characters:

- **The Foreman** — ceremonial authority; the voice of the court itself
- **The Builder / Skeptic / Futurist** — three distinct temperaments; give them distinct accents so listeners can follow who's talking without looking
- **The Team** — one shared voice for all participant lines; a local accent is a lovely touch for a local event

**Audition workflow** (do this, don't guess from descriptions):

1. Shortlist 3–4 candidates per role from the library
2. Synthesize each role's *signature line* — one real sentence from your actual content — with every candidate
3. Stitch the clips into per-role audition tracks (`ffmpeg concat`) and listen once
4. Lock the cast, then re-voice a full case end-to-end before judging it

Budget ~1–2k chars per audition round. We swapped the Foreman twice and the whole cast once; each swap cost one focused audition, not a rebuild.

### 2. Where voices come from (ElevenLabs)

| Source | What it is | When to use it |
|---|---|---|
| **Premade voices** | the defaults in your account | quick start — but note: default voices expire (ours carried a 2026-12-31 date); library picks are safer long-term |
| **Voice Library** | 10k+ community voices, filterable by accent/gender/style/use-case, API-accessible on paid tiers | the main casting pool; preview any voice with your own text before committing |
| **Voice Design** | generate a new voice from a text prompt (age, accent, tone, pacing) | when no library voice fits a signature role; 3 options per generation, you pay only the preview text |
| **Voice Cloning** | instant (short sample) or professional (high fidelity) | only if you have rights to the voice — e.g. cloning a real host |

A library voice doesn't need to be "in your collection" to synthesize — the metadata endpoint says not-found, TTS works anyway. Test with TTS, trust the synthesis.

### 3. Model choice

| Model | Character | Verdict |
|---|---|---|
| `eleven_v3` | most expressive, built for character dialogue | **what we ran** — the jury are characters; it shows |
| `eleven_multilingual_v2` | most lifelike + most stable on long-form, broadest language coverage | the reliability fallback if v3 misbehaves on a voice |
| `eleven_flash_v2_5` | fastest, 50% cheaper | bulk/low-stakes; not for the show |
| `eleven_turbo_v2_5` | deprecated | don't start here — we did, and upgraded mid-rehearsal |

The synth script falls back v3 → multilingual_v2 automatically per clip on model errors.

### 4. Budget math

- A judged case ≈ **5–10k characters** voiced (15–25 lines)
- A full event of ~40 cases ≈ **250–400k chars** including rehearsals and re-voices
- Auditions: ~1–2k per round
- Our Creator month (126k chars) covered a heavy rehearsal week + the event with headroom; size your plan for `cases × 10k × 1.5` (the 1.5 is re-voices — you will re-voice)

### 5. The voice map

`broadcast/elevenlabs_voices.json` — one entry per speaker key used by the transcripts:

```json
{
  "engine": "elevenlabs",
  "model_id": "eleven_v3",
  "voices": {
    "foreman":     { "voice_id": "...", "name": "...", "role": "The Foreman", "speed": 1.5 },
    "juror_one":   { "voice_id": "...", "name": "...", "role": "The Builder" },
    "juror_two":   { "voice_id": "...", "name": "...", "role": "The Skeptic" },
    "juror_three": { "voice_id": "...", "name": "...", "role": "The Futurist" },
    "team":        { "voice_id": "...", "name": "...", "role": "The Team" }
  }
}
```

- **`speed`** is post-synthesis time-stretch (ffmpeg `atempo`) — faster *without* pitch shift, so nobody turns into a chipmunk. Our Foreman ran at 1.5: gravitas talks slow, and the court had a queue to get through. Any voice can carry its own speed.
- The synth caches every clip by case+line; nothing is re-synthesized unless you ask.

### 6. Swapping a voice (mid-event safe)

```bash
# change the voice_id in elevenlabs_voices.json, then:
python3 scripts/elevenlabs_synth.py --force --speaker foreman case_T01 case_T02 ...
```

`--speaker` limits the re-voice to that role — a Foreman swap across three cases cost ~4k chars, not a full re-cast. Rebuild segments and re-upload afterwards; the player picks up the new clips.

### 7. Fallback — edge-tts

`scripts/edge_synth.py` voices any line ElevenLabs missed using Microsoft edge-tts: **free and unlimited**, lower quality, no character casting. The event pipeline runs ElevenLabs first and edge-tts on the remainder automatically, so a quota death or a flaky request never leaves a case silent. Rehearse with edge-tts alone if you want the whole flow working before buying anything (`broadcast/prepare.py` uses it for the demo).

---

## The two rules, again

- **STT never leaves the machine.** Local Whisper, bounded downloads, transcript into evidence.
- **TTS never blocks the show.** Cache everything, fall back to free voices, re-voice by role, upload additively.
