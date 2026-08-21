"""Record every roster player's ranked games via the Riot API.

Writes one row per (match, player) to data/matches.jsonl, covering Ranked
Flex (queue 440) and Ranked Solo/Duo (420) played since SINCE. Already
recorded games are skipped, so it is safe to run daily. A game several
roster players shared is fetched once and recorded once per player.

    export RIOT_API_KEY=RGAPI-...
    python3 scripts/pull_matches.py
    python3 scripts/pull_matches.py --dry-run
"""
import argparse
import datetime
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from riot_api import Riot  # noqa: E402
from pull_ranks import ensure_puuids  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent
PLAYERS = REPO / "data" / "players.json"
MATCHES = REPO / "data" / "matches.jsonl"
SINCE = datetime.datetime(2026, 8, 19, tzinfo=datetime.timezone.utc)  # tracking start
QUEUES = {440: "flex", 420: "solo"}


def load_existing():
    if not MATCHES.exists():
        return set()
    return {(r["matchId"], r["name"]) for r in map(json.loads, MATCHES.read_text().splitlines()) if r}


def row_for(match, player):
    info = match["info"]
    me = next(p for p in info["participants"] if p["puuid"] == player["puuid"])
    teammates = [p["puuid"] for p in info["participants"] if p["teamId"] == me["teamId"] and p["puuid"] != me["puuid"]]
    start = datetime.datetime.fromtimestamp(info["gameStartTimestamp"] / 1000, datetime.timezone.utc)
    return {
        "matchId": match["metadata"]["matchId"],
        "queue": QUEUES.get(info["queueId"], str(info["queueId"])),
        "start": start.isoformat(timespec="seconds"),
        "duration": info["gameDuration"],
        "patch": ".".join(info["gameVersion"].split(".")[:2]),
        "name": player["name"],
        "champion": me["championName"],
        "position": me["teamPosition"] or me["individualPosition"],
        "win": me["win"],
        "kills": me["kills"],
        "deaths": me["deaths"],
        "assists": me["assists"],
        "cs": me["totalMinionsKilled"] + me["neutralMinionsKilled"],
        "visionScore": me["visionScore"],
        "gold": me["goldEarned"],
        "level": me["champLevel"],
        "side": "blue" if me["teamId"] == 100 else "red",
        "teammates": teammates,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="fetch and print only")
    args = ap.parse_args()

    riot = Riot()
    players = ensure_puuids(riot, json.loads(PLAYERS.read_text()))
    by_puuid = {p["puuid"]: p for p in players}
    existing = load_existing()
    since = int(SINCE.timestamp())

    wanted = {}  # matchId -> [players]
    for player in players:
        region = player.get("region", "na")
        for queue in QUEUES:
            for match_id in riot.match_ids(player["puuid"], region, queue=queue, start_time=since):
                if (match_id, player["name"]) not in existing:
                    wanted.setdefault(match_id, []).append(player)

    new_rows = []
    for match_id, owners in sorted(wanted.items()):
        match = riot.match(match_id, owners[0].get("region", "na"))
        if not match:
            continue
        for player in owners:
            row = row_for(match, player)
            row["teammates"] = [by_puuid[t]["name"] for t in row["teammates"] if t in by_puuid]
            new_rows.append(row)
            print(f"{row['start'][:10]} {row['queue']:<4} {row['name']:>8} {row['champion']:<12} "
                  f"{row['position']:<7} {'W' if row['win'] else 'L'} {row['kills']}/{row['deaths']}/{row['assists']}")

    print(f"\n{len(new_rows)} new rows across {len(wanted)} games.")
    if args.dry_run or not new_rows:
        return
    with MATCHES.open("a") as f:
        for row in sorted(new_rows, key=lambda r: (r["start"], r["matchId"], r["name"])):
            f.write(json.dumps(row) + "\n")
    print(f"Appended to {MATCHES.relative_to(REPO)}; commit and push to publish.")


if __name__ == "__main__":
    main()
