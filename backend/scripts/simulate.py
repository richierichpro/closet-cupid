"""Run fake users through Cupid and print its report card.

    uv run python scripts/simulate.py            # synthetic catalogue
    uv run python scripts/simulate.py --real     # the real catalogue in data/cupid.db
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cupid import metrics  # noqa: E402
from cupid.engine import ROUND_SIZE, Pool  # noqa: E402
from cupid.simulate import (  # noqa: E402
    PERSONAS, run_session, synthetic_pool, taste_recovered, true_lift, type_precision,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--real", action="store_true", help="use the real catalogue")
    parser.add_argument("--swipes", type=int, default=100)
    parser.add_argument("--seeds", type=int, default=5, help="sessions per persona, averaged")
    args = parser.parse_args()

    if args.real:
        from cupid import db
        pool = Pool(db.load_items(db.connect()))
        print(f"Real catalogue: {len(pool.items)} items")
    else:
        pool = synthetic_pool()
        print(f"Synthetic catalogue: {len(pool.items)} items")
    print("Scored on 300 items Cupid never dealt, against the fake user's true taste.")
    print("Pick-right: shown one item you'd like and one you wouldn't, how often Cupid ranks the liked one higher.")

    for name, persona in PERSONAS.items():
        n = args.seeds
        curve, random_top, best, recovered = None, 0.0, {"pick_right": 0.0, "top_liked": 0.0}, 0.0
        liked_cupid, liked_random, type_hits = {}, {}, []
        lift = true_lift(persona, pool)
        for seed in range(n):
            cupid, result = run_session(persona, pool, args.swipes, seed)
            if curve is None:
                curve = [{"pick_right": 0.0, "top_liked": 0.0} for _ in result["curve"]]
            for agg, point in zip(curve, result["curve"]):
                for k in agg:
                    agg[k] += point[k] / n
            random_top += result["random_top_liked"] / n
            for k in best:
                best[k] += result["best"][k] / n
            recovered += taste_recovered(persona, cupid) / n
            precision = type_precision(persona, cupid, lift)
            if precision is not None:
                type_hits.append(precision)
            for r in metrics.report(cupid.log)["rounds"]:
                liked_cupid[r["round"]] = liked_cupid.get(r["round"], 0) + r["like_rate"] / n
            rand, _ = run_session(persona, pool, args.swipes, seed, feed="random")
            for r in metrics.report(rand.log)["rounds"]:
                liked_random[r["round"]] = liked_random.get(r["round"], 0) + r["like_rate"] / n

        print(f"\n=== {name} ===")
        print(f"Coin flip pick-right: 50%   Best possible: {best['pick_right']:.0%}   "
              f"Random top-20 liked: {random_top:.0%}   Best possible top-20: {best['top_liked']:.0%}")
        print(f"{'after swipes':>12} {'pick-right':>11} {'top-20 liked':>13} {'liked (Cupid deck)':>19} {'liked (random deck)':>20}")
        for i, point in enumerate(curve):
            # Checkpoint i comes right after round i (rounds are numbered from 1).
            liked = f"{liked_cupid[i]:.0%}" if i in liked_cupid else "-"
            rand = f"{liked_random[i]:.0%}" if i in liked_random else "-"
            print(f"{i * ROUND_SIZE:>12} {point['pick_right']:>11.0%} {point['top_liked']:>13.0%} {liked:>19} {rand:>20}")
        print(f"Strong likes/dislikes learned correctly: {recovered:.0%}")
        if type_hits:
            print(f"'Your type' attributes the user really likes: {sum(type_hits) / len(type_hits):.0%}")
        print(f"Your type (last session): {cupid.your_type()['summary'] or '-'}")
        print(f"Cupid's own search: {cupid.write_query()!r}")


if __name__ == "__main__":
    main()
