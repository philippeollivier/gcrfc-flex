"""Download replays of top solo queue players' games through the League client,
then parse them.

  python3 -m wardparse.scrape --challenger 100 --games 5

Everything goes through the running League client (no game is launched and
no Riot API key is needed): the Challenger ladder, each player's match
history, and the replay downloads. Only current-patch games can be
downloaded; older ones come back 'missingOrExpired'.
"""
import argparse
import json
import os
import time

from .__main__ import DEFAULT_OUT
from .lcu import ClientNotRunning, LeagueClient

RANKED_SOLO = 420
MANIFEST = os.path.join(DEFAULT_OUT, 'scrape_manifest.json')


def load_manifest():
    try:
        with open(MANIFEST) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {'ladder': {}, 'games': {}}


def save_manifest(m):
    os.makedirs(os.path.dirname(MANIFEST), exist_ok=True)
    with open(MANIFEST, 'w') as f:
        json.dump(m, f, indent=1)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--challenger', type=int, default=100, help='top N players on the Challenger ladder')
    ap.add_argument('--games', type=int, default=5, help='most recent ranked solo games per player')
    ap.add_argument('--no-parse', action='store_true', help='download only')
    args = ap.parse_args(argv)

    try:
        lcu = LeagueClient()
    except ClientNotRunning as e:
        raise SystemExit(str(e))
    me = lcu.summoner()
    print('League client: logged in as %s#%s' % (me.get('gameName'), me.get('tagLine')), flush=True)
    replays_dir = lcu.replays_dir()

    manifest = load_manifest()
    ladder = lcu.challenger_ladder()[:args.challenger]
    counts = {}
    for rank in ladder:
        puuid = rank['puuid']
        manifest['ladder'][puuid] = {'position': rank['position'], 'lp': rank['leaguePoints'],
                                     'checked': time.strftime('%Y-%m-%d')}
        try:
            history = lcu.match_history(puuid, args.games * 3)
        except RuntimeError as e:
            print('#%d: match history failed: %s' % (rank['position'], e), flush=True)
            continue
        games = [g for g in history if g['queueId'] == RANKED_SOLO][:args.games]
        me_in = next((pi['player'] for g in games for pi in g['participantIdentities']
                      if pi['player'].get('puuid') == puuid), {})
        name = '%s#%s' % (me_in.get('gameName', '?'), me_in.get('tagLine', '?'))
        manifest['ladder'][puuid]['riotId'] = name
        print('#%d %s (%d LP): %d ranked games' % (rank['position'], name, rank['leaguePoints'], len(games)), flush=True)
        for g in games:
            key = '%s_%d' % (g['platformId'], g['gameId'])
            entry = manifest['games'].setdefault(key, {'ladderPlayers': [], 'version': g['gameVersion']})
            if puuid not in entry['ladderPlayers']:
                entry['ladderPlayers'].append(puuid)
            if entry.get('state') != 'watch':
                t = time.time()
                try:
                    entry['state'] = lcu.download_replay(g)
                except RuntimeError as e:
                    entry['state'] = 'error: %s' % str(e)[:200]
                entry['file'] = os.path.join(replays_dir, '%s-%d.rofl' % (g['platformId'], g['gameId']))
                print('   %s %s -> %s (%.0fs)' % (key, g['gameVersion'], entry['state'], time.time() - t), flush=True)
            counts[entry['state']] = counts.get(entry['state'], 0) + 1
        save_manifest(manifest)

    states = {}
    for e in manifest['games'].values():
        states[e['state']] = states.get(e['state'], 0) + 1
    print('\nall games so far:', ', '.join('%s: %d' % kv for kv in sorted(states.items())), flush=True)

    ready = [e['file'] for e in manifest['games'].values() if e.get('state') == 'watch' and os.path.exists(e['file'])]
    if ready and not args.no_parse:
        from .__main__ import main as parse_main
        print('parsing %d replays (already-parsed ones are skipped)' % len(ready), flush=True)
        parse_main(ready)


if __name__ == '__main__':
    main()
