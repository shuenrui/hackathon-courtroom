# Google Sheet — blackboard spec

The Judging Service is the **sole writer**. Humans get view or comment access only. Create one spreadsheet; share with the service-account that runs the Judging Service (provisioning step).

## Tab: Intake (append-only)

Mirror of the Google Form responses. The Form owns this tab; the service only reads.

| Column | Type | Notes |
|---|---|---|
| Timestamp | datetime | Form response time; dedupe uses latest per team number |
| team_number | integer | From check-in; primary key |
| team_name | text | |
| captain_contact | text | WhatsApp/Telegram handle for scorecard delivery |
| problem_statement | text | ≤150 words |
| solution | text | ≤300 words |
| project_url | url | required — live deployment |
| demo_video_url | url | ≤3 min |
| github_repo | url | declared at team formation |
| resubmission | boolean | optional marker; dedupe handles it anyway |

## Tab: Judging (service-written)

One row per team, updated as scoring progresses.

| Column | Source |
|---|---|
| team_number, team_name, captain_contact | copied from Intake |
| submitted_at | latest intake timestamp |
| url_reachable, url_status, url_flags | smoke test |
| sanitization_flags | sanitizer |
| juror_one_total / juror_two_total / juror_three_total | blind scores |
| dropped_judges | dispatch failures |
| avg_completeness … avg_novelty, avg_total | aggregated |
| spread | max − min juror total |
| contested | spread ≥ 10 or rank band 4–9 |
| rank, status | shortlisted / alternate / eliminated |
| flags | union of juror flags |
| deliberation_note | Foreman's verdict line, appended after each case |

## Tab: Shortlist (service-written; Shuen Rui's 16:30 screen)

Sorted view: rank, team, avg_total, contested, flags, spot-check status (blank → ok → overridden), override reason.

## Access rules

- Service account: editor.
- Shuen Rui: editor (for the 16:30 spot-check column only — overrides are also logged by the Foreman).
- Everyone else: no access. Scores are private.
