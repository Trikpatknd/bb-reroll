"""Snapshot tests for origin_hardcoded_stars.summarize() (drives the GUI info
panel). Dict insertion order is preserved (Python 3.7+), so the rendered token
order is stable."""
from bbreroll import origin_hardcoded_stars as ohs


def test_gladiators_snapshot():
    assert ohs.summarize("Gladiators") == (
        "Fixed stars (the seed cannot change them):\n"
        "  Brother 1: MSK 3, MDF 2, FAT 2\n"
        "  Brother 2: HP 3, FAT 2, RES 2\n"
        "  Brother 3: MSK 2, MDF 2, INIT 3"
    )


def test_fully_rolled_snapshot():
    assert ohs.summarize("Davkul Cultists") == \
        "All 5 brothers get random stars."


def test_origin_without_a_fixed_roster_snapshot():
    # Random Party rolls 4-6 brothers per seed
    assert ohs.summarize("Random Party") == \
        'The brothers of Random Party change with the seed.'


def test_partial_lists_rolled_slots():
    # Escaped Slaves: slots 1 & 3 hardcoded, 2/4/5 rolled.
    out = ohs.summarize("Escaped Slaves")
    assert out.startswith("Fixed stars (the seed cannot change them):")
    assert "Brother 1: RES 3, MSK 1, RDF 3" in out
    assert "Brother 3: INIT 2, RES 2, RSK 2" in out
    assert "Brothers 2, 4, 5: random stars." in out


def test_unknown_origin_message():
    assert "no data" in ohs.summarize("Nonexistent")
