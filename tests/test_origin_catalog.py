"""Integrity checks for the per-origin hardcoded-stars catalog and its
agreement with the GUI's ORIGINS dropdown list."""
import ast
from pathlib import Path

from bbreroll import origin_hardcoded_stars as ohs

ROOT = Path(__file__).resolve().parent.parent

VALID_STATS = {"hp", "fat", "res", "init", "msk", "rsk", "mdf", "rdf"}
# Hard-disabled scenarios (isValid() == false) that must never be offered.
DISABLED = {"Build your own", "Druid [Legacy]", "Horse Party", "Mage"}


def _gui_origins():
    """ORIGINS list from gui.py via ast — avoids importing customtkinter."""
    tree = ast.parse((ROOT / "gui.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "ORIGINS" for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("ORIGINS not found in gui.py")


def test_catalog_has_expected_count():
    # 12 vanilla Legends-hooked + 17 Legends-added + Custom.
    assert len(ohs.ORIGIN_HARDCODED_STARS) == 30


def test_custom_present_and_empty():
    assert "Custom" in ohs.ORIGIN_HARDCODED_STARS
    assert ohs.ORIGIN_HARDCODED_STARS["Custom"] == []


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
        "gui.py ORIGINS and ORIGIN_HARDCODED_STARS keys must match exactly"
    for name in DISABLED:
        assert name not in gui_names


def test_slot_count_matches_gui_bro_count():
    """For origins with a fixed bro count in the dropdown, the catalog should
    list exactly that many slots (Custom has count None and an empty list)."""
    counts = {name: count for name, count in _gui_origins()}
    for origin, slots in ohs.ORIGIN_HARDCODED_STARS.items():
        count = counts.get(origin)
        if count is None:
            continue  # Custom / manual
        assert len(slots) == count, f"{origin}: catalog has {len(slots)} slots, dropdown says {count}"
