# GCRFC Flex

Static team site for the GCRFC ranked flex climb. Styles and scripts follow the Steez Sheet (`assets/style.css`, `assets/site.js`).

- `index.html` — flex rank chart + roster
- `data/players.json` — roster config (riot slugs, roles)
- `data/ranks.jsonl` — append-only rank snapshots, one JSON row per player per pull
- `scripts/pull_ranks.py` — fetch current ranks from op.gg and append to `data/ranks.jsonl`

Weekly update: `python3 scripts/pull_ranks.py`, then commit and push. Deployed via GitHub Pages from `main`.

## Ward atlas

`wards/index.html` — where and when high-elo players ward, aggregated over every scraped game. Pick a lane (and team / ward type); the heatmap shows where that lane placed wards in the last 1–5 minutes of game time, with numbered top spots labelled by the share of games that warded there. Red side is mirrored onto blue side so both pool together. The time strip shows when the lane wards (placements per game per 30 s) and when the first dragon, Voidgrubs, Rift Herald and Baron spawn. "Wards" view shows individual placements with who, when, and how long each lasted. Data comes from `.rofl` replays, parsed by `wardparse/`.

- `python3 -m pip install -r wardparse/requirements.txt` (once)
- `python3 -m wardparse.scrape --challenger 100 --games 5` — with the League client open and logged in, downloads the recent ranked games of the top NA Challenger players through the client, then parses them. Only current-patch replays are downloadable, so run it during each patch. Progress is kept in `data/wards/scrape_manifest.json`.
- `python3 -m wardparse <replay.rofl | folder>` — parse replays you already have into `data/wards/<matchId>.json` + `data/wards/index.json`.
- To view locally, serve the repo (`python3 -m http.server`, then open `/wards/`); opening the file directly can't load the data.

How the parser works: replay packet payloads are obfuscated differently every patch, so the parser downloads that patch's macOS game binary from Riot's CDN (cached in `~/.cache/lol-ward-tracker/`) and runs the game's own packet decoders under the Unicorn CPU emulator. The ward packet types and field layouts are found from the data, not hard-coded. Each parse is checked against the replay's end-of-game stats: placements match `WARD_PLACED` exactly for ~99% of players across 170+ games (patches 16.18 and 16.19); the rest are over by one ward, almost always a support.
