#!/usr/bin/env python3
import json, sys
from pathlib import Path

team = sys.argv[1] if len(sys.argv) > 1 else "1"
team_str = str(team)
out = Path("/home/oem/hackathon-judging/out")

# 1. out/state.json -> remove teams[team] and filter previous_results
p = out / "state.json"
if p.exists():
    d = json.loads(p.read_text())
    if team_str in d.get("teams", {}):
        del d["teams"][team_str]
        print(f"removed {team_str} from {p} teams")
    if "previous_results" in d:
        before = len(d["previous_results"])
        d["previous_results"] = [r for r in d["previous_results"] if str(r.get("team_number")) != team_str]
        print(f"filtered previous_results {before} -> {len(d['previous_results'])}")
    p.write_text(json.dumps(d, indent=2, ensure_ascii=False))
    print(f"wrote {p}")
else:
    print(f"{p} missing")

# 2. out/discord_state.json -> remove from completed/active
p2 = out / "discord_state.json"
if p2.exists():
    d2 = json.loads(p2.read_text())
    for k in ("completed","active"):
        if team_str in [str(x) for x in d2.get(k,[])] or int(team) in d2.get(k,[]):
            d2[k] = [x for x in d2[k] if str(x) != team_str and x != int(team)]
            print(f"removed {team_str} from {p2} {k}")
    # also handle int vs str
    p2.write_text(json.dumps(d2, indent=2))
    print(f"wrote {p2}")
else:
    print(f"{p2} missing")

# 3. out/judging.json -> filter results (optional, will be regenerated)
for fname in ["judging.json","shortlist.json","report.json","scorecards.md"]:
    pp = out / fname
    if pp.exists() and pp.suffix == ".json":
        try:
            dd = json.loads(pp.read_text())
            # judging.json has previous_results-like list
            if isinstance(dd, dict) and "previous_results" in dd:
                before = len(dd["previous_results"])
                dd["previous_results"] = [r for r in dd["previous_results"] if str(r.get("team_number")) != team_str]
                pp.write_text(json.dumps(dd, indent=2, ensure_ascii=False))
                print(f"cleaned {pp} previous_results")
            elif isinstance(dd, list):
                before = len(dd)
                dd2 = [r for r in dd if str(r.get("team_number")) != team_str]
                if len(dd2) != before:
                    pp.write_text(json.dumps(dd2, indent=2, ensure_ascii=False))
                    print(f"cleaned {pp} list")
        except Exception as e:
            print(f"skip {pp}: {e}")

print(f"Done. Team {team_str} lock removed. Restart judging: sudo systemctl restart judging")
