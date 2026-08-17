from .schema import CRITERIA, CRITERIA_MAX, TIEBREAK_ORDER


def average_scores(score_docs: list[dict]) -> dict:
    n = len(score_docs)
    if n == 0:
        return {}
    averages = {}
    for criterion in CRITERIA:
        values = [doc["scores"][criterion] for doc in score_docs]
        averages[criterion] = round(sum(values) / n, 1)
    averages["total"] = round(sum(averages[c] for c in CRITERIA), 1)
    return averages


def juror_spread(score_docs: list[dict]) -> float:
    if len(score_docs) < 2:
        return 0.0
    totals = [doc["total"] for doc in score_docs]
    return round(max(totals) - min(totals), 1)


def rank_teams(results: list[dict], tiebreak_order=TIEBREAK_ORDER) -> list[dict]:
    def sort_key(entry):
        averages = entry["averages"]
        return tuple(-averages.get(c, 0) for c in ("total",) + tiebreak_order)

    return sorted(results, key=sort_key)


def contested(entry: dict, position: int, top_n: int, spread_threshold: float, band_lo: int, band_hi: int) -> bool:
    if entry.get("spread", 0) >= spread_threshold:
        return True
    return band_lo <= position <= band_hi


def build_shortlist(ranked: list[dict], top_n: int, alternates: int, spread_threshold: float, band_lo: int, band_hi: int) -> dict:
    for index, entry in enumerate(ranked, start=1):
        entry["rank"] = index
        entry["contested"] = contested(entry, index, top_n, spread_threshold, band_lo, band_hi)

    shortlist = ranked[:top_n]
    alternate_list = ranked[top_n : top_n + alternates]
    eliminated = ranked[top_n + alternates :]

    for entry in shortlist:
        entry["status"] = "shortlisted"
    for entry in alternate_list:
        entry["status"] = "alternate"
    for entry in eliminated:
        entry["status"] = "eliminated"

    return {"shortlist": shortlist, "alternates": alternate_list, "eliminated": eliminated}
