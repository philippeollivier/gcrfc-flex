"""Winrate by support champion for one player on one champion (solo queue).

Reads only files already in the repo (data/matches.jsonl plus the stored
match-v5 payloads in data/matches/) - no API calls. Remakes (sub-5-minute
games) are excluded, matching the site's records.

    python3 scripts/support_winrates.py                    # Phil on Kaisa
    python3 scripts/support_winrates.py --player Erica --champion Nami
"""
import argparse
import collections
import json
import pathlib

REPO = pathlib.Path(__file__).resolve().parent.parent
PLAYERS = REPO / "data" / "players.json"
MATCHES = REPO / "data" / "matches.jsonl"
RAW = REPO / "data" / "matches"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--player", default="Phil")
    ap.add_argument("--champion", default="Kaisa", help="Riot championName, e.g. Kaisa, MissFortune")
    ap.add_argument("--queue", default="solo", choices=["solo", "flex"])
    args = ap.parse_args()

    players = json.loads(PLAYERS.read_text())
    puuid = next(p["puuid"] for p in players if p["name"] == args.player)
    rows = [json.loads(line) for line in MATCHES.read_text().splitlines() if line.strip()]
    games = [r for r in rows if r["name"] == args.player and r["queue"] == args.queue
             and r["champion"] == args.champion and r["duration"] >= 300]

    by_support = collections.defaultdict(lambda: [0, 0])  # champion -> [wins, losses]
    missing = 0
    for game in games:
        payload = RAW / f"{game['matchId']}.json"
        if not payload.exists():
            missing += 1
            continue
        parts = json.loads(payload.read_text())["info"]["participants"]
        me = next(p for p in parts if p["puuid"] == puuid)
        support = next((p for p in parts if p["teamId"] == me["teamId"] and p["puuid"] != me["puuid"]
                        and p["teamPosition"] == "UTILITY"), None)
        champ = support["championName"] if support else "(no support)"
        by_support[champ][0 if game["win"] else 1] += 1

    print(f"{args.player} on {args.champion}, {args.queue} queue "
          f"({len(games) - missing} games{f'; {missing} missing payloads' if missing else ''}, remakes excluded)\n")
    print(f"{'Support':<14} {'Games':>5} {'WR':>6} {'Wins':>4} {'Losses':>6}")
    ranked = sorted(by_support.items(), key=lambda kv: (-(kv[1][0] / sum(kv[1])), -sum(kv[1])))
    for champ, (wins, losses) in ranked:
        total = wins + losses
        print(f"{champ:<14} {total:>5} {wins / total:>6.0%} {wins:>4} {losses:>6}")


if __name__ == "__main__":
    main()
