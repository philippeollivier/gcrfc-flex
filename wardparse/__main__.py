"""CLI: python3 -m wardparse <replay.rofl | dir ...> [-o data/wards]

Writes one JSON per replay plus index.json (one summary row per game), which
the viewer at wards/index.html loads.
"""
import argparse
import concurrent.futures
import glob
import json
import os
import time

from .extract import parse_to_file

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
DEFAULT_OUT = os.path.join(REPO, 'data', 'wards')


def summary(game):
    return {
        'matchId': game['matchId'],
        'version': game['version'],
        'gameLength': game['gameLength'],
        'wards': len(game['wards']),
        'countsMatch': game['validation']['countsMatch'],
        'players': [[p['champion'], p['position'], p['team']] for p in game['players']],
    }


ROLES = ['TOP', 'JUNGLE', 'MIDDLE', 'BOTTOM', 'UTILITY']
TYPES = ['trinket', 'stealth', 'control', 'farsight', 'zombie']
ENDS = ['expired', 'replaced', 'killed', 'destroyed', 'game end']


def write_index(out):
    """index.json: one summary row per game. wards.json: every ward of every
    game as compact rows, which is what the map page loads."""
    games = []
    for fn in glob.glob(os.path.join(out, '*.json')):
        if os.path.basename(fn) in ('index.json', 'wards.json', 'scrape_manifest.json'):
            continue
        with open(fn) as f:
            games.append(json.load(f))
    games.sort(key=lambda g: g['matchId'], reverse=True)
    rows = [summary(g) for g in games]
    with open(os.path.join(out, 'index.json'), 'w') as f:
        json.dump(rows, f, separators=(',', ':'))

    cols = ['game', 'placed', 'died', 'x', 'z', 'type', 'team', 'role', 'champion', 'end', 'killer']
    wards = []
    for gi, g in enumerate(games):
        ps = g['players']
        for w in g['wards']:
            if w['owner'] is None:
                continue
            owner = ps[w['owner']]
            role = owner['position'] if owner['position'] in ROLES else ''
            wards.append([gi, round(w['placed']), round(w['placed'] + w['lifetime']), round(w['x']), round(w['z']),
                          TYPES.index(w['type']), owner['team'], ROLES.index(role) if role else -1,
                          owner['champion'], ENDS.index(w['end']),
                          ps[w['killer']]['champion'] if w['killer'] is not None else None])
    with open(os.path.join(out, 'wards.json'), 'w') as f:
        json.dump({'games': [[g['matchId'], g['version'], round(g['gameLength'])] for g in games],
                   'roles': ROLES, 'types': TYPES, 'ends': ENDS, 'cols': cols, 'wards': wards},
                  f, separators=(',', ':'))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('replays', nargs='+', help='.rofl files or directories')
    ap.add_argument('-o', '--out', default=DEFAULT_OUT)
    ap.add_argument('--binary', help='use this arm64 game binary instead of downloading one')
    ap.add_argument('--force', action='store_true', help='re-parse replays that already have output')
    ap.add_argument('-j', '--jobs', type=int, default=3,
                    help='replays to parse in parallel (each needs ~2 GB of memory)')
    args = ap.parse_args(argv)

    paths = []
    for r in args.replays:
        paths += sorted(glob.glob(os.path.join(r, '*.rofl'))) if os.path.isdir(r) else [r]
    os.makedirs(args.out, exist_ok=True)

    todo = []
    for path in paths:
        out_json = os.path.join(args.out, os.path.basename(path).rsplit('.', 1)[0] + '.json')
        if args.force or not os.path.exists(out_json):
            todo.append((path, out_json))
    if todo:
        print('parsing %d replays with %d workers' % (len(todo), args.jobs), flush=True)
    with concurrent.futures.ProcessPoolExecutor(args.jobs) as pool:
        jobs = {pool.submit(parse_to_file, path, out_json, args.binary): path for path, out_json in todo}
        for n, fut in enumerate(concurrent.futures.as_completed(jobs), 1):
            print('[%d/%d] %s: %s' % (n, len(todo), os.path.basename(jobs[fut]), fut.result()), flush=True)

    rows = write_index(args.out)
    print('index: %d games in %s' % (len(rows), os.path.relpath(args.out)))


if __name__ == '__main__':
    main()
