"""Run a patch's own packet Deserialize() functions under Unicorn.

The game stores decoded fields re-obfuscated in memory, but its field readers
first write the plain value into the packet object and only then re-encode it
in place. We log every write into the object, so for each field offset the
last full-width write before re-encoding is the plain value. Strings are kept
plain in memory.
"""
import json
import struct

from unicorn import Uc, UcError, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE, UC_PROT_ALL
from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_SP, UC_ARM64_REG_LR, UC_ARM64_REG_PC

from .binscan import Binary

STACK, STACK_SZ = 0x7000_0000, 0x10_0000
HEAP, HEAP_SZ = 0x6000_0000, 0x100_0000
CTX = HEAP + HEAP_SZ - 0x10000   # fake game-context objects live at the heap's end
BUF = 0x5000_0000
STOP = 0x4000_0000
RET = 0xd65f03c0


class DecodeError(Exception):
    pass


class Decoded:
    """Plain field values of one deserialized packet, keyed by object offset.

    `hist[off]` holds every 4-byte write to that offset in order. Depending on
    the patch, the plain value is followed by in-place re-encoding either
    byte-wise (plain stays the last 4-byte write) or as another 4-byte write,
    so callers pick the write that looks like what they expect (`value`)."""

    def __init__(self, hist, u8, strings):
        self.hist, self.u8, self.strings = hist, u8, strings

    def value(self, off, pred):
        """Last 4-byte write at `off` satisfying pred, else None."""
        for v in reversed(self.hist.get(off, ())):
            if pred(v):
                return v
        return None

    def fvalue(self, off, lo, hi):
        """Last write at `off` that is a float in [lo, hi]. Near-zero values
        other than 0.0 are rejected: re-encoded bytes often read as tiny
        denormal floats that would otherwise pass any range check."""
        def ok(v):
            f = as_float(v)
            return lo <= f <= hi and (f == 0.0 or abs(f) >= 0.01)
        v = self.value(off, ok)
        return None if v is None else as_float(v)


def as_float(v):
    f = struct.unpack('<f', struct.pack('<I', v))[0]
    return f if f == f else float('nan')  # keep NaN comparisons False


class PacketEmulator:
    def __init__(self, binary_path):
        self.bin = Binary(binary_path)
        self.mu = mu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        raw = self.bin.raw
        for seg in self.bin.macho.segments:
            if seg.virtual_size == 0 or seg.name == '__PAGEZERO':
                continue
            va = seg.virtual_address & ~0xfff
            size = (seg.virtual_address + seg.virtual_size - va + 0xfff) & ~0xfff
            mu.mem_map(va, size, UC_PROT_ALL)
            mu.mem_write(seg.virtual_address, raw[seg.file_offset:seg.file_offset + seg.file_size])
        for base, size in ((STACK, STACK_SZ), (HEAP, HEAP_SZ), (BUF, 0x10_0000), (STOP, 0x1000)):
            mu.mem_map(base, size)
        mu.mem_write(STOP, struct.pack('<I', RET))

        scan = self._scan(binary_path)
        self.stubs = {int(k): v for k, v in scan['stubs'].items()}
        for i, g in enumerate(scan['context_globals']):
            obj = CTX + i * 0x1000
            mu.mem_write(obj, b'\x01' * 0x100)   # every flag byte "on"
            mu.mem_write(obj + 8, b'\x02')       # observed as a small count
            mu.mem_write(g, struct.pack('<Q', obj))
        self.heap = HEAP
        self._stub_hook = None
        self._install_stub_hook()
        self._ctors = {int(k): v for k, v in scan['ctors'].items()}
        self._classes = {}

    def _scan(self, binary_path):
        """Static scan results for this binary, cached next to it (the scan
        walks all ~8M instructions, so it's worth doing once per patch)."""
        cache = binary_path + '.scan.json'
        try:
            with open(cache) as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
        scan = {'stubs': self.bin.allocator_stubs(), 'context_globals': self.bin.context_globals(),
                'ctors': self.bin.packet_ctors()}
        try:
            with open(cache, 'w') as f:
                json.dump(scan, f)
        except OSError:
            pass
        return scan

    # --- plumbing ------------------------------------------------------------
    def _install_stub_hook(self):
        if self._stub_hook is not None:
            self.mu.hook_del(self._stub_hook)
        lo, hi = min(self.stubs), max(self.stubs)
        self._stub_hook = self.mu.hook_add(UC_HOOK_CODE, self._on_stub, begin=lo, end=hi + 4)

    def _on_stub(self, mu, addr, size, _):
        kind = self.stubs.get(addr)
        if kind is None:
            return
        if kind == 'new':
            n = mu.reg_read(UC_ARM64_REG_X0)
            if n > 0x10_0000:
                raise DecodeError('huge allocation')
            p = self.heap
            self.heap += (n + 15) & ~15
            if self.heap >= CTX:
                raise DecodeError('emulated heap exhausted')
            mu.mem_write(p, b'\0' * n)
            mu.reg_write(UC_ARM64_REG_X0, p)
        elif kind == 'ret1':
            mu.reg_write(UC_ARM64_REG_X0, 1)
        mu.reg_write(UC_ARM64_REG_PC, mu.reg_read(UC_ARM64_REG_LR))

    def _call(self, fn, *args):
        mu = self.mu
        for i, a in enumerate(args):
            mu.reg_write(UC_ARM64_REG_X0 + i, a)
        mu.reg_write(UC_ARM64_REG_SP, STACK + STACK_SZ - 0x1000)
        mu.reg_write(UC_ARM64_REG_LR, STOP)
        try:
            mu.emu_start(fn, STOP, count=500_000)
        except UcError as e:
            raise DecodeError(str(e))
        if mu.reg_read(UC_ARM64_REG_PC) != STOP:
            raise DecodeError('did not return')
        return mu.reg_read(UC_ARM64_REG_X0)

    def _alloc(self, n):
        p = self.heap
        self.heap += (n + 15) & ~15
        self.mu.mem_write(p, b'\0' * n)
        return p

    def _u64(self, a):
        return struct.unpack('<Q', self.mu.mem_read(a, 8))[0]

    # --- packet classes -----------------------------------------------------
    def packet_class(self, pid):
        """(ctor, deserialize, object size) for a packet id, or None."""
        if pid in self._classes:
            return self._classes[pid]
        found = None
        text_lo = self.bin.text_va
        text_hi = text_lo + 4 * len(self.bin.words)
        for ctor in self._ctors.get(pid, []):
            self.heap = HEAP
            try:
                obj = self._alloc(0x4000)
                self._call(ctor, obj)
                vt = self._u64(obj)
                deser, size_fn = self._u64(vt + 8), self._u64(vt + 16)
                if not (text_lo <= deser < text_hi and text_lo <= size_fn < text_hi):
                    continue
                size = self._call(size_fn, obj)
                if not 0x10 <= size <= 0x4000:
                    continue
            except DecodeError:
                continue
            found = (ctor, deser, size)
            # Deserialize() first reads the sender net id, which replays store
            # in the block header instead of the payload: make it a no-op.
            hdr = self.bin.first_call(deser)
            if hdr and hdr not in self.stubs:
                self.stubs[hdr] = 'ret1'
                self._install_stub_hook()
            break
        self._classes[pid] = found
        return found

    def decode(self, pid, payload):
        cls = self.packet_class(pid)
        if cls is None:
            raise DecodeError('no class for packet 0x%x' % pid)
        ctor, deser, size = cls
        self.heap = HEAP
        obj = self._alloc(size)
        self._call(ctor, obj)
        writes = []
        h = self.mu.hook_add(UC_HOOK_MEM_WRITE, lambda mu, a, addr, sz, v, u: writes.append((addr - obj, sz, v)),
                             begin=obj, end=obj + size - 1)
        try:
            self.mu.mem_write(BUF, payload)
            cur = self._alloc(16)
            self.mu.mem_write(cur, struct.pack('<Q', BUF))
            ok = self._call(deser, obj, cur, BUF + len(payload)) & 0xff
        finally:
            self.mu.hook_del(h)
        if not ok:
            raise DecodeError('deserialize rejected payload')
        hist, u8 = {}, {}
        for off, sz, v in writes:
            if sz == 4:
                hist.setdefault(off, []).append(v & 0xffffffff)
            elif sz == 1:
                u8.setdefault(off, v & 0xff)
        return Decoded(hist, u8, self._strings(obj, size))

    def _strings(self, obj, size):
        """Find {ptr, u32 len} string headers in the object pointing at heap text."""
        mem = bytes(self.mu.mem_read(obj, size))
        out = {}
        for off in range(0, size - 12, 8):
            ptr, ln = struct.unpack_from('<QI', mem, off)
            if HEAP <= ptr < CTX and 0 < ln < 256:
                s = bytes(self.mu.mem_read(ptr, ln))
                if all(32 <= c < 127 for c in s):
                    out[off] = s.decode()
        return out
