"""Integrity checks for the per-origin hardcoded-stars catalog and its
agreement with the GUI's ORIGINS list (bbreroll/offline_origins.py)."""
from bbreroll import offline_origins
from bbreroll import origin_hardcoded_stars as ohs

VALID_STATS = {"hp", "fat", "res", "init", "msk", "rsk", "mdf", "rdf"}
# Hard-disabled scenarios (isValid() == false) that must never be offered.
DISABLED = {"Build your own", "Druid [Legacy]", "Horse Party", "Mage"}


def _gui_origins():
    return offline_origins.ORIGINS


def test_catalog_has_expected_count():
    # 14 vanilla Legends-hooked + 21 Legends-added (Legends 19.4.22).
    assert len(ohs.ORIGIN_HARDCODED_STARS) == 35


def test_disabled_origins_absent():
    for name in DISABLED:
        assert name not in ohs.ORIGIN_HARDCODED_STARS, f"{name} is disabled and must not appear"


def test_slot_keys_and_values_valid():
    for origin, slots in ohs.ORIGIN_HARDCODED_STARS.items():
        assert isinstance(slots, list), origin
        for i, slot in enumerate(slots, 1):
            assert isinstance(slot, dict), f"{origin} slot {i}"
            for stat, val in slot.items():
                assert stat in VALID_STATS, f"{origin} slot {i}: bad stat {stat!r}"
                assert isinstance(val, int) and 1 <= val <= 3, \
                    f"{origin} slot {i}: {stat} out of range ({val})"


def test_catalog_matches_gui_origins():
    gui_names = [name for name, _count in _gui_origins()]
    assert set(gui_names) == set(ohs.ORIGIN_HARDCODED_STARS), \
        "ORIGINS and ORIGIN_HARDCODED_STARS keys must match exactly"
    for name in DISABLED:
        assert name not in gui_names


def test_slot_count_matches_gui_bro_count():
    """For origins with a fixed bro count in the dropdown, the catalog should
    list exactly that many slots."""
    counts = {name: count for name, count in _gui_origins()}
    for origin, slots in ohs.ORIGIN_HARDCODED_STARS.items():
        count = counts.get(origin)
        if count is None:
            continue  # Random Party: 4-6 bros, rolled per seed
        assert len(slots) == count, f"{origin}: catalog has {len(slots)} slots, dropdown says {count}"


def test_every_origin_has_a_scenario_script_and_a_brother_count():
    assert [name for name, _count in _gui_origins()] == list(offline_origins.SCENARIO)
    assert offline_origins.COUNTS["Peasant Militia"] == 12 and offline_origins.COUNTS["Random Party"] is None
