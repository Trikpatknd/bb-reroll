"""Where test windows open (bbreroll/screens.py)."""
import pytest

from bbreroll import screens

MAIN = {"left": 0, "top": 0, "right": 2560, "bottom": 1440, "primary": True, "scale": 1.5}
SECOND = {"left": 3840, "top": -400, "right": 5280, "bottom": 2160, "primary": False, "scale": 1.0}


@pytest.mark.core
def test_a_test_window_opens_on_the_second_monitor():
    assert screens.window_position([MAIN, SECOND]) == "+3880+40"


@pytest.mark.edge
def test_the_order_of_the_monitors_does_not_matter():
    assert screens.window_position([SECOND, MAIN]) == "+3880+40"


@pytest.mark.edge
def test_a_second_monitor_above_the_main_one_keeps_its_own_rows():
    above = dict(SECOND, top=-1440, bottom=0)
    assert screens.window_position([MAIN, above]) == "+3880+-1400"


@pytest.mark.edge
def test_one_monitor_keeps_the_window_near_its_corner():
    assert screens.window_position([MAIN]) == "+40+40"


@pytest.mark.dirty
def test_no_monitor_found_keeps_the_window_near_the_corner():
    assert screens.window_position([]) == "+40+40"


@pytest.mark.core
def test_the_scale_is_the_scale_of_the_monitor_at_that_point():
    assert screens.scale_at(100, 100, [MAIN, SECOND]) == 1.5
    assert screens.scale_at(3880, 40, [MAIN, SECOND]) == 1.0


@pytest.mark.dirty
def test_a_point_on_no_monitor_has_no_scale():
    assert screens.scale_at(3000, 40, [MAIN, SECOND]) == 1.0


@pytest.mark.core
def test_this_computer_gives_monitors_with_one_main_monitor():
    found = screens.monitors()
    if found:       # (a machine with no desktop gives none)
        assert sum(m["primary"] for m in found) == 1 and all(m["right"] > m["left"] and m["scale"] > 0 for m in found)
