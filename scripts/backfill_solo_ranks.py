"""Backfill rank sidecars for solo-queue games already in the repo.

Writes data/matches/<id>.ranks.json (same shape the flex pull produces) for
one roster player's stored solo games. Ranks are as of pull time - Riot has
no historical ranks. Existing sidecars are skipped.

    export RIOT_API_KEY=RGAPI-...
    python3 scripts/backfill_solo_ranks.py --player Phil --wins-only
"""
import argparse
import datetime
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from riot_api import Riot  # noqa: E402
from pull_ranks import entry_to_rank  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent
RAW = REPO / "data" / "matches"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--player", default="Phil")
    ap.add_argument("--wins-only", action="store_true")
    args = ap.parse_args()

    players = json.loads((REPO / "data" / "players.json").read_text())
    player = next(p for p in players if p["name"] == args.player)
    region = player.get("soloRegion", player.get("region", "na"))
    rows = [json.loads(l) for l in (REPO / "data" / "matches.jsonl").read_text().splitlines() if l.strip()]
    games = [r for r in rows if r["name"] == args.player and r["queue"] == "solo" and r["duration"] >= 300
             and (r["win"] or not args.wins_only)]

    riot = Riot()
    done = 0
    for g in games:
        out = RAW / f"{g['matchId']}.ranks.json"
        payload = RAW / f"{g['matchId']}.json"
        if out.exists() or not payload.exists():
            continue
        match = json.loads(payload.read_text())
        standings = []
        for part in match["info"]["participants"]:
            entries = {e["queueType"]: e for e in riot.league_entries(part["puuid"], region)}
            standings.append({
                "puuid": part["puuid"],
                "riotId": f"{part.get('riotIdGameName', '')}#{part.get('riotIdTagline', '')}",
                "teamId": part["teamId"],
                "position": part["teamPosition"] or part["individualPosition"],
                "champion": part["championName"],
                "flex": entry_to_rank(entries.get("RANKED_FLEX_SR")),
                "solo": entry_to_rank(entries.get("RANKED_SOLO_5x5")),
            })
        out.write_text(json.dumps({"matchId": g["matchId"], "pulled": datetime.date.today().isoformat(),
                                   "participants": standings}, separators=(",", ":")) + "\n")
        done += 1
        print(f"{g['start'][:10]} {g['matchId']} sidecar written")

    print(f"\n{done} sidecars written for {args.player}'s solo {'wins' if args.wins_only else 'games'}.")


if __name__ == "__main__":
    main()
