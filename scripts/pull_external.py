"""Pull one non-roster account's ranked games for ad-hoc analysis.

Nothing here feeds the site: everything lands under data/external/<slug>/,
mirroring the main dataset's shapes so the same analysis scripts work.
  data/external/<slug>/matches.jsonl     one summary row per game
  data/external/<slug>/matches/<id>.json Riot's complete match-v5 payload
Already stored files are skipped, so reruns are cheap.

    export RIOT_API_KEY=RGAPI-...
    python3 scripts/pull_external.py --riot-id "Duckies Kingdom#5693" --region oce
"""
import argparse
import datetime
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from riot_api import Riot  # noqa: E402
from pull_matches import SINCE, QUEUES, row_for  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent
EXTERNAL = REPO / "data" / "external"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--riot-id", required=True, help='e.g. "Duckies Kingdom#5693"')
    ap.add_argument("--region", default="na")
    args = ap.parse_args()

    name, _, tag = args.riot_id.rpartition("#")
    slug = f"{name}-{tag}".replace(" ", "")
    base = EXTERNAL / slug
    matches_file = base / "matches.jsonl"
    raw_dir = base / "matches"

    riot = Riot()
    puuid = riot.puuid(name, tag, args.region)
    if not puuid:
        sys.exit(f"No account found for {args.riot_id} on {args.region}")

    existing = set()
    if matches_file.exists():
        existing = {json.loads(l)["matchId"] for l in matches_file.read_text().splitlines() if l.strip()}

    since = int(SINCE.timestamp())
    player = {"name": name}
    new_rows, new_raw = [], 0
    for queue in QUEUES:
        for match_id in riot.match_ids(puuid, args.region, queue=queue, start_time=since):
            raw_path = raw_dir / f"{match_id}.json"
            if match_id in existing and raw_path.exists():
                continue
            match = riot.match(match_id, args.region)
            if not match:
                continue
            if not raw_path.exists():
                raw_dir.mkdir(parents=True, exist_ok=True)
                raw_path.write_text(json.dumps(match, separators=(",", ":")) + "\n")
                new_raw += 1
            if match_id not in existing:
                row = row_for(match, player, puuid)
                row["teammates"] = []  # roster names don't apply here
                new_rows.append(row)
                print(f"{row['start'][:10]} {row['queue']:<4} {row['champion']:<12} "
                      f"{row['position']:<7} {'W' if row['win'] else 'L'} {row['kills']}/{row['deaths']}/{row['assists']}")

    print(f"\n{len(new_rows)} new games, {new_raw} payloads for {args.riot_id} ({args.region}).")
    if new_rows:
        base.mkdir(parents=True, exist_ok=True)
        with matches_file.open("a") as f:
            for row in sorted(new_rows, key=lambda r: (r["start"], r["matchId"])):
                f.write(json.dumps(row) + "\n")


if __name__ == "__main__":
    main()
