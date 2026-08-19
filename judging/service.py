import argparse
import json
import sys
import time
from pathlib import Path

from .aggregate import average_scores, build_shortlist, juror_spread, rank_teams
from .blackboard import Blackboard, SheetsBlackboard
from .dispatch import dispatch_reflections, dispatch_to_panel
from .evidence import build_evidence_bundle
from .knowledge import ReflectionStore
from .qwen_client import MockQwenClient, QwenClient
from .sanitize import sanitize_submission
from .schema import BlindScoreValidator
from .scorecards import compile_scorecards, split_scorecards
from .smoke_test import smoke_test
from .state import RunState

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_config(config_path: str) -> dict:
    return json.loads(Path(config_path).read_text())


def load_prompts(config: dict) -> tuple[str, dict[str, str], str]:
    rubric = (REPO_ROOT / config["paths"]["rubric_prompt"]).read_text()
    juror_prompts = {
        juror: (REPO_ROOT / path).read_text()
        for juror, path in config["paths"]["juror_prompts"].items()
    }
    foreman = ""
    foreman_path = config["paths"].get("foreman_prompt")
    if foreman_path and (REPO_ROOT / foreman_path).exists():
        foreman = (REPO_ROOT / foreman_path).read_text()
    return rubric, juror_prompts, foreman


def build_client(config: dict, mock: bool):
    if mock:
        return MockQwenClient()
    return QwenClient.from_config(config["qwen"], timebox_sec=config["dispatch"]["timebox_sec"])


def judge_submission(
    submission: dict,
    config: dict,
    client,
    rubric: str,
    juror_prompts: dict[str, str],
    validator: BlindScoreValidator,
    skip_network: bool = False,
    lessons: str = "",
) -> dict:
    started = time.monotonic()
    sanitized, sanitization_flags = sanitize_submission(submission, config["limits"])

    if skip_network:
        url_evidence = {
            "submitted_url": submission.get("project_url", ""),
            "reachable": None,
            "flags": ["smoke_test_skipped"],
            "signals": [],
            "smoke_note": "Smoke test skipped in offline run.",
        }
    else:
        url_evidence = smoke_test(
            submission.get("project_url", ""),
            timeout_sec=config["smoke"]["timeout_sec"],
            user_agent=config["smoke"]["user_agent"],
        )

    bundle = build_evidence_bundle(sanitized, sanitization_flags, url_evidence)
    dispatch = dispatch_to_panel(
        bundle,
        client,
        rubric,
        juror_prompts,
        validator,
        retries=config["dispatch"]["retries"],
        lessons=lessons,
    )

    averages = average_scores(dispatch.scores)
    spread = juror_spread(dispatch.scores)
    flags = sorted({flag for doc in dispatch.scores for flag in doc.get("flags", [])})
    evidence_notes = [note for doc in dispatch.scores for note in doc.get("evidence", [])]

    return {
        "team_number": submission.get("team_number"),
        "team_name": submission.get("team_name", ""),
        "captain_contact": submission.get("captain_contact", ""),
        "project_url": submission.get("project_url", ""),
        "url_smoke": {
            "reachable": url_evidence.get("reachable"),
            "status_code": url_evidence.get("status_code"),
            "flags": url_evidence.get("flags", []),
            "note": url_evidence.get("smoke_note", ""),
        },
        "sanitization_flags": sanitization_flags,
        "valid_scores": len(dispatch.scores),
        "dropped_judges": dispatch.dropped,
        "averages": averages,
        "spread": spread,
        "flags": flags,
        "evidence_notes": evidence_notes,
        "blind_scores": dispatch.scores,
        "elapsed_sec": round(time.monotonic() - started, 1),
    }


def run_pipeline(args) -> int:
    config = load_config(args.config)
    rubric, juror_prompts, _foreman = load_prompts(config)
    validator = BlindScoreValidator(REPO_ROOT / config["paths"]["schema"])
    client = build_client(config, args.mock)
    knowledge_dir = REPO_ROOT / config.get("knowledge", {}).get("dir", "knowledge")
    lessons = ReflectionStore(knowledge_dir).load_lessons()
    if lessons.strip():
        print("knowledge: injecting lessons from prior cases into juror prompts", flush=True)
    if args.intake == "sheet":
        sheets_cfg = config.get("sheets", {})
        board = SheetsBlackboard(
            sheets_cfg.get("credentials_path", ""), sheets_cfg.get("spreadsheet_id", "")
        )
    else:
        board = Blackboard()

    state = RunState(Path(args.out) / "state.json")
    previous = {str(e["team_number"]): e for e in state.previous_results()}

    raw_intake = board.load_intake(None if args.intake == "sheet" else args.intake)
    ignored_resubmissions = board.ignored_resubmissions(raw_intake)
    intake = board.dedupe_first(raw_intake)
    if ignored_resubmissions:
        detail = ", ".join(f"team {k} (x{v + 1} entries)" for k, v in sorted(ignored_resubmissions.items()))
        print(f"note: later submissions ignored — single submission locked at first entry: {detail}", flush=True)
    if args.team is not None:
        intake = [row for row in intake if row.get("team_number") == args.team]
        if not intake:
            print(f"team {args.team} not found in intake", file=sys.stderr)
            return 2

    results = []
    for submission in intake:
        team_key = str(submission.get("team_number"))
        if team_key in previous and not state.needs_scoring(submission):
            results.append(previous[team_key])
            print(f"team {submission.get('team_number'):>3} | unchanged, reusing prior scores", flush=True)
            continue

        entry = judge_submission(
            submission,
            config,
            client,
            rubric,
            juror_prompts,
            validator,
            skip_network=args.skip_network,
            lessons=lessons,
        )
        state.mark_scored(submission)
        results.append(entry)
        print(
            f"team {entry['team_number']:>3} | valid {entry['valid_scores']}/3 | "
            f"total {entry['averages'].get('total', '-')} | spread {entry['spread']} | "
            f"{entry['elapsed_sec']}s",
            flush=True,
        )

    ranked = rank_teams(results)
    short_cfg = config["shortlist"]
    shortlist = build_shortlist(
        ranked,
        top_n=short_cfg["top_n"],
        alternates=short_cfg["alternates"],
        spread_threshold=short_cfg["contested_spread"],
        band_lo=short_cfg["cutoff_band_lo"],
        band_hi=short_cfg["cutoff_band_hi"],
    )

    scorecards = compile_scorecards(ranked)

    from .foreman import write_foreman_artifacts
    from .dialog import append_answer_phase, write_dialog

    for entry in ranked:
        write_dialog(entry, args.out)
    answers_file = getattr(args, "answers", None)
    if answers_file and args.team is not None:
        answers = [line.strip() for line in Path(answers_file).read_text().splitlines() if line.strip()]
        append_answer_phase({"team_number": args.team}, answers, args.out)

    write_foreman_artifacts(ranked, shortlist, args.out)
    state.save(ranked)

    report = {
        "mode": "mock" if args.mock else "live",
        "intake_rows": len(raw_intake),
        "scored_teams": len(results),
        "ignored_resubmissions": ignored_resubmissions,
        "results": [
            {
                "team_number": e["team_number"],
                "rank": e["rank"],
                "status": e["status"],
                "contested": e["contested"],
                "total": e["averages"].get("total"),
                "dropped_judges": e["dropped_judges"],
            }
            for e in ranked
        ],
        "shortlist": [e["team_number"] for e in shortlist["shortlist"]],
        "alternates": [e["team_number"] for e in shortlist["alternates"]],
    }

    out_dir = Path(args.out)
    board.write_judging(ranked, out_dir / "judging.json")
    board.write_shortlist(shortlist, out_dir / "shortlist.json")
    board.write_scorecards(scorecards, out_dir / "scorecards.md")
    board.write_report(report, out_dir / "report.json")

    delivery_dir = out_dir / "delivery"
    delivery_dir.mkdir(parents=True, exist_ok=True)
    for team_number, message in split_scorecards(ranked).items():
        (delivery_dir / f"scorecard_team_{team_number:02d}.txt").write_text(message + "\n")

    print(f"\nshortlist: {report['shortlist']}")
    print(f"alternates: {report['alternates']}")
    print(f"outputs written to {out_dir.resolve()}")
    return 0


def summon_pipeline(args) -> int:
    """The ping event: Judge Lead summons the jury for one team, then shows the dialog."""
    status = run_pipeline(args)
    if status != 0:
        return status
    if args.team is None:
        print("summon requires --team N", file=sys.stderr)
        return 2
    transcript = Path(args.out) / "dialog" / f"team_{args.team:02d}.md"
    if transcript.exists():
        print(f"\n=== Jury dialog — Team {args.team:02d} ===")
        print(transcript.read_text())
    else:
        print(f"no dialog produced for team {args.team}", file=sys.stderr)
    return 0


def render_case_summary(entry: dict, answers: list[str]) -> str:
    summary = {
        "team_number": entry["team_number"],
        "url_smoke": entry.get("url_smoke", {}),
        "sanitization_flags": entry.get("sanitization_flags", []),
        "final_averages": entry.get("averages", {}),
        "spread": entry.get("spread"),
        "contested": entry.get("contested"),
        "juror_scores": [
            {"judge": d.get("judge"), "total": d.get("total"), "evidence": d.get("evidence", [])}
            for d in entry.get("blind_scores", [])
        ],
        "team_answers": answers,
    }
    return json.dumps(summary, indent=2, ensure_ascii=False)


def reflect_pipeline(args) -> int:
    config = load_config(args.config)
    rubric, juror_prompts, foreman_prompt = load_prompts(config)
    client = build_client(config, args.mock)

    judging_path = Path(args.out) / "judging.json"
    if not judging_path.exists():
        print(f"no judging results at {judging_path} — run scoring first", file=sys.stderr)
        return 2
    results = json.loads(judging_path.read_text())
    entry = next((e for e in results if e.get("team_number") == args.team), None)
    if entry is None:
        print(f"team {args.team} not in judging results", file=sys.stderr)
        return 2

    answers = []
    if args.answers:
        answers = [line.strip() for line in Path(args.answers).read_text().splitlines() if line.strip()]

    summary = render_case_summary(entry, answers)
    prompts = dict(juror_prompts)
    if foreman_prompt.strip():
        prompts["foreman"] = foreman_prompt

    docs, dropped = dispatch_reflections(
        summary, client, prompts, retries=config["dispatch"]["retries"], team_number=args.team
    )
    if dropped:
        print(f"reflection pass dropped: {dropped}", file=sys.stderr)

    knowledge_dir = REPO_ROOT / config.get("knowledge", {}).get("dir", "knowledge")
    store = ReflectionStore(knowledge_dir)
    store.add_case(args.team, docs)
    print(f"team {args.team:>3} | reflections {len(docs)}/4 → {store.ledger_path}")
    print(f"lessons rebuilt → {store.lessons_path}")
    return 0


def poll_pipeline(args) -> int:
    cycles = 0
    while True:
        cycles += 1
        print(f"--- poll cycle {cycles} ---", flush=True)
        status = run_pipeline(args)
        if status != 0:
            return status
        if args.cycles and cycles >= args.cycles:
            break
        time.sleep(args.every)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="judging.service", description="Round 1 judging pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="run the full pipeline over an intake file")
    run_parser.add_argument("--intake", required=True, help="intake file (.json list or .csv)")
    run_parser.add_argument("--config", default=str(REPO_ROOT / "config.json"))
    run_parser.add_argument("--out", default=str(REPO_ROOT / "out"))
    run_parser.add_argument("--mock", action="store_true", help="use deterministic mock jurors (no API key)")
    run_parser.add_argument("--skip-network", action="store_true", help="skip URL smoke tests")
    run_parser.add_argument("--team", type=int, default=None, help="canary mode: process only this team number")

    poll_parser = sub.add_parser("poll", help="loop run over a growing intake file (streaming mode)")
    poll_parser.add_argument("--intake", required=True)
    poll_parser.add_argument("--config", default=str(REPO_ROOT / "config.json"))
    poll_parser.add_argument("--out", default=str(REPO_ROOT / "out"))
    poll_parser.add_argument("--mock", action="store_true")
    poll_parser.add_argument("--skip-network", action="store_true")
    poll_parser.add_argument("--every", type=int, default=300, help="seconds between polls (default 300)")
    poll_parser.add_argument("--cycles", type=int, default=0, help="stop after N cycles; 0 = run forever")
    poll_parser.add_argument("--team", type=int, default=None)

    summon_parser = sub.add_parser(
        "summon",
        help="the ping event: run judging for one team and print the visible jury dialog",
    )
    summon_parser.add_argument("--intake", required=True)
    summon_parser.add_argument("--team", type=int, required=True)
    summon_parser.add_argument("--config", default=str(REPO_ROOT / "config.json"))
    summon_parser.add_argument("--out", default=str(REPO_ROOT / "out"))
    summon_parser.add_argument("--mock", action="store_true")
    summon_parser.add_argument("--skip-network", action="store_true")

    answer_parser = sub.add_parser(
        "answer",
        help="append a team's clarifications to their dialog transcript",
    )
    answer_parser.add_argument("--team", type=int, required=True)
    answer_parser.add_argument("--answers", required=True, help="file with the team's answers, one per line")
    answer_parser.add_argument("--out", default=str(REPO_ROOT / "out"))

    reflect_parser = sub.add_parser(
        "reflect",
        help="knowledge loop: post-case reflection pass (3 judges + Foreman meta) → lessons ledger",
    )
    reflect_parser.add_argument("--team", type=int, required=True)
    reflect_parser.add_argument("--answers", default=None, help="optional file with the team's answers, one per line")
    reflect_parser.add_argument("--config", default=str(REPO_ROOT / "config.json"))
    reflect_parser.add_argument("--out", default=str(REPO_ROOT / "out"))
    reflect_parser.add_argument("--mock", action="store_true")

    args = parser.parse_args()
    if args.command == "run":
        return run_pipeline(args)
    if args.command == "poll":
        return poll_pipeline(args)
    if args.command == "summon":
        return summon_pipeline(args)
    if args.command == "reflect":
        return reflect_pipeline(args)
    if args.command == "answer":
        if args.team is None:
            return 2
        answers = [line.strip() for line in Path(args.answers).read_text().splitlines() if line.strip()]
        from .dialog import append_answer_phase

        path = append_answer_phase({"team_number": args.team}, answers, args.out)
        print(f"answers appended to {path}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
