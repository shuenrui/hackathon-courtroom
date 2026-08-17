# Day-of runbook — 23 August 2026

Code repo: this directory. Blackboard = the hackathon spreadsheet. Judge room = Discord.

## Before the day

- [ ] QWEN_API_KEY loaded on the machine running the Judging Service; verify model name in config.json against the account
- [ ] Discord server/category built: team channels, courtroom, #live-feed, #announcements, #ops, #bot-health; four bots with persona identities
- [ ] Form live; entry-ID mapping table filled into form-spec.md and the submission kit
- [ ] Registry repo created; push rights confirmed for team agents
- [ ] Projector tested with #live-feed (sanitized mirror), not the courtroom

## 08:00 — setup

- Service account access to the Sheet confirmed; run one canary: `python3 -m judging.service run --intake <canary file> --team 1` against a dummy row end-to-end
- Foreman heartbeat visible in #bot-health
- Judge bots visible in the courtroom

## 10:10–10:30 — team formation

- Teams declare their public GitHub repo: agent pushes a one-line file to the registry repo
- Team numbers assigned at check-in

## 14:00 — submissions open

- Publish the Form link + entry-ID mapping in the workshop kit and team channels
- Start the Judging Service in poll mode (or run manually every ~5 min in v1)
- Announce in #announcements and team channels: "the jury is reading submissions now"
- Deliberation streams as blind scores land; Foreman opens cases in submission order

## 16:00 — form closes sharp

- Announce close; service processes the last responses
- No new submissions after 16:00; resubmissions before it count (latest wins)

## 16:15 — clarifications close

- Foreman closes all open clarification threads; unanswered questions logged

## 16:30 — lock

- Service writes final Shortlist tab: top 6 + 2 alternates + flags
- Shuen Rui's spot-check pass: flagged queue only; overrides logged by the Foreman

## 16:45 — announce

- #announcements + room: top six by team name and number — no scores
- Round 2 begins (human judges, 60-pt rubric as their scorecard)

## After 18:30

- Compile final scorecards: `out/scorecards.md`; Shuen Rui/helper sends each section to captains manually
- Preserve outputs: judging.json, shortlist.json, report.json + the Sheet, for the post-event note

## Failure modes

| Symptom | Move |
|---|---|
| Judging Service dies | Restart; the Sheet is the state, nothing is lost |
| Qwen API down | Wait one cycle; if still down at 15:30, escalate — fallback: human screening with the same rubric |
| One juror keeps failing | Service drops it and averages survivors; flag surfaces in the Shortlist tab |
| Foreman heartbeat stops | Check the Hermes instance; if dead, deliberation goes manual — Shuen Rui moderates the courtroom, scores still stand |
| Smoke test floods | Lower concurrency / raise timeout in config.json |
