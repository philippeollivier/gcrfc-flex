# GCRFC Flex

Static team site for the GCRFC ranked flex climb. Styles and scripts follow the Steez Sheet (`assets/style.css`, `assets/site.js`).

- `index.html` — flex rank chart + roster
- `data/players.json` — roster config (riot slugs, roles)
- `data/ranks.jsonl` — append-only rank snapshots, one JSON row per player per pull
- `scripts/pull_ranks.py` — fetch current ranks from op.gg and append to `data/ranks.jsonl`

Weekly update: `python3 scripts/pull_ranks.py`, then commit and push. Deployed via GitHub Pages from `main`.
