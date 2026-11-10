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


WORK_MAIN = dict(MAIN, work=(0, 0, 2560, 1392))         # (a taskbar 48 high)
WORK_SECOND = dict(SECOND, work=(3840, -400, 5280, 2112))
SIZE = (1000, 960)


@pytest.mark.core
def test_a_saved_place_that_fits_stays():
    assert screens.start_geometry("1000x960+200+150", SIZE, [WORK_MAIN, WORK_SECOND]) == "1000x960+200+150"
    assert screens.start_geometry("1000x960+4000+0", SIZE, [WORK_MAIN, WORK_SECOND]) == "1000x960+4000+0"


@pytest.mark.core
def test_a_window_low_on_the_screen_moves_up_so_search_shows():
    # the reported case: 1000x960 at 150 % placed low on the 1440-pixel screen
    assert screens.start_geometry("1000x960+300+700", SIZE, [WORK_MAIN]) == "1000x960+300+392"


@pytest.mark.core
def test_no_saved_place_centres_the_window_on_the_main_monitor():
    assert screens.start_geometry(None, SIZE, [WORK_SECOND, WORK_MAIN]) == "1000x960+780+196"


@pytest.mark.edge
def test_a_window_on_a_monitor_that_is_gone_moves_to_the_main_one():
    assert screens.start_geometry("1000x960+4000+0", SIZE, [WORK_MAIN]) == "1000x960+1560+0"


@pytest.mark.edge
def test_a_window_larger_than_the_screen_shrinks_to_it():
    small = dict(MAIN, right=1366, bottom=768, work=(0, 0, 1366, 728))
    assert screens.start_geometry("1000x960+0+0", SIZE, [small]) == "1000x688+0+0"


@pytest.mark.edge
def test_a_monitor_left_of_the_main_one_keeps_its_negative_place():
    left = dict(SECOND, left=-1440, right=0, top=0, bottom=2560, work=(-1440, 0, 0, 2512))
    assert screens.start_geometry("1000x960+-1300+100", SIZE, [WORK_MAIN, left]) == "1000x960+-1300+100"


@pytest.mark.dirty
def test_no_monitor_found_keeps_what_was_saved():
    assert screens.start_geometry("1000x960+300+700", SIZE, []) == "1000x960+300+700"
    assert screens.start_geometry(None, SIZE, []) == "1000x960"


@pytest.mark.dirty
def test_a_saved_place_in_another_form_is_not_used():
    assert screens.start_geometry("1000x960-20+30", SIZE, [WORK_MAIN]) == "1000x960+780+196"
    assert screens.start_geometry("big", SIZE, [WORK_MAIN]) == "1000x960+780+196"


@pytest.mark.core
def test_this_computer_gives_monitors_with_one_main_monitor():
    found = screens.monitors()
    if found:       # (a machine with no desktop gives none)
        assert sum(m["primary"] for m in found) == 1 and all(m["right"] > m["left"] and m["scale"] > 0 for m in found)
