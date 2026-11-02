"""Deserters' start loop without the game (bbseed/mapgen.py, "The start"): the draws of n iterations at the map edges
and the settlement the loop circles. The game tests (whole maps, the start without a map) are in test_mapgen_game.py."""
import pytest

from bbseed import mapgen

SIZE = (140, 170)        # Const.World.Settings.SizeX / SizeY of both setups


@pytest.mark.core
def test_full_ranges_in_the_middle():
    assert mapgen.loop_ranges((70, 85), SIZE) == ((63, 77), (78, 92))
    assert mapgen.deserters_loop_draws((70, 85), 9, SIZE) == 18


@pytest.mark.edge
def test_no_fort_square_means_the_full_ranges():
    assert mapgen.deserters_loop_draws(None, 23, None) == 46
    assert mapgen.deserters_loop_draws(None, 0, SIZE) == 0


@pytest.mark.edge
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


@pytest.mark.edge
def test_a_range_of_one_value_draws_nothing():
    # engine fact 1: rand(a, a) draws nothing; on a 4 x 4 map both ranges are 2 .. 2
    assert mapgen.loop_ranges((1, 3), (4, 4)) == ((2, 2), (2, 2))
    assert mapgen.deserters_loop_draws((1, 3), 7, (4, 4)) == 0
    # 5 wide, 4 high: x has 2 .. 3 (one draw), y 2 .. 2 (none)
    assert mapgen.deserters_loop_draws((0, 0), 7, (5, 4)) == 7
    # an empty range (hi < lo: Size 3) draws nothing either (rand(2, 1))
    assert mapgen.loop_ranges((0, 0), (3, 3)) == ((2, 1), (2, 1))
    assert mapgen.deserters_loop_draws((0, 0), 3, (3, 3)) == 0


@pytest.mark.edge
def test_every_square_of_a_side_of_5_or_more_draws_twice():
    for side in (5, 6, 10, 18, 140):
        for x in range(side):
            assert mapgen.deserters_loop_draws((x, x), 1, (side, side)) == 2, (side, x)


@pytest.mark.dirty
def test_bad_arguments():
    with pytest.raises(ValueError):
        mapgen.deserters_loop_draws(None, -1)
    with pytest.raises(ValueError):
        mapgen.deserters_loop_draws((3, 3), 1, None)


@pytest.mark.core
def test_the_fort_is_the_first_military_one_on_the_roads_and_not_southern():
    # [military, isolated, southern] per settlement, in getSettlements() order
    flags = [[False, False, False], [True, True, False], [True, False, True], [True, False, False], [True, False, False]]
    assert mapgen.fort_index(flags) == 3


@pytest.mark.edge
def test_without_a_qualifying_fort_the_loop_ends_on_the_last_settlement():
    assert mapgen.fort_index([[True, True, False], [False, False, False], [True, False, True]]) == 2
    assert mapgen.fort_index([[False, False, False]]) == 0
    assert mapgen.fort_index([]) is None


@pytest.mark.core
def test_spawn_is_a_stop():
    assert mapgen.STOPS == ("accepted", "reseed", "spawn")
    assert mapgen.SPAWN_LOOP_CAP == 100000


@pytest.mark.dirty
def test_a_start_loop_that_has_tried_every_square_ends_with_an_error():
    """The checks of one square never change, so the loop remembers the squares that failed: a map on which none passes
    raises as soon as the last square of the ranges has failed, not after SPAWN_LOOP_CAP iterations."""
    loop = mapgen.StartLoop(((10, 11), (20, 21)))          # 2 x 2 squares
    assert loop.total == 4
    squares = [(10, 20), (11, 21), (10, 20), (11, 20), (10, 20), (10, 21)]
    answers = [loop.enter(x, y) for x, y in squares[:5]]
    assert answers == [False, False, True, False, True], "a square that failed before is answered at once"
    assert loop.enter(*squares[5]) is False        # the 4th different square (10, 21): it may still pass
    with pytest.raises(mapgen.MapError, match="all 4 squares"):
        loop.enter(10, 20)                  # the loop went on: (10, 21) failed too, so all 4 have failed


@pytest.mark.edge
def test_a_range_with_one_value_or_none_counts_one_value():
    assert mapgen.StartLoop(((5, 5), (7, 9))).total == 3
    assert mapgen.StartLoop(((6, 5), (7, 6))).total == 1       # hi < lo: rand gives lo, nothing is drawn
    assert mapgen.StartLoop(mapgen.loop_ranges((70, 85), SIZE)).total == 15 * 15
