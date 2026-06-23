"""
align_timeline.py — deterministic donation-before-vote check.

Given a list of donations and a list of votes, returns each vote annotated
with which donations predated it, which postdated it, and which fall within
a 90-day look-back window (the strongest proximity signal).

Usage (from the agent or interactively):

    from skills.conflict_of_interest_report.scripts.align_timeline import align

    result = align(donations, votes)
    for entry in result:
        print(entry["division_title"], entry["strength"])

Input shapes:

    donations: list of dicts with at minimum:
        {
            "date": "YYYY-MM-DD",     # acceptance date
            "amount": float,
            "donor": str,
            "party": str,             # or "personal" for Register interests
            "source": str,            # "interests" | "party_donations"
        }

    votes: list of dicts with at minimum:
        {
            "date": "YYYY-MM-DD",     # division date
            "division_title": str,
            "vote": str,              # "Aye" | "No" | "Abstain" | "Teller"
        }

Output: list of dicts — one per vote — with donations bucketed by timing.
"""

from __future__ import annotations

from datetime import date, timedelta

WINDOW_DAYS = 90  # donations within this window before a vote are the strongest signal


def _parse(d: str | date) -> date:
    if isinstance(d, date):
        return d
    return date.fromisoformat(d[:10])


def align(donations: list[dict], votes: list[dict]) -> list[dict]:
    """
    Annotate each vote with donations bucketed by timing relative to that vote.

    Returns one entry per vote with:
      - before_window  : donations > WINDOW_DAYS before the vote (historic, weaker signal)
      - in_window      : donations within WINDOW_DAYS before the vote (strong signal)
      - after          : donations after the vote (cannot have influenced it — exclude)
      - strength       : "strong" | "moderate" | "weak" | "none"
    """
    results = []
    for vote in votes:
        vote_date = _parse(vote["date"])
        window_start = vote_date - timedelta(days=WINDOW_DAYS)

        before_window, in_window, after = [], [], []

        for donation in donations:
            donation_date = _parse(donation["date"])
            if donation_date > vote_date:
                after.append(donation)
            elif donation_date >= window_start:
                in_window.append(donation)
            else:
                before_window.append(donation)

        strength = _score(in_window, before_window)

        results.append({
            "division_title": vote.get("division_title", ""),
            "vote_date":      str(vote_date),
            "vote":           vote.get("vote", ""),
            "in_window":      in_window,
            "before_window":  before_window,
            "after":          after,
            "strength":       strength,
        })

    # Sort strongest signals first
    order = {"strong": 0, "moderate": 1, "weak": 2, "none": 3}
    results.sort(key=lambda r: order[r["strength"]])
    return results


def _score(in_window: list[dict], before_window: list[dict]) -> str:
    """
    Assign a conflict-strength label based on donation timing.

    strong   — personal donation within the window
    moderate — party donation within window, or personal donation before window
    weak     — party donation before window only
    none     — no donations predate the vote
    """
    if not in_window and not before_window:
        return "none"

    personal_in_window = [d for d in in_window if d.get("source") == "interests"]
    party_in_window    = [d for d in in_window if d.get("source") == "party_donations"]
    personal_historic  = [d for d in before_window if d.get("source") == "interests"]

    if personal_in_window:
        return "strong"
    if party_in_window or personal_historic:
        return "moderate"
    return "weak"


def summarise(aligned: list[dict]) -> str:
    """Return a plain-text summary of the alignment results."""
    lines = []
    for entry in aligned:
        if entry["strength"] == "none":
            continue
        lines.append(
            f"[{entry['strength'].upper()}] {entry['division_title']} "
            f"({entry['vote_date']}, voted {entry['vote']}) — "
            f"{len(entry['in_window'])} donation(s) within {WINDOW_DAYS} days before, "
            f"{len(entry['before_window'])} historic, "
            f"{len(entry['after'])} postdating (excluded)"
        )
    return "\n".join(lines) if lines else "No pre-vote donations found."
