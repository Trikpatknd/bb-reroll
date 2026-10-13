"""bbseed.rng against values the real game produced (probe v1, BB 1.5.2.3,
2026-10-12). Each list is what the game logged for the same calls."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bbseed.rng import sdbm64, seeded, seeded_string


def _draws(gen, n, lo, hi):
    return [gen.rand(lo, hi) for _ in range(n)]


def test_integer_seed_stream_matches_game():
    assert _draws(seeded(1), 10, 0, 35) == [32, 6, 18, 18, 0, 33, 20, 9, 32, 4]
    assert _draws(seeded(1), 5, 0, 2147483647) == [996700008, 588839502, 2061911450, 2033565838, 1828480824]
    assert _draws(seeded(1), 10, 1, 100) == [29, 63, 31, 47, 85, 10, 29, 66, 49, 25]
    assert _draws(seeded(1), 10, -10, 10) == [-8, -1, 8, 2, -1, -10, 10, 8, -8, -3]


def test_negative_seed_is_unsigned_32_bit():
    assert _draws(seeded(-1), 6, 0, 35) == _draws(seeded(0xFFFFFFFF), 6, 0, 35)


def test_string_seed_stream_matches_game():
    assert _draws(seeded_string(""), 8, 0, 35) == [6, 23, 13, 6, 28, 14, 19, 0]
    assert _draws(seeded_string("a"), 8, 0, 35) == [6, 25, 35, 32, 32, 21, 23, 29]
    assert _draws(seeded_string("b"), 8, 0, 35) == [22, 31, 8, 17, 8, 16, 29, 32]


def test_string_hash_is_case_sensitive_and_64_bit():
    assert sdbm64("") == 0
    assert sdbm64("a") == 97
    assert sdbm64("ab") == 97 * 65599 + 98
    assert sdbm64("REROLL") != sdbm64("reroll")
    assert sdbm64("66R2NK3Y5D") > 0xFFFFFFFF          # no 32-bit truncation


def test_single_value_or_empty_range_draws_nothing():
    # rand(5, 5) = 5 and rand(35, 0) = 35 were measured in the game (probe 2); that they
    # consume no draw follows from the June log (see bbseed/rng.py).
    gen = seeded(1)
    assert gen.rand(5, 5) == 5 and gen.rand(35, 0) == 35 and gen.rand(1, 0) == 1
    assert gen.draws == 0
    assert _draws(gen, 3, 0, 35) == [32, 6, 18]


def test_real_campaign_loop_from_june_log():
    # BB Reroll 3.4.7 reseeded with seed + "::BBR", spawned a Trader roster, then
    # drew the next seed's 10 characters: iteration 0 -> 1 consumed 370 draws.
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    gen = seeded_string("66R2NK3Y5D" + "::BBR")
    for _ in range(370):
        gen.next()
    assert "".join(chars[gen.rand(0, 35)] for _ in range(10)) == "CWWEUHO396"
