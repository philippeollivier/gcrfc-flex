"""Snapshot every roster player's ranked standing via the Riot API.

Appends one row per player for today to data/ranks.jsonl (a same-day re-run
replaces that day's rows). Caches each player's puuid in data/players.json.

    export RIOT_API_KEY=RGAPI-...
    python3 scripts/pull_ranks.py            # write rows
    python3 scripts/pull_ranks.py --dry-run  # fetch and print only
"""
import argparse
import datetime
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from riot_api import Riot, split_riot_id  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent
PLAYERS = REPO / "data" / "players.json"
RANKS = REPO / "data" / "ranks.jsonl"
QUEUES = {"flex": "RANKED_FLEX_SR", "solo": "RANKED_SOLO_5x5"}
DIVISIONS = {"I": 1, "II": 2, "III": 3, "IV": 4}
APEX = {"MASTER", "GRANDMASTER", "CHALLENGER"}


def ensure_puuids(riot, players):
    changed = False
    for player in players:
        if not player.get("puuid"):
            name, tag = split_riot_id(player["slug"])
            player["puuid"] = riot.puuid(name, tag, player.get("region", "na"))
            changed = True
    if changed:
        PLAYERS.write_text(json.dumps(players, indent=2) + "\n")
    return players


def entry_to_rank(entry):
    if not entry:
        return None
    tier = entry["tier"]
    return {
        "tier": tier.lower(),
        "division": None if tier in APEX else DIVISIONS[entry["rank"]],
        "lp": entry["leaguePoints"],
        "wins": entry["wins"],
        "losses": entry["losses"],
    }


def pull(riot, player):
    entries = {e["queueType"]: e for e in riot.league_entries(player["puuid"], player.get("region", "na"))}
    return {q: entry_to_rank(entries.get(qt)) for q, qt in QUEUES.items()}


def fmt(rank):
    if not rank:
        return "unranked"
    div = f" {rank['division']}" if rank["division"] else ""
    return f"{rank['tier'].capitalize()}{div}, {rank['lp']} LP ({rank['wins']}W {rank['losses']}L)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="fetch and print only")
    args = ap.parse_args()

    riot = Riot()
    players = ensure_puuids(riot, json.loads(PLAYERS.read_text()))
    date = datetime.date.today().isoformat()
    rows = []
    for player in players:
        try:
            queues = pull(riot, player)
        except Exception as err:
            print(f"{player['name']:>14}: FAILED ({err})", file=sys.stderr)
            continue
        rows.append({"date": date, "name": player["name"], **queues})
        print(f"{player['name']:>14}: flex {fmt(queues['flex']):<38} solo {fmt(queues['solo'])}")

    if args.dry_run:
        return
    # One snapshot per day: a same-day re-run replaces that day's rows.
    kept = [line for line in RANKS.read_text().splitlines()
            if line.strip() and json.loads(line)["date"] != date] if RANKS.exists() else []
    with RANKS.open("w") as f:
        for line in kept:
            f.write(line + "\n")
        for row in rows:
            f.write(json.dumps(row) + "\n")
    print(f"\nWrote {len(rows)} rows for {date} to {RANKS.relative_to(REPO)}; commit and push to publish.")


if __name__ == "__main__":
    main()
