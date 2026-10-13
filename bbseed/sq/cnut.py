"""Reader for Squirrel 3.0.4 compiled scripts (.cnut) as Battle Brothers ships them.

The file is Squirrel's own closure serialization (sqclosure.cpp / sqfuncproto.cpp:
`SQClosure::Save`, `SQFunctionProto::Save`), 32-bit build: SQInteger and SQFloat are 4
bytes, SQChar is 1.

Battle Brothers scrambles the stream as it reads it: every single read of 8 or more bytes
has its whole 4-byte groups decrypted as one XXTEA block (the remaining 1-3 bytes and all
shorter reads are plain). So what is scrambled follows from the sizes of the engine's
reads: string bodies of 8+ characters, and the line-info, default-parameter and
instruction arrays. The scheme and key are documented by the author of the community mod
kit (adammil.net, "Battle Brothers mod kit"); this module does the same thing that kit's
decrypter does, on the player's own game files.
"""
import struct

KEY = (238473842, 20047425, 14005, 978629342)
_DELTA = 0x9E3779B9
_M = 0xFFFFFFFF

TAG_FILE = 0xFAFA
TAG_HEAD = 0x53514952      # 'SQIR'
TAG_PART = 0x50415254      # 'PART'
TAG_TAIL = 0x5441494C      # 'TAIL'
OT_NULL, OT_INTEGER, OT_FLOAT, OT_BOOL, OT_STRING = 0x01000001, 0x05000002, 0x05000004, 0x01000008, 0x08000010


class CnutError(Exception):
    pass


def xxtea_decrypt(v):
    """In-place XXTEA decryption of a list of 32-bit words (needs at least 2)."""
    n = len(v)
    key = KEY
    rounds = 6 + 52 // n
    total = (rounds * _DELTA) & _M
    y = v[0]
    last = n - 1
    for _ in range(rounds):
        e = (total >> 2) & 3
        for p in range(last, 0, -1):
            z = v[p - 1]
            y = v[p] = (v[p] - ((((z >> 5) ^ (y << 2)) + ((y >> 3) ^ (z << 4))) ^ ((total ^ y) + (key[(p & 3) ^ e] ^ z)))) & _M
        z = v[last]
        y = v[0] = (v[0] - ((((z >> 5) ^ (y << 2)) + ((y >> 3) ^ (z << 4))) ^ ((total ^ y) + (key[e] ^ z)))) & _M
        total = (total - _DELTA) & _M


def unscramble_read(chunk):
    """One read of the script stream, as the game sees it after its decryption."""
    n = len(chunk) // 4
    if len(chunk) < 8:
        return chunk
    words = list(struct.unpack_from("<%dI" % n, chunk))
    xxtea_decrypt(words)
    return struct.pack("<%dI" % n, *words) + chunk[n * 4:]


class Proto:
    """One function of a compiled script (SQFunctionProto), as plain data."""

    __slots__ = ("sourcename", "name", "literals", "parameters", "outervalues", "localvars", "lineinfos",
                 "defaultparams", "code", "functions", "stacksize", "bgenerator", "varparams")

    def line(self):
        return self.lineinfos[0][0] if self.lineinfos else 0


class _Stream:
    def __init__(self, data, scrambled):
        self.data = data
        self.pos = 0
        self.scrambled = scrambled
        self.out = bytearray() if scrambled else None      # the same stream, unscrambled (for caching)

    def read(self, n):
        chunk = self.data[self.pos:self.pos + n]
        if len(chunk) != n:
            raise CnutError("unexpected end of file")
        self.pos += n
        if self.scrambled:
            if n >= 8:
                chunk = unscramble_read(chunk)
            self.out += chunk
        return chunk

    def u32(self):
        return struct.unpack("<I", self.read(4))[0]

    def i32(self):
        return struct.unpack("<i", self.read(4))[0]

    def tag(self, expected):
        got = self.u32()
        if got != expected:
            raise CnutError("bad tag at offset %d: %08x, expected %08x" % (self.pos - 4, got, expected))

    def obj(self):
        t = self.u32()
        if t == OT_STRING:
            n = self.i32()
            if n < 0 or n > len(self.data):
                raise CnutError("bad string length %d at offset %d" % (n, self.pos))
            return self.read(n).decode("utf-8", "replace")
        if t == OT_INTEGER:
            return self.i32()
        if t == OT_FLOAT:
            return struct.unpack("<f", self.read(4))[0]
        if t == OT_NULL:
            return None
        if t == OT_BOOL:
            return bool(self.i32())
        raise CnutError("cannot read an object of type %08x at offset %d" % (t, self.pos - 4))


def _function(s):
    p = Proto()
    s.tag(TAG_PART)
    p.sourcename = s.obj()
    p.name = s.obj()
    s.tag(TAG_PART)
    nliterals, nparameters, nouters, nlocals, nlines, ndefaults, ninstr, nfunctions = (s.i32() for _ in range(8))
    s.tag(TAG_PART)
    p.literals = [s.obj() for _ in range(nliterals)]
    s.tag(TAG_PART)
    p.parameters = [s.obj() for _ in range(nparameters)]
    s.tag(TAG_PART)
    p.outervalues = []
    for _ in range(nouters):
        kind = s.u32()
        src = s.obj()
        name = s.obj()
        p.outervalues.append((kind, src, name))
    s.tag(TAG_PART)
    p.localvars = []
    for _ in range(nlocals):
        name = s.obj()
        p.localvars.append((name, s.u32(), s.u32(), s.u32()))
    s.tag(TAG_PART)
    raw = s.read(8 * nlines)
    p.lineinfos = [struct.unpack_from("<ii", raw, 8 * i) for i in range(nlines)]
    s.tag(TAG_PART)
    raw = s.read(4 * ndefaults)
    p.defaultparams = list(struct.unpack("<%di" % ndefaults, raw))
    s.tag(TAG_PART)
    p.code = s.read(8 * ninstr)                 # SQInstruction: int32 arg1, u8 op, u8 arg0, u8 arg2, u8 arg3
    s.tag(TAG_PART)
    p.functions = [_function(s) for _ in range(nfunctions)]
    p.stacksize = s.i32()
    p.bgenerator = s.read(1)[0] != 0
    p.varparams = s.i32()
    return p


def load(data, scrambled=True):
    """Parse a .cnut. Returns (main function Proto, the unscrambled stream or None)."""
    s = _Stream(data, scrambled)
    if struct.unpack("<H", s.read(2))[0] != TAG_FILE:
        raise CnutError("not a compiled Squirrel script")
    s.tag(TAG_HEAD)
    if (s.u32(), s.u32(), s.u32()) != (1, 4, 4):
        raise CnutError("compiled for a different build (char/int/float sizes)")
    main = _function(s)
    s.tag(TAG_TAIL)
    return main, (bytes(s.out) if scrambled else None)


def instructions(code):
    """The instruction array as tuples (op, arg0, arg1, arg2, arg3); arg1 is the signed 32-bit one."""
    return [(op, a0, a1, a2, a3) for a1, op, a0, a2, a3 in struct.iter_unpack("<iBBBB", code)]
