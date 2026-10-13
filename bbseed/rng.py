"""Battle Brothers' seeded random generator, reproduced bit-for-bit.

Identified 2026-10-12 by black-box probe (probe/…/zz_seedlab_probe.nut, game
1.5.2.3) and cross-checked against 149k real loop seeds from a June 2026 run
(game 1.5.1.8): see MODLOG.md.

  Math.seedRandom(n)        -> std::mt19937_64 seeded with n as unsigned 32-bit
  Math.seedRandomString(s)  -> std::mt19937_64 seeded with sdbm64(s)
                               (h = h*65599 + byte, wrapping at 2^64; case-sensitive)
  Math.rand(lo, hi)         -> lo + U % (hi - lo + 1), one 64-bit draw U per call
                               -- but ONLY when hi > lo. With hi <= lo it returns lo
                               and draws nothing (rand(3, 3), rand(1, 0) ...).
  Math.rand()               -> C runtime rand(); a SEPARATE stream that the
                               seed functions above do not touch

The hi <= lo rule was settled on 2026-10-12 by the June log: running the game's
own roster scripts in the lab engine reproduces the game's draw count for 1,000
of 1,000 consecutive seeds only if such calls consume nothing; with one draw per
call the counts are off by 7-47 on every seed (each roster makes ~30 such calls).
"""

M64 = (1 << 64) - 1
_NN, _MM = 312, 156
_A = 0xB5026F5AA96619E9
_UM, _LM = 0xFFFFFFFF80000000, 0x7FFFFFFF


def sdbm64(s) -> int:
    """The engine's string-seed hash."""
    h = 0
    for c in (s.encode("latin1") if isinstance(s, str) else s):
        h = (c + (h << 6) + (h << 16) - h) & M64
    return h


class MT64:
    """std::mt19937_64."""

    __slots__ = ("mt", "idx", "draws")

    def __init__(self, seed: int):
        mt = [0] * _NN
        mt[0] = seed & M64
        for i in range(1, _NN):
            prev = mt[i - 1]
            mt[i] = (6364136223846793005 * (prev ^ (prev >> 62)) + i) & M64
        self.mt = mt
        self.idx = _NN
        self.draws = 0      # how many numbers have been drawn since seeding

    def _twist(self):
        mt = self.mt
        for i in range(_NN):
            x = (mt[i] & _UM) | (mt[(i + 1) % _NN] & _LM)
            mt[i] = mt[(i + _MM) % _NN] ^ (x >> 1) ^ (_A if x & 1 else 0)
        self.idx = 0

    def next(self) -> int:
        if self.idx >= _NN:
            self._twist()
        x = self.mt[self.idx]
        self.idx += 1
        self.draws += 1
        x ^= (x >> 29) & 0x5555555555555555
        x ^= (x << 17) & 0x71D67FFFEDA60000
        x ^= (x << 37) & 0xFFF7EEE000000000
        x ^= x >> 43
        return x & M64

    def rand(self, lo: int, hi: int) -> int:
        """Math.rand(lo, hi). A range with a single value (or an empty one) draws nothing."""
        if hi <= lo:
            return lo
        return lo + self.next() % (hi - lo + 1)


def seeded(seed_int: int) -> MT64:
    """Math.seedRandom(seed_int)."""
    return MT64(seed_int & 0xFFFFFFFF)


def seeded_string(s) -> MT64:
    """Math.seedRandomString(s)."""
    return MT64(sdbm64(s))
