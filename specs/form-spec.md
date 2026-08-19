# Google Form — submission spec

The Form is the **official submission record** and carries ONLY the submission content. Identity (team name, members, captain contact) lives in the registry repo; the form's `team_number` is the join key back to it. Teams (usually their submission agent) fill it; responses land in the Intake tab.

## Fields

| # | Field | Type | Validation |
|---|---|---|---|
| 1 | Team number | dropdown (1..N, generated from check-in count) | required — join key to the registry |
| 2 | Problem statement | paragraph | required, ≤150 words stated in help text |
| 3 | Solution | paragraph | required, ≤300 words stated in help text |
| 4 | Project URL | URL | required |
| 5 | Demo video link | URL | required, ≤3 min stated |
| 6 | GitHub repo | URL | required — must match `repo_url` in the team's registry file |

Dropped from the form (live in the registry instead): team name, member names, captain contact.

## Form settings

- One response per team is enforced by the service: the FIRST form response locks the slot; later responses are ignored and counted. State this on the form so teams don't waste a resubmission.
- Collect email addresses: OFF (team identity lives in the registry, not the form).
- Confirmation message: "Received. The jury is on it — watch your team channel for clarification questions."

## Entry-ID mapping table

Required for agent-driven scripted submission. Fill in after the form exists: open the form's pre-filled link, map each field to its `entry.<id>`, and publish the table in the workshop kit + the team channel at 14:00.

| Field | entry ID |
|---|---|
| Team number | TBD |
| Problem statement | TBD |
| Solution | TBD |
| Project URL | TBD |
| Demo video link | TBD |
| GitHub repo | TBD |

POST endpoint form-action URL: TBD (from the pre-filled link's `action`).
