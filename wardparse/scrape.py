"""Download replays of top solo queue players' games through the League client,
parsing each one as soon as it lands.

  python3 -m wardparse.scrape --challenger 100 --games 10

Everything goes through the running League client (no game is launched and
no Riot API key is needed): the Challenger ladder, each player's match
history, and the replay downloads. Only current-patch replays can be
downloaded (the client calls older ones 'incompatible'), so each player's
most recent current-patch games are used.

Safe to stop at any time (Ctrl-C): progress is saved after every game, every
finished parse is kept, and the page data is rebuilt on the way out. Running
it again resumes, skipping replays already downloaded or parsed.
"""
import argparse
import concurrent.futures
import json
import os
import signal
import time

from .__main__ import DEFAULT_OUT, write_index
from .extract import parse_to_file, write_json_atomic
from .gamebinary import get_binary
from .lcu import ClientNotRunning, LeagueClient

RANKED_SOLO = 420
MANIFEST = os.path.join(DEFAULT_OUT, 'scrape_manifest.json')
HISTORY_PAGE = 20
HISTORY_MAX = 100  # how far back to page through a player's history


def load_manifest():
    try:
        with open(MANIFEST) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {'ladder': {}, 'games': {}}


def save_manifest(m):
    os.makedirs(os.path.dirname(MANIFEST), exist_ok=True)
    write_json_atomic(MANIFEST, m, indent=1)


def _ignore_sigint():
    # Workers ignore Ctrl-C; the main process stops them cleanly instead.
    signal.signal(signal.SIGINT, signal.SIG_IGN)


def recent_ranked(lcu, puuid, patch, want):
    """Up to `want` current-patch ranked solo games, newest first. History mixes
    in other queues, so page back until we have enough or reach an older patch."""
    history, games = [], []
    for begin in range(0, HISTORY_MAX, HISTORY_PAGE):
        page = lcu.match_history(puuid, HISTORY_PAGE, begin)
        history += page
        games += [g for g in page if g['queueId'] == RANKED_SOLO and g['gameVersion'].startswith(patch + '.')]
        older = any(not g['gameVersion'].startswith(patch + '.') for g in page)
        if len(games) >= want or len(page) < HISTORY_PAGE or older:
            break
    return history, games[:want]


class Parser:
    """Parses downloaded replays in background worker processes."""

    def __init__(self, jobs):
        self.pool = concurrent.futures.ProcessPoolExecutor(jobs, initializer=_ignore_sigint)
        self.pending = {}
        self.binaries = set()
        self.rejected = set()  # replays that failed or were skipped (e.g. remakes) this run
        self.done = self.failed = 0

    def submit(self, path, version):
        out = os.path.join(DEFAULT_OUT, os.path.basename(path).rsplit('.', 1)[0] + '.json')
        if os.path.exists(out) or path in self.rejected or path in self.pending.values():
            return
        if version not in self.binaries:  # fetch once here so workers don't race to download it
            get_binary(version, log=lambda *a: None)
            self.binaries.add(version)
        self.pending[self.pool.submit(parse_to_file, path, out)] = path

    def collect(self, block=False):
        if not self.pending:
            return
        done, _ = concurrent.futures.wait(self.pending, timeout=None if block else 0)
        for fut in done:
            path = self.pending.pop(fut)
            try:
                msg = fut.result()
            except Exception as e:  # a worker crash shouldn't stop the run
                msg = 'failed: %s' % e
            if msg.startswith('failed'):
                self.failed += 1
                self.rejected.add(path)
            else:
                self.done += 1
            print('   parsed %s: %s' % (os.path.basename(path), msg), flush=True)

    def close(self, finish):
        if not finish:
            # drop queued work; parses already running finish (their output is written atomically)
            for fut in list(self.pending):
                if fut.cancel():
                    self.pending.pop(fut)
        self.collect(block=True)
        self.pool.shutdown(wait=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--challenger', type=int, default=100, help='top N players on the Challenger ladder')
    ap.add_argument('--games', type=int, default=10, help='most recent ranked solo games per player')
    ap.add_argument('-j', '--jobs', type=int, default=3, help='replays to parse in parallel (~2 GB memory each)')
    ap.add_argument('--no-parse', action='store_true', help='download only')
    args = ap.parse_args(argv)

    try:
        lcu = LeagueClient()
        me = lcu.summoner()
    except ClientNotRunning as e:
        raise SystemExit(str(e))
    replays_dir = lcu.replays_dir()
    patch = lcu.current_patch()
    print('League client: logged in as %s#%s; current patch %s' % (me.get('gameName'), me.get('tagLine'), patch),
          flush=True)

    manifest = load_manifest()
    parser = None if args.no_parse else Parser(args.jobs)
    downloaded = 0
    interrupted = False
    try:
        # replays downloaded by an earlier, interrupted run but never parsed
        if parser:
            for e in manifest['games'].values():
                if e.get('state') == 'watch' and os.path.exists(e.get('file', '')):
                    parser.submit(e['file'], e['version'])

        for rank in lcu.challenger_ladder()[:args.challenger]:
            puuid = rank['puuid']
            manifest['ladder'][puuid] = {'position': rank['position'], 'lp': rank['leaguePoints'],
                                         'checked': time.strftime('%Y-%m-%d')}
            try:
                history, games = recent_ranked(lcu, puuid, patch, args.games)
            except RuntimeError as e:
                print('#%d: match history failed: %s' % (rank['position'], e), flush=True)
                continue
            me_in = next((pi['player'] for g in history for pi in g['participantIdentities']
                          if pi['player'].get('puuid') == puuid), {})
            manifest['ladder'][puuid]['riotId'] = '%s#%s' % (me_in.get('gameName', '?'), me_in.get('tagLine', '?'))
            print('#%d %s (%d LP): %d ranked games on %s'
                  % (rank['position'], manifest['ladder'][puuid]['riotId'], rank['leaguePoints'], len(games), patch),
                  flush=True)
            for g in games:
                key = '%s_%d' % (g['platformId'], g['gameId'])
                entry = manifest['games'].setdefault(key, {'ladderPlayers': [], 'version': g['gameVersion']})
                if puuid not in entry['ladderPlayers']:
                    entry['ladderPlayers'].append(puuid)
                entry['file'] = os.path.join(replays_dir, '%s-%d.rofl' % (g['platformId'], g['gameId']))
                if entry.get('state') not in ('watch', 'incompatible', 'missingOrExpired'):
                    t = time.time()
                    try:
                        entry['state'] = lcu.download_replay(g)
                    except RuntimeError as e:
                        entry['state'] = 'error: %s' % str(e)[:200]
                    print('   %s -> %s (%.0fs)' % (key, entry['state'], time.time() - t), flush=True)
                    if entry['state'] == 'watch':
                        downloaded += 1
                save_manifest(manifest)
                if parser and entry['state'] == 'watch' and os.path.exists(entry['file']):
                    parser.submit(entry['file'], entry['version'])
                if parser:
                    parser.collect()
            if parser:
                write_index(DEFAULT_OUT)  # keep the page data current as we go
    except (KeyboardInterrupt, ClientNotRunning) as e:
        interrupted = True
        why = 'interrupted' if isinstance(e, KeyboardInterrupt) else str(e)
        print('\nstopping (%s): keeping everything finished so far...' % why, flush=True)
    finally:
        save_manifest(manifest)
        if parser:
            parser.close(finish=not interrupted)
        rows = write_index(DEFAULT_OUT)
        states = {}
        for e in manifest['games'].values():
            st = e.get('state', 'not downloaded')  # a stop can land mid-download
            states[st] = states.get(st, 0) + 1
        print('\nthis run: %d new replays downloaded%s' % (
            downloaded, ', %d parsed, %d failed' % (parser.done, parser.failed) if parser else ''))
        print('all replays: %s' % ', '.join('%s: %d' % kv for kv in sorted(states.items())))
        print('page data: %d games in %s' % (len(rows), os.path.relpath(DEFAULT_OUT)))
        if interrupted:
            print('run the same command again to resume.')


if __name__ == '__main__':
    main()
