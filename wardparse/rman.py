"""Minimal Riot RMAN manifest reader + single-file downloader.

Used to fetch the exact League game binary matching a replay's patch, so its
packet deserializers can be emulated. Usage:
    python3 rman.py <manifest_url_or_path> <file_name_substring> <out_path>
"""
import struct
import sys
import urllib.request

import zstandard

BUNDLE_URL = 'https://lol.secure.dyn.riotcdn.net/channels/public/bundles/%016X.bundle'


class Table:
    def __init__(self, buf, pos):
        self.buf, self.pos = buf, pos
        vt = pos - struct.unpack_from('<i', buf, pos)[0]
        vsize = struct.unpack_from('<H', buf, vt)[0]
        self.offs = [struct.unpack_from('<H', buf, vt + 4 + 2 * i)[0] for i in range((vsize - 4) // 2)]

    def _o(self, i):
        return self.offs[i] if i < len(self.offs) else 0

    def scalar(self, i, fmt, default=0):
        o = self._o(i)
        return struct.unpack_from(fmt, self.buf, self.pos + o)[0] if o else default

    def _ref(self, i):
        o = self._o(i)
        if not o:
            return None
        p = self.pos + o
        return p + struct.unpack_from('<I', self.buf, p)[0]

    def string(self, i):
        p = self._ref(i)
        if p is None:
            return ''
        n = struct.unpack_from('<I', self.buf, p)[0]
        return self.buf[p + 4:p + 4 + n].decode()

    def tables(self, i):
        p = self._ref(i)
        if p is None:
            return []
        n = struct.unpack_from('<I', self.buf, p)[0]
        out = []
        for k in range(n):
            q = p + 4 + 4 * k
            out.append(Table(self.buf, q + struct.unpack_from('<I', self.buf, q)[0]))
        return out

    def u64s(self, i):
        p = self._ref(i)
        if p is None:
            return []
        n = struct.unpack_from('<I', self.buf, p)[0]
        return list(struct.unpack_from('<%dQ' % n, self.buf, p + 4))


def load_manifest(src):
    data = urllib.request.urlopen(src).read() if src.startswith('http') else open(src, 'rb').read()
    assert data[:4] == b'RMAN'
    off, clen, _mid, ulen = struct.unpack_from('<IIQI', data, 8)
    body = zstandard.ZstdDecompressor().stream_reader(data[off:off + clen], read_across_frames=True).read(ulen)
    root = Table(body, struct.unpack_from('<I', body, 0)[0])
    chunks = {}
    for b in root.tables(0):
        bid = b.scalar(0, '<Q')
        o = 0
        for c in b.tables(1):
            cid, csz, usz = c.scalar(0, '<Q'), c.scalar(1, '<I'), c.scalar(2, '<I')
            chunks[cid] = (bid, o, csz, usz)
            o += csz
    dirs = {d.scalar(0, '<Q'): (d.scalar(1, '<Q'), d.string(2)) for d in root.tables(3)}

    def path(did):
        parts = []
        while did in dirs and dirs[did][1]:
            parts.append(dirs[did][1])
            did = dirs[did][0]
        return '/'.join(reversed(parts))

    files = []
    for f in root.tables(2):
        name = f.string(3)
        d = path(f.scalar(1, '<Q'))
        files.append((d + '/' + name if d else name, f.scalar(2, '<I'), f.u64s(7)))
    return files, chunks


def download(files, chunks, match, out):
    cands = [f for f in files if f[0].endswith(match) or match in f[0]]
    name, size, cids = min(cands, key=lambda f: len(f[0]))
    print('downloading', name, size, 'bytes,', len(cids), 'chunks')
    by_bundle = {}
    for cid in cids:
        by_bundle.setdefault(chunks[cid][0], []).append(cid)
    blobs = {}
    for bid, ids in by_bundle.items():
        lo = min(chunks[c][1] for c in ids)
        hi = max(chunks[c][1] + chunks[c][2] for c in ids)
        req = urllib.request.Request(BUNDLE_URL % bid, headers={'Range': 'bytes=%d-%d' % (lo, hi - 1)})
        raw = urllib.request.urlopen(req).read()
        for c in ids:
            _, o, csz, _ = chunks[c]
            blobs[c] = zstandard.ZstdDecompressor().decompressobj().decompress(raw[o - lo:o - lo + csz])
    with open(out, 'wb') as fh:
        for cid in cids:
            fh.write(blobs[cid])
    return name


if __name__ == '__main__':
    files, chunks = load_manifest(sys.argv[1])
    if len(sys.argv) < 4:
        for f in files:
            print(f[1], f[0])
    else:
        download(files, chunks, sys.argv[2], sys.argv[3])
