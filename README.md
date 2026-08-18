# hackathon-judging

Round 1 judging system for the Devin x Claw Collective x Qwen Hackathon — 23 August 2026.

Built for one job: turn submissions into a deliberation-ready shortlist of six (plus two alternates) with per-team scorecards, deterministically and reliably.

## Architecture

Split by design — reliability-critical plumbing is deterministic; the LLM does the talking.

```
intake (CSV/Sheet) ─► Judging Service (deterministic)
                        ├─ dedupe (latest per team number)
                        ├─ sanitize (injection defence)
                        ├─ smoke test the live URL
                        ├─ build ONE shared evidence bundle
                        ├─ dispatch: 3 parallel Qwen calls, one per juror persona
                        │    └─ each returns private scores + visible review/questions
                        ├─ validate strict JSON (retry once, then drop + flag)
                        ├─ aggregate, tie-break, contested detection
                        ├─ write blackboard (sole writer)
                        └─ shortlist + compiled scorecards
                      ─► Dialog layer (the show): summon → juror reviews → questions
                        ─► Foreman (Hermes, LLM layer): courtroom deliberation,
                           spectacle mirror, announcements
```

- Panel: Juror One "The Builder" (completeness), Juror Two "The Skeptic" (problem fit / viability), Juror Three "The Futurist" (agent mastery / novelty) — three sealed persona prompts over one Qwen model.
- Round 2 is human-judged with the same 60-pt rubric; this system serves Round 1 only.

## Layout

```
judging/          deterministic service (stdlib + requests + jsonschema)
schemas/          blind-score JSON schema (the judge contract)
prompts/          sealed prompts: rubric + 3 jurors + Foreman
specs/            Sheet tabs, Form fields, runbook, templates
tests/            dummy submissions
config.json       runtime configuration
```

## Run

```bash
pip install -r requirements.txt

# end-to-end dry run, mock jurors, local files
python3 -m judging.service run --intake tests/dummy_submissions.json --mock

# streaming mode: re-run every 5 min as intake grows (day-of engine)
python3 -m judging.service poll --intake tests/dummy_submissions.json --mock --every 300

# real Qwen calls (needs QWEN_API_KEY)
export QWEN_API_KEY=...
python3 -m judging.service run --intake tests/dummy_submissions.json
```

## The visible jury dialog (the show)

The jury is four Discord-presence bots: The Foreman (Judge Lead) + three juror bots.
The ping event is `summon`: a team submits the form, then pings the Judge Lead on Discord;
the Judge Lead summons the jury for that team and the dialog is posted to the team channel.

```bash
# team pings the Judge Lead  →  judge the team now, print the visible dialog
python3 -m judging.service summon --intake tests/dummy_submissions.json --team 1 --mock

# the team answers in-channel → append their answers to the transcript
python3 -m judging.service answer --team 1 --answers team1_answers.txt --out out
```

Each juror model call returns two layers: **private scores** (strict JSON → Sheet, never
posted) and **visible review + up to 3 questions** (posted to the team channel). The dialog
layer strips any score-like numbers before posting — leaks like `7/10` become
`[score held back]`. Transcripts land in `out/dialog/team_NN.md`; a Discord transport that
implements the same `post()` surface replaces the mock channel at go-live.

Outputs land in `out/`:

- `judging.json` — full results with blind scores, averages, spread, flags
- `shortlist.json` — top six + two alternates + eliminated
- `scorecards.md` — compiled scorecard document
- `delivery/` — one paste-ready scorecard per team for manual sending
- `dialog/` — the visible jury dialog per team (summon → reviews → questions → answers)
- `foreman/` — post-ready artifacts for the Foreman: courtroom case headers (with scores), #live-feed mirrors (scores stripped), verdict lines, and the top-six announcement
- `state.json` — incremental state: unchanged submissions are never re-scored; resubmissions are detected by content hash
- `report.json` — run summary

## Blackboard

Local mode writes JSON files (sole writer = the service). `judging.sheets.SheetsBlackboard` is the provisioned adapter for the Google Sheet blackboard (tabs per `specs/sheet-spec.md`); it activates once `gspread`, a service-account JSON, and the spreadsheet id are in place. Until then it raises a clear provisioning error.

## Key parameters (config.json)

- `shortlist.top_n` = 6, `shortlist.alternates` = 2
- `shortlist.contested_spread` = 10 pts between jurors
- `dispatch.timebox_sec` = 300 per juror per submission
- `smoke.timeout_sec` = 20

## Timeline gates

- 17–18 Aug: form + sheet live, prompts v1, schema — this repo is that deliverable
- 19–20 Aug: rehearsal 1 with three dummy submissions end-to-end incl. a contested case
- 21 Aug: rehearsal 2 under time pressure; go/fallback decision
- 22 Aug: freeze

Fallback if the pipeline is not reliable by 21 Aug: human screening with the same rubric; scorecards still compiled by this repo.
