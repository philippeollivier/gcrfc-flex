"""Fetch just the missing match-v5 payloads for a filtered set of recorded games.

Filters the rows already in data/matches.jsonl (no match-id listing), so it
is much faster than a full pull_matches.py run - use it to grab payloads for
one player/champion ahead of the regular sweep.

    export RIOT_API_KEY=RGAPI-...
    python3 scripts/pull_payloads.py --player Phil --champion Kaisa --queue solo
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from riot_api import Riot  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent
MATCHES = REPO / "data" / "matches.jsonl"
RAW = REPO / "data" / "matches"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--player")
    ap.add_argument("--champion")
    ap.add_argument("--queue", choices=["solo", "flex"])
    args = ap.parse_args()

    rows = [json.loads(line) for line in MATCHES.read_text().splitlines() if line.strip()]
    wanted = sorted({r["matchId"] for r in rows
                     if (not args.player or r["name"] == args.player)
                     and (not args.champion or r["champion"] == args.champion)
                     and (not args.queue or r["queue"] == args.queue)
                     and not (RAW / f"{r['matchId']}.json").exists()})
    print(f"{len(wanted)} payloads to fetch")
    riot = Riot()
    for match_id in wanted:
        match = riot.match(match_id)
        if match:
            (RAW / f"{match_id}.json").write_text(json.dumps(match, separators=(",", ":")) + "\n")
            print(match_id)


if __name__ == "__main__":
    main()
