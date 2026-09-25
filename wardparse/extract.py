"""Extract every ward placement (who, what, where, when) and its lifetime from
a .rofl replay.

Packet ids and field layouts are reshuffled every patch, so nothing here is
keyed on them. Instead:
  * the spawn packet is whichever packet type decodes to a known ward name;
  * its net-id / owner / position fields are found from the decoded values;
  * the death packet is the once-per-ward packet whose payload names either
    the ward itself (it expired) or a champion (it was killed).
"""
import collections
import json
import os
import time

from .emulator import DecodeError, PacketEmulator
from .gamebinary import get_binary
from .rofl import packets

WARD_TYPES = {
    'YellowTrinket': ('trinket', 'Stealth Ward (Trinket)'),
    'SightWard': ('stealth', 'Stealth Ward'),
    'JammerDevice': ('control', 'Control Ward'),
    'BlueTrinket': ('farsight', 'Farsight Ward'),
}
# Natural lifetimes in seconds (trinket: 90-120 depending on level). A ward
# that died "by itself" well before this was pushed out by the ward limit.
NATURAL_LIFETIME = {'trinket': 90, 'stealth': 150, 'control': None, 'farsight': None}


def _ward_type(name):
    if name in WARD_TYPES:
        return WARD_TYPES[name]
    if 'zombie' in name.lower() and 'ward' in name.lower():
        return ('zombie', 'Zombie Ward')
    return None


# A spawn carries two names (object + skin) whose field order changes per
# patch, e.g. a trinket is (YellowTrinket, SightWard) on 16.18 and
# (SightWard, YellowTrinket) on 16.19. The most specific name wins.
_SPECIFICITY = ['JammerDevice', 'BlueTrinket', 'YellowTrinket']


def _spawn_ward_type(strings):
    names = set(strings.values())
    for n in _SPECIFICITY:
        if n in names:
            return WARD_TYPES[n]
    for n in names:
        if _ward_type(n):
            return _ward_type(n)
    return None


def _in_map(v):
    return v is not None and -1000 < v < 16000


class ExtractionError(Exception):
    pass


def _find_spawn_type(em, stream, log):
    """Packet type that spawns wards.

    Pass 1 samples every type to find the few that carry strings at all;
    pass 2 scans those fully, since wards can be rare among spawns. A hit
    needs two ward names in one packet (object + skin, e.g. SightWard +
    YellowTrinket): other packets, like sound events, mention one at most."""
    by_type = collections.defaultdict(list)
    for p in stream:
        if len(p.data) >= 24:
            by_type[p.type].append(p)
    string_types = []
    for t, lst in by_type.items():
        step = max(1, len(lst) // 40)
        for p in lst[::step][:40]:
            try:
                if em.decode(t, p.data).strings:
                    string_types.append(t)
                    break
            except DecodeError:
                continue
    best = (0, None)
    for t in string_types:
        hits = 0
        for p in by_type[t]:
            try:
                d = em.decode(t, p.data)
            except DecodeError:
                continue
            if sum(1 for s in d.strings.values() if _ward_type(s)) >= 2:
                hits += 1
                if hits >= 20:
                    break
        if hits > best[0]:
            best = (hits, t)
    if not best[1]:
        raise ExtractionError('could not find the ward spawn packet')
    log('spawn packet: 0x%x' % best[1])
    return best[1]


def _is_netid(v):
    return v >> 24 == 0x40


def _field_offsets(spawns, heroes):
    """Locate net id, owner and position fields among decoded ward spawns."""
    offs = set.intersection(*(set(d.hist) for _, d in spawns))
    netid = next((o for o in sorted(offs) if all(p.param in d.hist[o] for p, d in spawns)), None)
    owner_scores = []
    for o in sorted(offs):
        if o != netid:
            share = sum(d.value(o, heroes.__contains__) is not None for _, d in spawns) / len(spawns)
            owner_scores.append((share, o))
    owner_share, owner = max(owner_scores) if owner_scores else (0, None)
    pos = None
    for o in sorted(offs):
        if o + 4 not in offs or o + 8 not in offs:
            continue
        xs = [d.fvalue(o, -1000, 16000) for _, d in spawns]
        ok = all(x is not None and d.fvalue(o + 4, -500, 800) is not None and d.fvalue(o + 8, -1000, 16000) is not None
                 for x, (_, d) in zip(xs, spawns))
        if ok and max(xs) - min(xs) > 1000:
            pos = o
            break
    if netid is None or pos is None or owner_share < 0.9:
        raise ExtractionError('could not locate ward fields (netid=%s owner=%s pos=%s)' % (netid, owner, pos))
    return netid, owner, pos


def _find_deaths(em, stream, ward_ids, heroes, spawn_type, log):
    """{ward net id: (time, killer net id)} from the per-ward death packet."""
    per = collections.defaultdict(lambda: collections.defaultdict(list))
    for p in stream:
        if p.param in ward_ids:
            per[p.type][p.param].append(p)
    best = None
    for t, by_ward in per.items():
        # mostly once per ward (a rare ward can die twice, e.g. when revived)
        once = sum(len(v) == 1 for v in by_ward.values())
        if t == spawn_type or len(by_ward) < 0.5 * len(ward_ids) or once < 0.95 * len(by_ward):
            continue
        sample = [v[0] for v in list(by_ward.values())[:60]]
        decoded = []
        for p in sample:
            try:
                decoded.append((p, em.decode(t, p.data)))
            except DecodeError:
                pass
        if len(decoded) < 0.8 * len(sample):
            continue
        for o in set.intersection(*(set(d.hist) for _, d in decoded)):
            self_kill = sum(p.param in d.hist[o] for p, d in decoded)
            champ = sum(d.value(o, heroes.__contains__) is not None for _, d in decoded)
            if self_kill and self_kill + champ >= 0.9 * len(decoded):
                score = (champ > 0, len(by_ward), self_kill + champ)
                if best is None or score > best[0]:
                    best = (score, t, o)
    if best is None:
        raise ExtractionError('could not find the ward death packet')
    _, t, killer_off = best
    log('death packet: 0x%x (killer at +0x%x)' % (t, killer_off))
    out = {}
    for wid, (p, *_) in per[t].items():
        try:
            d = em.decode(t, p.data)
            # prefer the ward itself or a champion; else any net id (turret, summon...)
            killer = d.value(killer_off, lambda v: v == wid or v in heroes) or d.value(killer_off, _is_netid)
        except DecodeError:
            killer = None
        out[wid] = (p.time, killer)
    return out


def _hero_ids(stream, n):
    """Champion net ids: n consecutive ids (in participant order) that are
    among the busiest objects. A quiet support can be less busy than some
    turret or summon, so the n busiest alone isn't enough."""
    busy = collections.Counter(p.param for p in stream if p.param)
    top = dict(busy.most_common(n * 4))
    best = max((sum(top.get(b + k, 0) for k in range(n)), b) for b in top
               if all(b + k in top for k in range(n)))
    return list(range(best[1], best[1] + n))


MIN_GAME_LENGTH = 5 * 60  # shorter games are remakes: nothing to learn, too few wards to calibrate on


def extract(path, binary=None, log=print):
    version, meta, pkts = packets(path)
    stats = meta['statsJson']
    if meta['gameLength'] / 1000.0 < MIN_GAME_LENGTH:
        raise ExtractionError('skipped: remake (%.0f s game)' % (meta['gameLength'] / 1000.0))
    binary = binary or get_binary(version, log=log)
    em = PacketEmulator(binary)
    stream = [p for p in pkts if not p.keyframe]
    game_length = meta['gameLength'] / 1000.0

    hero_ids = _hero_ids(stream, len(stats))
    heroes = {nid: i for i, nid in enumerate(hero_ids)}

    spawn_type = _find_spawn_type(em, stream, log)
    spawns, others = [], []
    for p in stream:
        if p.type != spawn_type:
            continue
        try:
            d = em.decode(spawn_type, p.data)
        except DecodeError:
            continue
        (spawns if _spawn_ward_type(d.strings) else others).append((p, d))
    netid_off, owner_off, pos_off = _field_offsets(spawns, heroes)
    # Summons (Shaco boxes, clones, plants...) credit their kills to the owner.
    summoner_of = {}
    for p, d in others:
        o = d.value(owner_off, heroes.__contains__)
        if o is not None:
            summoner_of[p.param] = heroes[o]
    deaths = _find_deaths(em, stream, {p.param for p, _ in spawns}, heroes, spawn_type, log)

    players = []
    for i, s in enumerate(stats):
        players.append({
            'index': i,
            'netId': hero_ids[i] if i < len(hero_ids) else None,
            'puuid': s.get('PUUID', ''),
            'champion': s.get('SKIN'),
            'riotId': '%s#%s' % (s.get('RIOT_ID_GAME_NAME', s.get('NAME', '?')), s.get('RIOT_ID_TAG_LINE', '')),
            'team': int(s.get('TEAM', 0)),
            'position': s.get('TEAM_POSITION') or s.get('INDIVIDUAL_POSITION') or '',
            'win': s.get('WIN') == 'Win',
            'stats': {k: int(s.get(k, 0) or 0) for k in
                      ('WARD_PLACED', 'WARD_KILLED', 'WARD_PLACED_DETECTOR', 'VISION_SCORE',
                       'VISION_WARDS_BOUGHT_IN_GAME')},
        })

    wards = []
    for p, d in spawns:
        key, label = _spawn_ward_type(d.strings)
        wid = p.param
        owner = heroes.get(d.value(owner_off, heroes.__contains__))
        died, killer_id = deaths.get(wid, (None, None))
        if died is None:
            end, killer, lifetime = 'game end', None, game_length - p.time
        else:
            lifetime = died - p.time
            killer = heroes.get(killer_id, summoner_of.get(killer_id))
            if killer is not None:
                end = 'killed'
            elif killer_id == wid:
                natural = NATURAL_LIFETIME.get(key)
                end = 'expired' if natural and lifetime >= natural - 1 else 'replaced'
            else:
                end = 'destroyed'
        wards.append({
            'id': wid,
            'type': key,
            'typeName': label,
            'owner': owner,
            'team': players[owner]['team'] if owner is not None else None,
            'x': round(d.fvalue(pos_off, -1000, 16000), 1),
            'z': round(d.fvalue(pos_off + 8, -1000, 16000), 1),
            'height': round(d.fvalue(pos_off + 4, -500, 800), 1),
            'placed': round(p.time, 2),
            'died': round(died, 2) if died is not None else None,
            'lifetime': round(lifetime, 2),
            'end': end,
            'killer': killer,
        })

    placed = collections.Counter(w['owner'] for w in wards)
    killed = collections.Counter(w['killer'] for w in wards if w['killer'] is not None)
    checks = [{'player': pl['index'],
               'placedParsed': placed.get(pl['index'], 0), 'placedOfficial': pl['stats']['WARD_PLACED'],
               'killedParsed': killed.get(pl['index'], 0), 'killedOfficial': pl['stats']['WARD_KILLED']}
              for pl in players]
    mismatches = [c for c in checks if c['placedParsed'] != c['placedOfficial']]
    if mismatches:
        log('WARNING: ward counts differ from the game\'s own stats for %d players' % len(mismatches))
    # Nothing can be warded on the map's outer rim; coordinates there mean a
    # field was decoded from the wrong write.
    off_map = sum(1 for w in wards if not (300 < w['x'] < 14600 and 300 < w['z'] < 14600))
    if off_map:
        log('WARNING: %d ward positions fall outside the playable map' % off_map)

    return {
        'matchId': os.path.basename(path).rsplit('.', 1)[0],
        'version': version,
        'gameLength': round(game_length, 2),
        'players': players,
        'wards': sorted(wards, key=lambda w: w['placed']),
        'validation': {'countsMatch': not mismatches, 'offMapPositions': off_map, 'perPlayer': checks},
    }


def parse_to_file(path, out_json, binary=None):
    """Batch worker: extract one replay to JSON; returns a one-line status."""
    t = time.time()
    try:
        game = extract(path, binary=binary, log=lambda *a: None)
    except Exception as e:  # keep going through a batch
        return 'failed: %s' % e
    with open(out_json, 'w') as f:
        json.dump(game, f, separators=(',', ':'))
    return '%d wards, counts match official stats: %s (%.0fs)' % (
        len(game['wards']), game['validation']['countsMatch'], time.time() - t)
