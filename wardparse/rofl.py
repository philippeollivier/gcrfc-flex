"""ROFL2 container + packet-block parsing (patch-independent framing)."""
import json
import struct
from dataclasses import dataclass

import zstandard


@dataclass(slots=True)
class Packet:
    time: float      # seconds
    type: int        # u16 packet id (scrambled per patch)
    param: int       # usually sender net id
    data: bytes
    chunk: int
    keyframe: bool


def read_version(path):
    """Patch version from the file header, without reading the whole replay."""
    with open(path, 'rb') as f:
        head = f.read(64)
    return head[15:15 + head[14]].decode()


def read_rofl(path):
    d = open(path, 'rb').read()
    assert d[:4] == b'RIOT'
    meta_len = struct.unpack('<I', d[-4:])[0]
    meta_end = len(d) - 4
    meta = json.loads(d[meta_end - meta_len:meta_end])
    meta['statsJson'] = json.loads(meta['statsJson'])
    vlen = d[14]
    version = d[15:15 + vlen].decode()
    o = 15 + vlen
    end = meta_end - meta_len
    entries = []
    while o + 17 <= end:
        cid, nxt, typ, usz, csz = struct.unpack_from('<IIBII', d, o)
        if typ not in (1, 2, 3, 4) or o + 17 + (csz or usz) > end:
            break  # trailing signature (its bytes can look like a header)
        o += 17
        if csz == 0:
            raw = d[o:o + usz]
            o += usz
        else:
            raw = zstandard.ZstdDecompressor().decompressobj().decompress(d[o:o + csz])
            o += csz
        entries.append((typ, cid, raw))
    return version, meta, entries


def iter_blocks(raw, chunk=0, keyframe=False):
    o, n = 0, len(raw)
    t = 0.0
    typ = 0
    param = 0
    while o < n:
        m = raw[o]; o += 1
        if m & 0x80:
            t += raw[o] / 1000.0; o += 1
        else:
            t = struct.unpack_from('<f', raw, o)[0]; o += 4
        if m & 0x10:
            ln = raw[o]; o += 1
        else:
            ln = struct.unpack_from('<I', raw, o)[0]; o += 4
        if not (m & 0x40):
            typ = struct.unpack_from('<H', raw, o)[0]; o += 2
        if m & 0x20:
            param = (param + raw[o]) & 0xFFFFFFFF; o += 1
        else:
            param = struct.unpack_from('<I', raw, o)[0]; o += 4
        yield Packet(t, typ, param, raw[o:o + ln], chunk, keyframe)
        o += ln


def packets(path):
    version, meta, entries = read_rofl(path)
    out = []
    for typ, cid, raw in entries:
        if typ in (1, 2):
            out.extend(iter_blocks(raw, cid, typ == 2))
    return version, meta, out
