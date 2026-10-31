"""Deserters' start loop without the game (bbseed/mapgen.py, "The start"): the draws of n iterations at the map edges
and the settlement the loop circles. The game tests (whole maps, the start without a map) are in test_mapgen_game.py."""
import pytest

from bbseed import mapgen

SIZE = (140, 170)        # Const.World.Settings.SizeX / SizeY of both setups


def test_full_ranges_in_the_middle():
    assert mapgen.loop_ranges((70, 85), SIZE) == ((63, 77), (78, 92))
    assert mapgen.deserters_loop_draws((70, 85), 9, SIZE) == 18


def test_no_fort_square_means_the_full_ranges():
    assert mapgen.deserters_loop_draws(None, 23, None) == 46
    assert mapgen.deserters_loop_draws(None, 0, SIZE) == 0


@pytest.mark.parametrize("fort, ranges", [
    ((0, 0), ((2, 7), (2, 7))),                      # the low corner: max(2, X - 7) = 2
    ((8, 8), ((2, 15), (2, 15))),                    # X - 7 = 1: clamped to 2
    ((9, 9), ((2, 16), (2, 16))),                    # the first square with the full low side
    ((139, 169), ((132, 138), (162, 168))),          # the high corner: min(Size - 2, X + 7) = Size - 2
    ((131, 161), ((124, 138), (154, 168))),          # X + 7 = Size - 2: the last square with the full high side
])
def test_clamped_ranges_at_the_edges_still_draw_twice(fort, ranges):
    assert mapgen.loop_ranges(fort, SIZE) == ranges
    assert mapgen.deserters_loop_draws(fort, 5, SIZE) == 10


def test_a_range_of_one_value_draws_nothing():
    # engine fact 1: rand(a, a) draws nothing; on a 4 x 4 map both ranges are 2 .. 2
    assert mapgen.loop_ranges((1, 3), (4, 4)) == ((2, 2), (2, 2))
    assert mapgen.deserters_loop_draws((1, 3), 7, (4, 4)) == 0
    # 5 wide, 4 high: x has 2 .. 3 (one draw), y 2 .. 2 (none)
    assert mapgen.deserters_loop_draws((0, 0), 7, (5, 4)) == 7
    # an empty range (hi < lo: Size 3) draws nothing either (rand(2, 1))
    assert mapgen.loop_ranges((0, 0), (3, 3)) == ((2, 1), (2, 1))
    assert mapgen.deserters_loop_draws((0, 0), 3, (3, 3)) == 0


def test_every_square_of_a_side_of_5_or_more_draws_twice():
    for side in (5, 6, 10, 18, 140):
        for x in range(side):
            assert mapgen.deserters_loop_draws((x, x), 1, (side, side)) == 2, (side, x)


def test_bad_arguments():
    with pytest.raises(ValueError):
        mapgen.deserters_loop_draws(None, -1)
    with pytest.raises(ValueError):
        mapgen.deserters_loop_draws((3, 3), 1, None)


def test_the_fort_is_the_first_military_one_on_the_roads_and_not_southern():
    # [military, isolated, southern] per settlement, in getSettlements() order
    flags = [[False, False, False], [True, True, False], [True, False, True], [True, False, False], [True, False, False]]
    assert mapgen.fort_index(flags) == 3


def test_without_a_qualifying_fort_the_loop_ends_on_the_last_settlement():
    assert mapgen.fort_index([[True, True, False], [False, False, False], [True, False, True]]) == 2
    assert mapgen.fort_index([[False, False, False]]) == 0
    assert mapgen.fort_index([]) is None


def test_spawn_is_a_stop():
    assert mapgen.STOPS == ("accepted", "reseed", "spawn")
    assert mapgen.SPAWN_LOOP_CAP == 100000
