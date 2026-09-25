"""Static discovery of the patch-specific addresses needed to emulate packet
deserializers from a League macOS arm64 game binary.

Everything here is found by code shape, not hard-coded addresses, so the same
code works on each patch's freshly compiled binary."""
import array
import collections
import struct

import lief


def _bl_target(w, addr):
    off = w & 0x3ffffff
    if off & 0x2000000:
        off -= 0x4000000
    return addr + off * 4


def _adrp_page(w, addr):
    immlo = (w >> 29) & 3
    immhi = (w >> 5) & 0x7ffff
    imm = (immhi << 2) | immlo
    if imm & (1 << 20):
        imm -= 1 << 21
    return (addr & ~0xfff) + (imm << 12)


def _is_adrp(w):
    return (w & 0x9f000000) == 0x90000000


def _ldst_uimm(w):
    """(kind, rn, rt, byte offset) for LDR/LDRB/STR/STRB unsigned-imm forms."""
    top = w & 0xffc00000
    rn, rt, imm = (w >> 5) & 31, w & 31, (w >> 10) & 0xfff
    kinds = {0xf9400000: ('ldr64', 8), 0xb9400000: ('ldr32', 4), 0x39400000: ('ldrb', 1),
             0xf9000000: ('str64', 8), 0x39000000: ('strb', 1)}
    if top in kinds:
        k, sc = kinds[top]
        return k, rn, rt, imm * sc
    return None


class Binary:
    def __init__(self, path):
        self.path = path
        self.macho = lief.parse(path)
        self.raw = open(path, 'rb').read()
        t = self.macho.get_section('__text')
        self.text_va = t.virtual_address
        self.words = array.array('I', self.raw[t.offset:t.offset + t.size // 4 * 4])

    def addr(self, i):
        return self.text_va + 4 * i

    def index(self, addr):
        return (addr - self.text_va) // 4

    def u64(self, va):
        for seg in self.macho.segments:
            if seg.virtual_address <= va < seg.virtual_address + seg.file_size:
                return struct.unpack_from('<Q', self.raw, seg.file_offset + va - seg.virtual_address)[0]
        return 0

    # --- allocator -----------------------------------------------------
    def operator_new(self):
        """The function most often called right after `mov x0/w0, #const`."""
        cnt = collections.Counter()
        w = self.words
        for i in range(1, len(w)):
            if (w[i] & 0xfc000000) == 0x94000000 and (w[i - 1] & 0x7fe0001f) == 0x52800000:
                cnt[_bl_target(w[i], self.addr(i))] += 1
        return cnt.most_common(1)[0][0]

    def _global_refs(self, start, n):
        """Globals referenced via adrp+ldr/ldrb in the first n instructions."""
        out = []
        regs = {}
        for i in range(self.index(start), self.index(start) + n):
            w = self.words[i]
            if _is_adrp(w):
                regs[w & 31] = _adrp_page(w, self.addr(i))
                continue
            m = _ldst_uimm(w)
            if m and m[1] in regs:
                out.append((m[0], regs[m[1]] + m[3]))
        return out

    def allocator_stubs(self):
        """{addr: 'new'|'ret'} for operator new and its siblings (every
        function gated on the allocator's init flag) plus the matching frees."""
        new = self.operator_new()
        refs = self._global_refs(new, 12)
        init_flag = next(g for k, g in refs if k == 'ldrb')
        heap_ptr = next((g for k, g in refs if k == 'ldr64'), None)
        stubs = {new: 'new'}
        w = self.words
        for i in range(len(w) - 12):
            # prologue then init-flag check within a few instructions
            if (w[i] & 0xffc003ff) != 0xa98003fd and (w[i] & 0xffc003e0) != 0xa98003e0:
                continue
            for k, g in self._global_refs(self.addr(i), 8):
                if k == 'ldrb' and g == init_flag:
                    stubs.setdefault(self.addr(i), 'new')
                elif k == 'ldr64' and g == heap_ptr and self._has_cbz_x0(i, 4):
                    stubs.setdefault(self.addr(i), 'ret')
        return stubs

    def _has_cbz_x0(self, i, n):
        return any((self.words[j] & 0xff00001f) == 0xb4000000 for j in range(i, i + n))

    # --- packets ---------------------------------------------------------
    def packet_ctors(self):
        """{packet_id: [candidate ctor addrs]}: packet ctors begin with
        `mov wN,#id ; strh wN,[x0,#8]` (other code can match too, so callers
        validate candidates)."""
        out = collections.defaultdict(list)
        w = self.words
        for i in range(len(w) - 1):
            a, b = w[i], w[i + 1]
            if (a & 0xffe00000) == 0x52800000 and (b & 0xffffffe0) == 0x79001000 and (a & 31) == (b & 31):
                out[(a >> 5) & 0xffff].append(self.addr(i))
        return out

    def first_call(self, fn, limit=16):
        for i in range(self.index(fn), self.index(fn) + limit):
            if (self.words[i] & 0xfc000000) == 0x94000000:
                return _bl_target(self.words[i], self.addr(i))
        return None

    def context_globals(self):
        """Global object pointers that field readers dereference to check a
        flag byte (e.g. `ldr x8,[G]; cbz x8; ldrb w8,[x8,#0x70]`). Emulation
        points each at a fake object whose flag bytes are set."""
        out = collections.Counter()
        w = self.words
        for i in range(len(w) - 4):
            if not _is_adrp(w[i]):
                continue
            m = _ldst_uimm(w[i + 1])
            if not m or m[0] != 'ldr64' or m[1] != (w[i] & 31):
                continue
            g = _adrp_page(w[i], self.addr(i)) + m[3]
            rt = m[2]
            # cbz rt ; ldrb wX,[rt,#0x70]
            if (w[i + 2] & 0xff00001f) == (0xb4000000 | rt):
                m2 = _ldst_uimm(w[i + 3])
                if m2 and m2[0] == 'ldrb' and m2[1] == rt and m2[3] == 0x70:
                    out[g] += 1
        return [g for g, _ in out.most_common(3)]
