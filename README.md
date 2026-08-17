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
                        ├─ validate strict JSON (retry once, then drop + flag)
                        ├─ aggregate, tie-break, contested detection
                        ├─ write blackboard (sole writer)
                        └─ shortlist + compiled scorecards
                      ─► Foreman (Hermes, LLM layer)
                        courtroom deliberation, spectacle mirror, announcements
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

# real Qwen calls (needs QWEN_API_KEY)
export QWEN_API_KEY=...
python3 -m judging.service run --intake tests/dummy_submissions.json
```

Outputs land in `out/`: `judging.json`, `shortlist.json`, `scorecards.md`, `report.json`.

## Blackboard

Local mode writes JSON files (sole writer = the service). The Sheets adapter interface is `judging.blackboard.Blackboard`; wiring gspread + service-account credentials is a provisioning step (see `specs/sheet-spec.md`).

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
