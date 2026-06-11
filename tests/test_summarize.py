"""Snapshot tests for origin_hardcoded_stars.summarize() (drives the GUI info
panel). Dict insertion order is preserved (Python 3.7+), so the rendered token
order is stable."""
from bbreroll import origin_hardcoded_stars as ohs


def test_gladiators_snapshot():
    assert ohs.summarize("Gladiators") == (
        "Hardcoded stars (locked, cannot be brute-forced):\n"
        "  Slot 1: msk:3  mdf:2  fat:2\n"
        "  Slot 2: hp:3  fat:2  res:2\n"
        "  Slot 3: msk:2  mdf:2  init:3"
    )


def test_fully_rolled_snapshot():
    assert ohs.summarize("Davkul Cultists") == \
        "All 5 slots fully rolled — every stat can be brute-forced."


def test_custom_snapshot():
    assert ohs.summarize("Custom") == \
        '"Custom" — no fixed roster; consult the scenario directly.'


def test_partial_lists_rolled_slots():
    # Escaped Slaves: slots 1 & 3 hardcoded, 2/4/5 rolled.
    out = ohs.summarize("Escaped Slaves")
    assert out.startswith("Hardcoded stars (locked, cannot be brute-forced):")
    assert "Slot 1: res:3  msk:1  rdf:3" in out
    assert "Slot 3: init:2  res:2  rsk:2" in out
    assert "Slots 2, 4, 5: fully rolled." in out


def test_unknown_origin_message():
    assert "no data available" in ohs.summarize("Nonexistent")
