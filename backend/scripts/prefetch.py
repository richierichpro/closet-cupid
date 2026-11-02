"""Pre-cache answers to "what are you looking for?" before a demo, so nothing is fetched on stage.

Each answer + occasion is one Amazon search the first time, then free forever.

    uv run python scripts/prefetch.py                              # show what's cached
    uv run python scripts/prefetch.py dresses                      # everyday dresses (asks first)
    uv run python scripts/prefetch.py dresses --for date wedding   # dresses for date night and for weddings
    uv run python scripts/prefetch.py dresses --for date wedding work party everyday --pages 2   # the demo catalogue
"""

import argparse
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cupid import catalogue, db  # noqa: E402
from cupid.amazon import LOOKING_FOR, OCCASION_WORDS, answer_search  # noqa: E402
from cupid.config import SERPAPI_DAILY_LIMIT  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("answers", nargs="*", metavar="ANSWER", help=f"any of: {', '.join(LOOKING_FOR)}")
    parser.add_argument("--for", dest="occasions", nargs="+", default=["everyday"], metavar="OCCASION",
                        help=f"any of: {', '.join(OCCASION_WORDS)} (default: everyday)")
    parser.add_argument("--pages", type=int, default=1, help="result pages per search (about 48 items each)")
    parser.add_argument("--yes", action="store_true", help="don't ask before spending SerpAPI calls")
    args = parser.parse_args()
    unknown = [a for a in args.answers if a not in LOOKING_FOR] + [o for o in args.occasions if o not in OCCASION_WORDS]
    if unknown:
        parser.error(f"unknown {unknown}; answers: {', '.join(LOOKING_FOR)}; occasions: {', '.join(OCCASION_WORDS)}")

    conn = db.connect()
    for occasion in OCCASION_WORDS:
        cached = [a for a in LOOKING_FOR if db.get_search(conn, answer_search(a, occasion).key())]
        print(f"  {occasion:9} cached: {', '.join(cached) or '-'}")
    if not args.answers:
        return

    todo = [replace(answer_search(a, o), page=p) for a in args.answers for o in args.occasions
            for p in range(1, args.pages + 1)]
    for s in todo:
        print(f"  → {s.k} (page {s.page})")
    new_calls = sum(db.get_search(conn, s.key()) is None for s in todo)
    print(f"\n{len(todo)} answers: {new_calls} real SerpAPI calls. Used in the last 24h: "
          f"{db.calls_last_24h(conn)}/{SERPAPI_DAILY_LIMIT}.")
    if new_calls and not args.yes and input(f"Spend {new_calls} SerpAPI calls? [y/N] ").strip().lower() != "y":
        print("Nothing spent.")
        return

    from cupid.vision import FashionEncoder
    report = catalogue.ingest(conn, todo, FashionEncoder())
    total = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    print(f"\n{report.added} new items ({report.duplicates} duplicates merged). Catalogue: {total} items. "
          f"SerpAPI calls in the last 24h: {db.calls_last_24h(conn)}/{SERPAPI_DAILY_LIMIT}.")


if __name__ == "__main__":
    main()
