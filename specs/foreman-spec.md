# Foreman spec — the conductor agent

One new, dedicated Hermes agent. Lead judge / Judge Lead of the Devin x Claw Collective x Qwen
Hackathon, 23 August 2026. It directs the jury; it never scores.

Persona: sealed in `prompts/foreman.md`. Mission: moderate the courtroom, run the clock,
relay the spectacle, and hold the timeline — while the Judging Service remains the sole
writer of scores.

## 1. Capability contract (transport-neutral)

| # | Capability | Mechanism |
|---|------------|-----------|
| 1 | Hear team pings in #submissions ("Team N, done submitting @Foreman") | watches #submissions; one thread per team number |
| 2 | Summon | triggers `judging.service summon --team N` |
| 3 | Thread lifecycle | create `case-TNN` in #CASES → pull in participant + 3 judge bots; participant kicked at the 7-min Q&A mark → same thread becomes the courtroom |
| 4 | 7-min shared Q&A clock | starts at the first posted question; countdowns; frozen at zero, unconditionally |
| 5 | Post jury output | judges' reviews + questions from `judging.service dispatch` into the case thread |
| 6 | Deliberation | open verdict, fixed order One → Two → Three, evidence-cited revisions only; light ~2 min / contested ~4 min; close with verdict line |
| 7 | Mirror | score-stripped case mirror to #live-feed (artifacts from the service, never raw numbers) |
| 8 | Announcements | #announcements at open/close; top-six at 16:45 — team names only, never scores |
| 9 | Reflection | at case close, trigger `judging.service reflect --team N` (knowledge loop) |
| 10 | Escalation | sanitization flags / dropped judges / URL unreachable → #ops for Shuen Rui |
| 11 | Heartbeat | #bot-health every 15 min, 14:00–18:30 |

## 2. Reads — memory restore (cross-session safe)

The Foreman's memory lives outside itself:

- `out/foreman/brief.md` — **cold-start brief**, regenerated on every pipeline run: phase,
  scored/contested teams, open threads, flags, upcoming deadlines, last verdicts
- `out/dialog/team_NN.md` — visible Q&A transcripts
- `out/judging.json` / Sheet Judging tab — scores (read-only for the Foreman)
- `knowledge/lessons.md` — the jury's accumulated learning

Any session start: read the brief → resume mid-state. A Foreman crash at 15:20 is not
memory loss — spawn a new session, point it at the brief.

## 3. Transport — DECIDED: Discord-native (Option A, 2026-08-18)

The Foreman's Hermes instance connects **directly to Discord** via a Discord adapter/bot —
it reads and posts in the case threads itself. No bridge, no extra hop.

Setup work: wire Hermes to Discord (it is Telegram-native today). The Telegram-bridge
option (B) was rejected: a relay hop in the critical path is a live-event risk.

## 4. Fallback (go/no-go on 21 Aug)

If the Foreman is not reliable by the 21 Aug rehearsal: **API-only mode.** The Judging
Service already produces every artifact the Foreman would post (dialog, mirrors, verdicts,
announcement text); Shuen Rui or a simple script posts them. Scores are untouched either
way — the spectacle degrades, the judging does not.

## 5. Provisioning checklist

- [ ] New Hermes instance — a fresh, single-mission agent in its own environment (not Window, not Carpet; no shared state)
- [ ] Persona loaded from `prompts/foreman.md`
- [ ] Discord bot **"The Foreman"** with admin access (create threads, add/remove members, post)
- [ ] Transport wiring per option A/B decision
- [ ] Rehearsal 19–20 Aug doubles as the post-11-Aug health check
- [ ] Heartbeat confirmed flowing to #bot-health before the window opens
