"""Talk to the running League client (LCU) to download replays of any match.

The client exposes a local HTTPS API authenticated by a per-session password
in its lockfile. Riot's replay servers only keep games from the current patch,
so a match from an older patch reports 'missingOrExpired'.
"""
import base64
import json
import os
import re
import ssl
import subprocess
import time
import urllib.error
import urllib.request

LOCKFILES = [
    '/Applications/League of Legends.app/Contents/LoL/lockfile',
    r'C:\Riot Games\League of Legends\lockfile',
]


class ClientNotRunning(Exception):
    pass


def _credentials():
    for path in LOCKFILES:
        if os.path.exists(path):
            _name, _pid, port, password, _proto = open(path).read().strip().split(':')
            return int(port), password
    # fall back to the process command line
    try:
        ps = subprocess.run(['ps', '-A', '-o', 'args'], capture_output=True, text=True).stdout
    except OSError:
        ps = ''
    port = re.search(r'--app-port=(\d+)', ps)
    token = re.search(r'--remoting-auth-token=([\w-]+)', ps)
    if port and token:
        return int(port.group(1)), token.group(1)
    raise ClientNotRunning('League client is not running. Start it and log in, then retry.')


class LeagueClient:
    def __init__(self):
        self.port, password = _credentials()
        self.auth = 'Basic ' + base64.b64encode(('riot:' + password).encode()).decode()
        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE  # the client uses a self-signed cert

    def request(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request('https://127.0.0.1:%d%s' % (self.port, path), data=data, method=method,
                                     headers={'Authorization': self.auth, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, context=self.ctx, timeout=30) as r:
                raw = r.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors='replace')
            raise RuntimeError('%s %s -> HTTP %d %s' % (method, path, e.code, detail)) from None

    def summoner(self):
        return self.request('GET', '/lol-summoner/v1/current-summoner')

    def platform(self):
        """Shard the logged-in account plays on, e.g. 'NA1'."""
        try:
            region = self.request('GET', '/riotclient/region-locale')
            return (region.get('webRegion') or region.get('region') or '').upper()
        except RuntimeError:
            return ''

    def replays_dir(self):
        return self.request('GET', '/lol-replays/v1/rofls/path')

    def replay_state(self, game_id):
        """'checking' | 'download' | 'downloading' | 'watch' | 'missingOrExpired' |
        'incompatible' | 'lost' | 'error' | 'none' (client has no record yet)"""
        try:
            meta = self.request('GET', '/lol-replays/v1/metadata/%d' % game_id)
        except RuntimeError as e:
            if 'HTTP 404' in str(e):
                return 'none', None
            raise
        return (meta or {}).get('state', 'unknown'), meta

    def match_history(self, puuid, count=20):
        """Recent games for any player on this shard (newest first)."""
        r = self.request('GET', '/lol-match-history/v1/products/lol/%s/matches?begIndex=0&endIndex=%d'
                         % (puuid, max(0, count - 1)))
        return r['games']['games']

    def challenger_ladder(self):
        """Solo queue Challenger standings, best first (same ladder op.gg shows)."""
        lad = self.request('GET', '/lol-ranked/v1/apex-leagues/RANKED_SOLO_5x5/CHALLENGER')
        return sorted(lad['divisions'][0]['standings'], key=lambda s: s['position'])

    def download_replay(self, game, timeout=300):
        """Ask the client to download a match-history game's replay; returns the final state."""
        game_id = game['gameId']
        state, _ = self.replay_state(game_id)
        if state == 'none':
            # games you weren't in need a metadata record first (match history does this)
            self.request('POST', '/lol-replays/v1/metadata/%d/create/gameVersion/%s/gameType/%s/queueId/%d'
                         % (game_id, game['gameVersion'], game['gameType'], game['queueId']), {})
            state = 'checking'
        waited = 0
        while state in ('checking', 'unknown', 'none') and waited < 20:
            time.sleep(1)
            waited += 1
            state, _ = self.replay_state(game_id)
        if state == 'watch':
            return state  # already on disk
        if state != 'download':
            return state
        self.request('POST', '/lol-replays/v1/rofls/%d/download/graceful' % game_id,
                     {'componentType': 'replay-button_match-history'})
        start = time.time()
        while time.time() - start < timeout:
            time.sleep(2)
            state, meta = self.replay_state(game_id)
            if state not in ('download', 'downloading', 'checking'):
                return state
        return 'timeout'
