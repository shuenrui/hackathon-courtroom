# hackathon-judging

Round 1 judging system for the Devin x Claw Collective x Qwen Hackathon — 23 August 2026.

Built for one job: turn submissions into a deliberation-ready shortlist of six (plus two alternates) with per-team scorecards, deterministically and reliably.

## Architecture

Split by design — reliability-critical plumbing is deterministic; the LLM does the talking.

```
intake (CSV/Sheet) ─► Judging Service (deterministic)
                        ├─ dedupe (first per team — single submission, locked)
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
schemas/          blind-score + reflection JSON schemas (the judge contracts)
prompts/          sealed prompts: rubric + 3 jurors + Foreman
specs/            Sheet tabs, Form fields, runbook, foreman-spec, templates
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

# case closed → reflection pass (3 judges + Foreman meta) → lessons ledger
python3 -m judging.service reflect --team 1 --answers team1_answers.txt --mock --out out
```

## Knowledge loop — the jury gets sharper every case

After a case closes, `reflect` fires a reflection pass: each judge + the Foreman (3rd-person
meta) write 2-4 transferable lines about the case. They land in `knowledge/`:

- `knowledge/reflections/case_NN.md` — human-readable record per case (the jury's casebook)
- `knowledge/reflections.json` — machine ledger
- `knowledge/lessons.md` — distilled, capped block (v1: deterministic — latest entries per
  lens, capped; model-driven distillation is a planned upgrade)

Every subsequent dispatch injects the lessons block into the judges' prompts ("LESSONS
LEARNED SO FAR"), capped per lens so prompts never bloat. Lessons sharpen **what to look
for and what to ask — never the rubric anchors**; scoring on the current case's evidence
stays blind and sealed. Cold-start safe: any new run rebuilds from the ledger.

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
- `state.json` — incremental state: a team's first submission locks the slot; later entries are ignored + counted; unchanged submissions are never re-scored
- `report.json` — run summary

## Blackboard

Two intake sources:

- **Local mode** (default): CSV/JSON intake file (sole writer = the service).
- **Sheet mode**: `--intake sheet` reads the Google Form responses tab via a service account (`gspread`). Provisioning: service-account JSON on disk (gitignored), sheet shared as editor with the service account email, `sheets.credentials_path` + `sheets.spreadsheet_id` set in config.json, `pip install gspread`. Column map lives in `judging/blackboard.py` (`SheetsBlackboard.COLUMN_MAP`).

**Write-back**: in sheet mode the service is the sole writer of the **Judging** and **Shortlist** tabs (layout in `specs/sheet-spec.md`). Every run syncs both tabs after writing the local JSON outputs. Sheet sync is best-effort — a Sheets hiccup logs a warning and never kills the run; the local outputs are the source of truth.

## Key parameters (config.json)

- `shortlist.top_n` = 6, `shortlist.alternates` = 2
- `shortlist.contested_spread` = 10 pts between jurors
- `dispatch.timebox_sec` = 300 per juror per submission
- `dispatch.parallel_judges` = true (the 3 judge calls run concurrently within a team)
- `smoke.timeout_sec` = 20
- `knowledge.dir` = `knowledge/`, `knowledge.lessons_per_lens` = 4 (cap injected lessons per judge lens)

## Timeline gates

- 17–18 Aug: form + sheet live, prompts v1, schema — this repo is that deliverable
- 19–20 Aug: rehearsal 1 with three dummy submissions end-to-end incl. a contested case
- 21 Aug: rehearsal 2 under time pressure; go/fallback decision
- 22 Aug: freeze

Fallback if the pipeline is not reliable by 21 Aug: human screening with the same rubric; scorecards still compiled by this repo.

## Concurrency + stress test

Problem: scoring was sequential — a submission burst (e.g. everyone submits 15:45–16:00)
could push the queue past the 16:15 clarification cutoff.

Status:

- [x] **Parallel judges within a team** — the 3 judge calls are independent and now run
      concurrently (`dispatch.parallel_judges`, ThreadPoolExecutor). ~3× faster per team.
      Judge order in the output is always the fixed One → Two → Three regardless of which
      finishes first.
- [x] **Queue discipline (deliberate choice)** — teams are processed sequentially, one case
      at a time. The Discord side (threads, Q&A) is naturally parallel; the courtroom shows
      one case at a time, so the pipeline matches the spectacle. Ping order = processing order.
- [x] **Mock burst stress test** — `python3 tests/stress_test.py`: 20-team burst through the
      full CLI pipeline, parallel-vs-serial equivalence, and 8-team concurrent dispatch with
      cross-team contamination checks. Zero cost (mock jurors).
- [ ] **Real-API load test at rehearsal** — canary 3 teams first, then scale to ~10; measure
      throughput + rate-limit behavior; set the honest per-team ceiling for event day.
      (Needs `QWEN_API_KEY`.)
