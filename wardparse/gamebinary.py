"""Fetch (and cache) the League macOS game binary matching a replay's patch.

Replay packet payloads are obfuscated differently on every patch, and the only
thing that knows how to read them is that patch's game client. Riot's patcher
manifests for old builds are archived at github.com/Morilli/riot-manifests, so
we can pull the exact binary straight from Riot's CDN without touching (or
even having) a local install.
"""
import os
import urllib.error
import urllib.request

from . import rman

CACHE = os.path.expanduser('~/.cache/lol-ward-tracker/binaries')
MANIFEST_INDEX = ('https://raw.githubusercontent.com/Morilli/riot-manifests/master/'
                  'LoL/{region}/macos/lol-game-client/{version}.txt')
REGIONS = ['NA1', 'EUW1', 'KR', 'EUN1', 'BR1', 'LA1', 'LA2', 'OC1', 'JP1', 'TR1', 'RU',
           'PBE1', 'SG2', 'TW2', 'VN2', 'TH2', 'PH2', 'ME1']
LOCAL_INSTALL = '/Applications/League of Legends.app/Contents/LoL/Game'


def build_version(replay_version):
    """'16.18.817.5716' (replay header) -> '16.18.8175716' (patcher build)."""
    parts = replay_version.split('.')
    return '.'.join(parts[:2]) + '.' + ''.join(parts[2:])


def _local_install_version():
    try:
        import json
        with open(os.path.join(LOCAL_INSTALL, 'code-metadata.json')) as f:
            return json.load(f)['version'].split('+')[0]
    except (OSError, ValueError, KeyError):
        return None


def _extract_arm64(fat, out):
    """Pull the arm64 slice out of a universal Mach-O (pure Python, so this
    also works off-macOS)."""
    import struct
    with open(fat, 'rb') as f:
        data = f.read()
    magic = struct.unpack_from('>I', data, 0)[0]
    if magic != 0xcafebabe:
        with open(out, 'wb') as f:
            f.write(data)
        return
    n = struct.unpack_from('>I', data, 4)[0]
    for i in range(n):
        cputype, _sub, off, size, _align = struct.unpack_from('>iiIII', data, 8 + 20 * i)
        if cputype == 0x0100000c:  # CPU_TYPE_ARM64
            with open(out, 'wb') as f:
                f.write(data[off:off + size])
            return
    raise RuntimeError('no arm64 slice in %s' % fat)


def get_binary(replay_version, log=print):
    """Path to the arm64 game binary for this replay's patch (downloaded once)."""
    build = build_version(replay_version)
    dest_dir = os.path.join(CACHE, build)
    dest = os.path.join(dest_dir, 'LeagueofLegends_arm64')
    if os.path.exists(dest):
        return dest
    os.makedirs(dest_dir, exist_ok=True)
    fat = os.path.join(dest_dir, 'LeagueofLegends')

    local_bin = os.path.join(LOCAL_INSTALL, 'LeagueofLegends.app/Contents/MacOS/LeagueofLegends')
    if _local_install_version() == build and os.path.exists(local_bin):
        log('using local game install (%s)' % build)
        _extract_arm64(local_bin, dest)
        return dest

    manifest_url = None
    for region in REGIONS:
        try:
            with urllib.request.urlopen(MANIFEST_INDEX.format(region=region, version=build)) as r:
                manifest_url = r.read().decode().strip()
                break
        except urllib.error.HTTPError:
            continue
    if not manifest_url:
        raise RuntimeError('no archived macOS manifest for build %s' % build)
    log('downloading game binary %s from %s' % (build, manifest_url))
    files, chunks = rman.load_manifest(manifest_url)
    rman.download(files, chunks, 'Contents/MacOS/LeagueofLegends', fat)
    _extract_arm64(fat, dest)
    os.remove(fat)
    return dest
