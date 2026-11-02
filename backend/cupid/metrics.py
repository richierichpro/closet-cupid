"""Cupid's report card: proof the engine is learning, not just looking like it.

Every number is scored on Cupid's guess *before* it saw the swipe, so it can't
be faked by learning from the answer.
"""

from .engine import Swipe

CAL_BUCKETS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01)]


def report(log: list[Swipe]) -> dict:
    rounds: dict[int, list[Swipe]] = {}
    for s in log:
        rounds.setdefault(s.round, []).append(s)

    # Baseline guesser: always predicts whatever answer has been more common so far.
    likes = seen = 0
    baseline_hits: dict[int, int] = {}
    for s in log:
        guess_like = seen > 0 and likes / seen > 0.5
        baseline_hits[s.round] = baseline_hits.get(s.round, 0) + (guess_like == s.liked)
        likes += s.liked
        seen += 1

    def rate(swipes):
        return sum(s.liked for s in swipes) / len(swipes) if swipes else None

    per_round = []
    for r, swipes in sorted(rounds.items()):
        n = len(swipes)
        per_round.append({
            # Random cards are the control group: Cupid's picks should beat them.
            "cupid_like_rate": rate([s for s in swipes if s.slot != "random"]),
            "random_like_rate": rate([s for s in swipes if s.slot == "random"]),
            "round": r + 1,
            "swipes": n,
            "accuracy": sum(s.correct for s in swipes) / n,
            "baseline_accuracy": baseline_hits[r] / n,
            "like_rate": sum(s.liked for s in swipes) / n,
            "brier": sum((s.p_before - s.liked) ** 2 for s in swipes) / n,
        })

    slots: dict[str, dict] = {}
    for s in log:
        d = slots.setdefault(s.slot, {"n": 0, "likes": 0})
        d["n"] += 1
        d["likes"] += s.liked
    for d in slots.values():
        d["like_rate"] = d["likes"] / d["n"]

    calibration = []
    for lo, hi in CAL_BUCKETS:
        inside = [s for s in log if lo <= s.p_before < hi]
        if inside:
            calibration.append({
                "bucket": f"{int(lo * 100)}-{min(int(hi * 100), 100)}%",
                "n": len(inside),
                "predicted": sum(s.p_before for s in inside) / len(inside),
                "actual": sum(s.liked for s in inside) / len(inside),
            })

    return {"rounds": per_round, "slots": slots, "calibration": calibration}
