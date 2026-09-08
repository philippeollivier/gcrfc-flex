"""One-time LP-history backfill from saved League of Graphs profile pages.

League of Graphs blocks automated access, so the pages must be saved from a
browser (Cmd+S, one per roster player, default filenames). Each page embeds
two rank-history graphs - graphDD1 (solo) and graphDD2 (flex) - as inline
script data: graphData [[ts, y], ...], lpData {ts: lp} and rankData
{ts: {tierRankString, ...}}. Points are snapshots from whenever League of
Graphs refreshed the profile, so coverage is sparse and irregular.

Rows for dates before our own tracking began (2026-08-19) are merged into
data/ranks.jsonl, marked "source": "leagueofgraphs", with wins/losses null
(League of Graphs does not expose historical W/L). Re-running replaces all
previously backfilled rows, so it is idempotent.

    python3 scripts/backfill_lp_leagueofgraphs.py ~/Downloads
"""
import datetime
import json
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
PLAYERS = REPO / "data" / "players.json"
RANKS = REPO / "data" / "ranks.jsonl"
QUEUES = {"graphDD1": "solo", "graphDD2": "flex"}  # page order: solo graph first
SEASON_START_MS = datetime.datetime(2026, 1, 8, 20, tzinfo=datetime.timezone.utc).timestamp() * 1000
OWN_DATA_FROM = "2026-08-19"  # dates >= this come from our daily Riot pulls
DIVISIONS = {"IV": 4, "III": 3, "II": 2, "I": 1}
APEX = {"Master", "Grandmaster", "Challenger"}


def parse_rank(tier_rank_string, lp):
    parts = tier_rank_string.split()
    tier = parts[0]
    if tier not in APEX and (len(parts) != 2 or parts[1] not in DIVISIONS):
        return None  # "Unranked" or other sentinel
    return {
        "tier": tier.lower(),
        "division": None if tier in APEX else DIVISIONS[parts[1]],
        "lp": lp,
        "wins": None,
        "losses": None,
    }


def graph_points(html, graph_id):
    """Yield (utc_date_iso, ts, rank_dict) for one graph's snapshots."""
    anchor = html.find(f"{graph_id}_ranking_history_graph_scale")
    if anchor == -1:
        return
    script = html[html.rfind("<script", 0, anchor):html.find("</script>", anchor)]
    data = json.loads(re.search(r"graphData = (\[.*?\]);", script, re.S).group(1))
    lp_data = json.loads(re.search(r"const lpData = (\{.*?\});", script, re.S).group(1))
    rank_data = json.loads(re.search(r"const rankData = (\{.*?\});", script, re.S).group(1))
    y_at = {str(ts): y for ts, y in data}
    for ts, lp in lp_data.items():
        # Skip series breaks (unranked stretches: null y, sentinel Iron IV 0 LP).
        if y_at.get(ts) is None or ts not in rank_data:
            continue
        rank = parse_rank(rank_data[ts]["tierRankString"], lp)
        if not rank:
            continue
        when = datetime.datetime.fromtimestamp(int(ts) / 1000, datetime.timezone.utc)
        yield when.date().isoformat(), int(ts), rank


def main():
    pages_dir = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".").expanduser()
    players = json.loads(PLAYERS.read_text())

    new_rows = {}  # (date, name) -> row
    for player in players:
        game_name, _, tag = player["slug"].rpartition("-")
        page = pages_dir / f"{game_name}#{tag} (NA) - LeagueOfGraphs.html"
        if not page.exists():
            print(f"{player['name']:>8}: no saved page ({page.name}), skipped")
            continue
        html = page.read_text(encoding="utf-8", errors="replace")
        counts = {}
        for graph_id, queue in QUEUES.items():
            latest = {}  # date -> (ts, rank): keep the last snapshot per day
            for date, ts, rank in graph_points(html, graph_id):
                if SEASON_START_MS <= ts and date < OWN_DATA_FROM and latest.get(date, (0,))[0] < ts:
                    latest[date] = (ts, rank)
            counts[queue] = len(latest)
            for date, (_, rank) in latest.items():
                row = new_rows.setdefault((date, player["name"]),
                                          {"date": date, "name": player["name"], "flex": None,
                                           "solo": None, "source": "leagueofgraphs"})
                row[queue] = rank
        print(f"{player['name']:>8}: {counts.get('solo', 0)} solo days, {counts.get('flex', 0)} flex days")

    kept = [json.loads(line) for line in RANKS.read_text().splitlines()
            if line.strip() and json.loads(line).get("source") != "leagueofgraphs"]
    rows = sorted(kept + list(new_rows.values()), key=lambda r: (r["date"], r["name"]))
    with RANKS.open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    print(f"\nMerged {len(new_rows)} backfilled rows into {RANKS.relative_to(REPO)} ({len(rows)} total).")


if __name__ == "__main__":
    main()
