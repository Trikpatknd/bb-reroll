"""The game's own campaign start, run in the lab up to the generated world (Legends 19.4.22 + MSU 1.9.0 +
Modern Hooks 0.6.0 on Battle Brothers 1.5.2.3). One lab is shared by the whole module: booting one takes
~15 s. Skipped when that game / those mods are not installed."""
import pytest

from bbseed import profiles

FOUND = profiles.installed_summary()
HAVE_GAME = FOUND is not None and FOUND["game_version"] == "1.5.2.3"
HAVE_LEGENDS = HAVE_GAME and any("mod_legends-19.4.22" in m for m in FOUND["mods"]) and any("1.9.0" in m for m in FOUND["mods"])


class InBigStack:
    """A lab whose every method call runs inside big_stack() (the interpreter recurses deeply: a Lab
    must only be called from such a thread). Attributes that are not methods are passed through."""

    def __init__(self, lab):
        self.lab = lab

    def __getattr__(self, name):
        from bbseed.lab import big_stack
        attr = getattr(self.lab, name)
        if not callable(attr):
            return attr
        return lambda *args, **kwargs: big_stack(lambda: attr(*args, **kwargs))


@pytest.fixture(scope="module")
def legends_lab():
    if not HAVE_LEGENDS:
        pytest.skip("Battle Brothers 1.5.2.3 with Legends 19.4.22 + MSU 1.9.0 is not installed")
    from bbseed.lab import Lab, big_stack
    lab = InBigStack(big_stack(lambda: Lab("legends")))
    info = lab.info()
    if (info["game_version"], info["legends_version"]) != ("1.5.2.3", "19.4.22"):
        pytest.skip("the lab did not load Legends 19.4.22 on 1.5.2.3: %r" % ((info["game_version"], info["legends_version"]),))
    return lab


def test_legends_map_reaches_world_accepted(legends_lab):
    out = legends_lab.world_map("1234567890", stop_at="accepted")
    lands = [l for l in out["log"] if l.startswith("Land Ocean ratio")]
    assert lands and out["log"][-1] == "World accepted."
    assert out["draws"] > 140 * 170          # one land/sea draw per tile at least
    needed = {"getTileSquare", "getNextTile", "hasNextTile", "getSurroundingTilesOfType", "spawnDetail", "setBrush"}
    assert not {n for (_k, n) in out["stub_uses"]} & needed      # modelled, not stubbed


def _natives(eng):
    """The natives a map run replaces while it runs: ::World's, ::Math's and the root table's."""
    from bbseed.sq.runtime import NativeFn
    return {(name, k): v for name, table in (("World", eng.World), ("Math", eng.Math), ("root", eng.root))
            for k, v in table.d.items() if type(v) is NativeFn}


def test_world_map_leaves_roster_path_unchanged(legends_lab):
    before = legends_lab.roster("1234567890", "trader_scenario", fresh=True)
    natives, world_keys = _natives(legends_lab.lab.eng), set(legends_lab.lab.eng.World.d)
    legends_lab.world_map("1234567890", stop_at="accepted")
    assert _natives(legends_lab.lab.eng) == natives and set(legends_lab.lab.eng.World.d) == world_keys, \
        "the run takes its natives (tiles, seed wrappers, top bar ...) away again"
    assert legends_lab.roster("1234567890", "trader_scenario", fresh=True) == before


def test_a_sift_roster_after_a_map_is_the_fresh_one(legends_lab):
    """The search's sift loop reuses the world state (fresh=False); a map run must not leave it a
    half-started campaign."""
    fresh = legends_lab.roster("0000000001", "trader_scenario", fresh=True)
    legends_lab.world_map("1234567890", stop_at="accepted")
    assert legends_lab.roster("0000000001", "trader_scenario", fresh=False) == fresh


def test_a_map_does_not_depend_on_the_maps_made_before(legends_lab):
    """The tile world is reused between maps (blanked, not rebuilt): nothing of one map may leak into the
    next. A map in another layout first, so that `first` is made on newly built tiles."""
    from bbseed import hexmap, mapgen
    other = next(layout for layout in hexmap.LAYOUTS if layout != mapgen.LAYOUT)
    assert legends_lab.world_map("0000000002", stop_at="accepted", layout=other)["log"][-1] == "World accepted."
    first = legends_lab.world_map("1234567890", stop_at="accepted")
    again = legends_lab.world_map("1234567890", stop_at="accepted")
    assert again["log"] == first["log"] and again["draws"] == first["draws"]
    # this run's stub uses only (the engine's total since start-up is never empty): up to "World accepted."
    # every native is modelled or an explained no-op
    assert again["stub_uses"] == first["stub_uses"] == {}
