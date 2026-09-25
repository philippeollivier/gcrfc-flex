# GCRFC Flex

Static team site for the GCRFC ranked flex climb. Styles and scripts follow the Steez Sheet (`assets/style.css`, `assets/site.js`).

- `index.html` — flex rank chart + roster
- `data/players.json` — roster config (riot slugs, roles)
- `data/ranks.jsonl` — append-only rank snapshots, one JSON row per player per pull
- `scripts/pull_ranks.py` — fetch current ranks from op.gg and append to `data/ranks.jsonl`

Weekly update: `python3 scripts/pull_ranks.py`, then commit and push. Deployed via GitHub Pages from `main`.

## Ward atlas

`wards/index.html` — every ward each player placed (type, position, how long it lasted, who killed it) on the Summoner's Rift map with a playable timeline. Data comes from `.rofl` replays, parsed by `wardparse/`.

- `python3 -m pip install -r wardparse/requirements.txt` (once)
- `python3 -m wardparse.scrape --challenger 100 --games 5` — with the League client open and logged in, downloads the recent ranked games of the top NA Challenger players through the client, then parses them. Only current-patch replays are downloadable, so run it during each patch. Progress is kept in `data/wards/scrape_manifest.json`.
- `python3 -m wardparse <replay.rofl | folder>` — parse replays you already have into `data/wards/<matchId>.json` + `data/wards/index.json`.
- To view locally, serve the repo (`python3 -m http.server`, then open `/wards/`); opening the file directly can't load the data.

How the parser works: replay packet payloads are obfuscated differently every patch, so the parser downloads that patch's macOS game binary from Riot's CDN (cached in `~/.cache/lol-ward-tracker/`) and runs the game's own packet decoders under the Unicorn CPU emulator. The ward packet types and field layouts are found from the data, not hard-coded. Each parse is checked against the replay's end-of-game stats: placements match `WARD_PLACED` exactly on every game tested so far (patches 16.18 and 16.19).
