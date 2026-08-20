#!/usr/bin/env python3
"""Stress test — mock jurors only, no API key needed.

Run: python3 tests/stress_test.py

Covers the concurrency TODO:
  1. burst       — 20-team intake through the full CLI pipeline, all scored 3/3
  2. parallel    — parallel dispatch == serial dispatch, fixed judge order preserved
  3. threads     — 8 teams dispatched concurrently on one shared client: no
                   cross-team contamination (team_number/judge integrity)
"""
import json
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from judging.dispatch import dispatch_to_panel
from judging.evidence import build_evidence_bundle
from judging.qwen_client import MockQwenClient
from judging.schema import BlindScoreValidator
from judging.service import load_config, load_prompts

JUDGES = ["juror_one", "juror_two", "juror_three"]


def make_intake(n: int) -> list[dict]:
    return [
        {
            "team_number": i,
            "problem_statement": f"Team {i} problem statement for the burst test.",
            "solution": f"Team {i} solution description.",
            "project_url": f"https://team{i}.example.com",
        }
        for i in range(1, n + 1)
    ]


def make_bundle(team_number: int) -> dict:
    submission = {
        "team_number": team_number,
        "problem_statement": f"Team {team_number} problem.",
        "solution": f"Team {team_number} solution.",
        "project_url": f"https://team{team_number}.example.com",
    }
    url_evidence = {"reachable": True, "status_code": 200, "flags": [], "signals": [], "smoke_note": ""}
    return build_evidence_bundle(submission, [], url_evidence)


def test_burst(n: int = 20) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        intake_path = Path(tmp) / "intake.json"
        intake_path.write_text(json.dumps(make_intake(n)))
        out_dir = Path(tmp) / "out"
        started = time.monotonic()
        proc = subprocess.run(
            [
                sys.executable, "-m", "judging.service", "run",
                "--intake", str(intake_path), "--mock", "--skip-network", "--out", str(out_dir),
            ],
            cwd=REPO,
            capture_output=True,
            text=True,
        )
        elapsed = time.monotonic() - started
        assert proc.returncode == 0, f"pipeline failed:\n{proc.stdout}\n{proc.stderr}"
        report = json.loads((out_dir / "report.json").read_text())
        assert report["scored_teams"] == n, f"expected {n} scored, got {report['scored_teams']}"
        results = json.loads((out_dir / "judging.json").read_text())
        assert len(results) == n
        for entry in results:
            assert entry["valid_scores"] == 3, f"team {entry['team_number']} lost a judge"
        print(f"[burst]     {n} teams scored 3/3 in {elapsed:.1f}s (full CLI pipeline, mock)")


def test_parallel_serial_equivalence() -> None:
    config = load_config(str(REPO / "config.json"))
    rubric, juror_prompts, _ = load_prompts(config)
    validator = BlindScoreValidator(REPO / config["paths"]["schema"])
    client = MockQwenClient()
    bundle = make_bundle(7)

    par = dispatch_to_panel(bundle, client, rubric, juror_prompts, validator, parallel=True)
    ser = dispatch_to_panel(bundle, client, rubric, juror_prompts, validator, parallel=False)

    assert [d["judge"] for d in par.scores] == JUDGES, "parallel dispatch broke judge order"
    assert [d["judge"] for d in ser.scores] == JUDGES
    assert par.scores == ser.scores, "parallel and serial dispatch diverged"
    assert not par.dropped and not ser.dropped
    print("[parallel]  parallel == serial; fixed judge order preserved")


def test_concurrent_teams(teams: int = 8) -> None:
    config = load_config(str(REPO / "config.json"))
    rubric, juror_prompts, _ = load_prompts(config)
    validator = BlindScoreValidator(REPO / config["paths"]["schema"])
    client = MockQwenClient()

    def score_team(team_number: int) -> dict:
        result = dispatch_to_panel(
            make_bundle(team_number), client, rubric, juror_prompts, validator, parallel=True
        )
        return {"team": team_number, "result": result}

    with ThreadPoolExecutor(max_workers=teams) as pool:
        outcomes = list(pool.map(score_team, range(1, teams + 1)))

    for outcome in outcomes:
        team = outcome["team"]
        result = outcome["result"]
        assert len(result.scores) == 3, f"team {team}: expected 3 scores, got {len(result.scores)}"
        for doc in result.scores:
            assert doc["team_number"] == team, (
                f"cross-team contamination: team {team} got a score doc for team {doc['team_number']}"
            )
            assert doc["judge"] in JUDGES
    print(f"[threads]   {teams} teams dispatched concurrently on one client — no contamination")


def main() -> int:
    test_burst()
    test_parallel_serial_equivalence()
    test_concurrent_teams()
    print("\nall stress checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
