"""Minimal Riot Games API client (stdlib only).

Reads the key from the RIOT_API_KEY environment variable. Throttles to stay
inside the development/personal limits (20 req/s, 100 req/2 min) and honours
Retry-After on 429.

Usage from another script:
    from riot_api import Riot
    riot = Riot()
    puuid = riot.puuid("Animbot", "naeuk")
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# Platform (league-v4) and regional (account-v1, match-v5) hosts per region.
ROUTING = {
    "na": ("na1", "americas"),
    "br": ("br1", "americas"),
    "lan": ("la1", "americas"),
    "las": ("la2", "americas"),
    "euw": ("euw1", "europe"),
    "eune": ("eun1", "europe"),
    "kr": ("kr", "asia"),
    "oce": ("oc1", "sea"),
}

MIN_INTERVAL = 1.25  # seconds between requests -> at most 96 per 2 minutes


class Riot:
    def __init__(self, key=None):
        self.key = key or os.environ.get("RIOT_API_KEY")
        if not self.key:
            sys.exit("RIOT_API_KEY is not set (export RIOT_API_KEY=RGAPI-...)")
        self._last = 0.0

    def get(self, host, path, **params):
        url = f"https://{host}.api.riotgames.com{path}"
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        for attempt in range(5):
            wait = MIN_INTERVAL - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            req = urllib.request.Request(url, headers={"X-Riot-Token": self.key, "User-Agent": "gcrfc-flex/1.0"})
            self._last = time.monotonic()
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return json.load(resp)
            except urllib.error.HTTPError as err:
                if err.code == 429:
                    time.sleep(int(err.headers.get("Retry-After", "10")))
                    continue
                if err.code == 404:
                    return None
                if err.code in (401, 403):
                    sys.exit(f"Riot API {err.code} for {path}: key missing, expired or invalid")
                if err.code >= 500:
                    time.sleep(5)
                    continue
                raise
        raise RuntimeError(f"Riot API gave up on {path}")

    # --- endpoints -------------------------------------------------------

    def puuid(self, game_name, tag_line, region="na"):
        data = self.get(ROUTING[region][1],
                        f"/riot/account/v1/accounts/by-riot-id/{urllib.parse.quote(game_name)}/{urllib.parse.quote(tag_line)}")
        return data["puuid"] if data else None

    def league_entries(self, puuid, region="na"):
        return self.get(ROUTING[region][0], f"/lol/league/v4/entries/by-puuid/{puuid}") or []

    def match_ids(self, puuid, region="na", queue=None, start_time=None, count=100):
        return self.get(ROUTING[region][1], f"/lol/match/v5/matches/by-puuid/{puuid}/ids",
                        queue=queue, startTime=start_time, count=count) or []

    def match(self, match_id, region="na"):
        return self.get(ROUTING[region][1], f"/lol/match/v5/matches/{match_id}")

    def timeline(self, match_id, region="na"):
        return self.get(ROUTING[region][1], f"/lol/match/v5/matches/{match_id}/timeline")


def split_riot_id(slug):
    """'Animbot-naeuk' -> ('Animbot', 'naeuk'); tag is after the last '-'."""
    name, _, tag = slug.rpartition("-")
    return name, tag
