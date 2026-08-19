#!/usr/bin/env python3
"""Pull current ranks for every player in data/players.json from op.gg
and append one snapshot row per player to data/ranks.jsonl.

Usage:
  scripts/pull_ranks.py            # fetch, print, append to data/ranks.jsonl
  scripts/pull_ranks.py --dry-run  # fetch and print only

Stdlib only. op.gg server-renders the rank cards, so a plain GET is enough;
if op.gg changes its markup the regexes below are what to fix.
"""

import argparse
import datetime
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLAYERS = REPO / "data" / "players.json"
RANKS = REPO / "data" / "ranks.jsonl"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
)
QUEUES = {"flex": "Ranked Flex", "solo": "Ranked Solo/Duo"}


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_queue(doc, label):
    """Return {tier, division, lp, wins, losses} or None if unranked."""
    for m in re.finditer(">" + re.escape(label) + "<", doc):
        window = doc[m.start() : m.start() + 2500]
        rank = re.search(
            r'first-letter:uppercase">([a-z]+) ?(\d?)</strong>'
            r'<span[^>]*>(\d+) LP</span>',
            window,
        )
        if rank:
            wl = re.search(r"(\d+)W (\d+)L", window)
            return {
                "tier": rank.group(1),
                "division": int(rank.group(2)) if rank.group(2) else None,
                "lp": int(rank.group(3)),
                "wins": int(wl.group(1)) if wl else None,
                "losses": int(wl.group(2)) if wl else None,
            }
        if "Unranked" in window[:600]:
            return None
    return None


def pull(player):
    url = f"https://op.gg/summoners/{player['region']}/{player['slug']}"
    doc = fetch(url).replace("<!-- -->", "")
    return {q: parse_queue(doc, label) for q, label in QUEUES.items()}


def fmt(rank):
    if not rank:
        return "unranked"
    div = f" {rank['division']}" if rank["division"] else ""
    return f"{rank['tier'].capitalize()}{div}, {rank['lp']} LP ({rank['wins']}W {rank['losses']}L)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="fetch and print only")
    args = ap.parse_args()

    players = json.loads(PLAYERS.read_text())
    date = datetime.date.today().isoformat()
    rows = []
    for player in players:
        try:
            queues = pull(player)
        except Exception as err:
            print(f"{player['name']:>14}: FAILED ({err})", file=sys.stderr)
            continue
        rows.append({"date": date, "name": player["name"], **queues})
        print(f"{player['name']:>14}: flex {fmt(queues['flex']):<38} solo {fmt(queues['solo'])}")
        time.sleep(1)

    if args.dry_run:
        return
    with RANKS.open("a") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    print(f"\nAppended {len(rows)} rows to {RANKS.relative_to(REPO)}; commit and push to publish.")


if __name__ == "__main__":
    main()
