"""Is the number of workers more than this computer can carry?"""
import sys

import pytest

from bbreroll import worker_load as W

GB = 1 << 30


@pytest.mark.core
def test_the_figure_per_worker_is_by_setup_and_python():
    assert W.gb_per_worker(vanilla=False, pypy=False) == 1.0
    assert W.gb_per_worker(vanilla=False, pypy=True) == 1.5
    assert W.gb_per_worker(vanilla=True, pypy=False) == 0.35
    assert W.gb_per_worker(vanilla=True, pypy=True) == 0.55


@pytest.mark.core
def test_workers_that_fit_give_no_line():
    assert W.problems(8, 24, 1.0, (64 * GB, 40 * GB)) == []
    assert W.problems(18, 24, 1.0, (64 * GB, 21 * GB)) == [], "18 of the 18.9 GB that can be used"


@pytest.mark.core
def test_too_many_workers_for_the_memory_say_how_many_fit():
    (line,) = W.problems(18, 24, 1.5, (32 * GB, 16 * GB))
    assert line == "Workers: 18 workers need approximately 27 GB of memory, and 16 GB is free now. Use 9 workers or less."
    assert line.isascii()


@pytest.mark.edge
def test_the_limit_leaves_some_free_memory_for_the_rest_of_the_computer():
    assert W.most_workers(10 * GB, 1.0) == 9
    assert W.problems(10, 24, 1.0, (32 * GB, 10 * GB)) != []
    assert W.problems(9, 24, 1.0, (32 * GB, 10 * GB)) == []


@pytest.mark.edge
def test_not_even_one_worker_fits():
    (line,) = W.problems(1, 8, 1.0, (8 * GB, GB // 2))
    assert line == "Workers: 1 worker needs approximately 1.0 GB of memory, and 0.5 GB is free now. Close other programs."


@pytest.mark.edge
def test_workers_on_all_threads_warn_and_one_thread_less_does_not():
    plenty = (256 * GB, 200 * GB)
    assert W.problems(23, 24, 1.0, plenty) == []
    (line,) = W.problems(24, 24, 1.0, plenty)
    assert "24 processor threads" in line and "Use 23 workers or less" in line
    assert W.problems(1, 1, 1.0, plenty) == [], "a one-thread computer has no smaller number to offer"


@pytest.mark.edge
def test_both_problems_give_two_lines_memory_first():
    lines = W.problems(8, 8, 1.0, (8 * GB, 4 * GB))
    assert len(lines) == 2 and "memory" in lines[0] and "threads" in lines[1]


@pytest.mark.dirty
def test_a_memory_that_cannot_be_read_gives_no_memory_line():
    assert W.problems(100, 200, 1.0, None) == []
    assert W.memory_is_low(None) is None


@pytest.mark.dirty
@pytest.mark.parametrize("workers", [None, 0, -1])
def test_a_workers_field_that_is_no_number_is_another_checks_matter(workers):
    assert W.problems(workers, 8, 1.0, (8 * GB, GB)) == []


@pytest.mark.core
def test_a_search_is_told_when_the_memory_is_almost_full():
    assert W.memory_is_low((64 * GB, 10 * GB)) is None
    line = W.memory_is_low((64 * GB, 2 * GB))
    assert line and "2.0 GB" in line and "Stop the search" in line, "under 5 % of 64 GB"
    assert W.memory_is_low((8 * GB, GB // 2)), "under 1 GB, also where that is more than 5 %"
    assert W.memory_is_low((8 * GB, 2 * GB)) is None


@pytest.mark.core
@pytest.mark.skipif(sys.platform != "win32", reason="the memory call of Windows")
def test_the_real_memory_call_gives_plausible_numbers():
    total, available = W.memory()
    assert GB < total < 1 << 45 and 0 < available <= total


@pytest.mark.dirty
def test_the_memory_is_not_read_off_windows(monkeypatch):
    monkeypatch.setattr(W.sys, "platform", "linux")
    assert W.memory() is None
