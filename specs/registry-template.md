# Registry repo — team registration template

Created at 10:10–10:30 during team formation. Each team's agent pushes ONE file to the registry repo; the Judging Service reads the repo to cross-check submitted repo links.

## Layout

```
registry/
├── team-01.yaml
├── team-02.yaml
└── ...
```

## File format — `team-NN.yaml`

```yaml
team_number: 7
team_name: Agent Smiths
repo_url: https://github.com/org/project
declared_at: 2026-08-23T10:22:00+08:00
```

## Rules

- One file per team; the filename must match the team number (team-07.yaml for team 7).
- The `repo_url` must match the GitHub repo field in the Form submission; mismatches are flagged.
- Pushes after 16:00 are ignored.
- Public repo: judges and the service only need read access.
