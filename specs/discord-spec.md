# Discord transport spec — wiring & provisioning

The transport that runs the case flow live in Discord. Code: `judging/discordx/`.
Launched with `python3 -m judging.discordx.runner` (live) or `--dry-run` (rehearsal).

## Bots (4)

| Role | Bot | Token env var |
|---|---|---|
| Foreman (conductor) | TBD — assign | `DISCORD_TOKEN_FOREMAN` |
| Juror One — The Builder | TBD | `DISCORD_TOKEN_JUROR_ONE` |
| Juror Two — The Skeptic | TBD | `DISCORD_TOKEN_JUROR_TWO` |
| Juror Three — The Futurist | TBD | `DISCORD_TOKEN_JUROR_THREE` |

Tokens live in `.env` (gitignored) — never in config.json, never committed.
Current bot names in the server: Vegapunk, Pythagoras, Atlas, Edison — role assignment
pending; set server nicknames to match the roles once assigned.

## Portal settings (per bot)

- MESSAGE CONTENT intent — ON (all four)
- SERVER MEMBERS intent — ON (at least Foreman)
- Invited with Administrator (event-only server)

## Channels (IDs in config.json `discord.channels`)

submissions · cases (hidden) · live_feed · announcements · ops · bot_health

## Case flow (as implemented in `judging.agents.runner` and `judging.agents.court`)

1. Ping in #submissions ("Team N done submitting @Foreman") → single-submission lock check
2. Private thread `case-TNN` created in #CASES; participant + judge bots pulled in
3. Judging service summoned (`summon --team N`); Foreman posts "panel is reading"
4. Each living OpenCode judge posts one conversational question in Builder → Skeptic → Futurist order
5. Shared Q&A clock starts with the Builder's first question (10 min); countdown marks at 3:00 / 1:00 / 0:10; answers in the
   thread are captured to `out/answers/team_NN.txt`
6. At zero: answers logged, participant removed, thread becomes the courtroom
7. Verdict line posted in the courtroom (scores allowed — judges only); score-stripped
   mirror posted to #live_feed
8. Reflection pass runs (knowledge loop); case marked complete in `out/discord_state.json`
9. Heartbeat to #bot_health every 15 min; failures escalate to #ops

## Rehearsal checks (before event day)

- [ ] Dry-run passes end to end: `python3 -m judging.discordx.runner --dry-run`
- [ ] Live connect: all four bots show online
- [ ] Real user can see + post in their private case thread inside hidden #CASES
      (fallback if blocked: make #CASES visible; threads stay private)
- [ ] One live canary case with a dummy team
