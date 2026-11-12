"""Make the repo root importable from tests without installing the project, the test tiers, and the labs the
game tests share.

Tiers: `python -m pytest` runs the fast tier (every test not marked `slow`); `python -m pytest --full` runs
everything (the final review); add `-n 4` (pytest-xdist, one worker process each, a lab is ~1 GB, at most 18 processes
in all) to run them side by side. `slow` = a test whose setup + call took more than ~5 s when measured (whole maps,
real search workers, game rosters): the `@pytest.mark.slow` lines of the test files list them. A test named by its
node id on the command line (`tests/test_x.py::test_y`) always runs, and so does anything selected with `-m`.

Categories: every test function has exactly one of three markers, and collection stops with an error when one has none or
several. Decide in this order. `dirty`: invalid, malformed, missing or failing input or environment, and how it is
handled. `edge`: valid input at a limit or an unusual case or combination. `core`: ordinary valid input, the main
behaviour. A test with a failure check beside other checks is two tests: `pytest.raises` belongs in `dirty` tests.
`python -m pytest -m core` runs one category (slow tests too); `-m "core and not slow"` the fast part of it.

Labs: booting a Legends lab takes ~15 s, a Vanilla one ~4 s, so the game tests that only READ a lab share one per
test session (`legends_lab`, `vanilla_lab` below; the lab is booted by the first test that asks for it). A test that
needs a fresh or an altered lab (another profile or Mod Options, `watch_rolls()`, a TalentWatch that wraps the player
class for good) makes its own.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------- tiers
def pytest_addoption(parser, pluginmanager):
    # pytest.ini sets `--dist=loadgroup` (every test on a free worker of its own, the xdist_group tests together); without
    # pytest-xdist the option would be unknown, so it is accepted and ignored then
    if not pluginmanager.hasplugin("xdist"):
        parser.addoption("--dist", default="no", help="accepted without pytest-xdist; no effect")
    parser.addoption("--full", action="store_true", default=False,
                     help="run every test, the slow ones (whole maps, labs, search workers) too")


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: setup + call over ~5 s; runs only with --full (or -m slow / a node id)")
    config.addinivalue_line("markers", "xdist_group(name): tests of one group run on one pytest-xdist worker, in order")
    config.addinivalue_line("markers", "core: ordinary valid input, the main behaviour")
    config.addinivalue_line("markers", "edge: valid input at a limit or an unusual case or combination")
    config.addinivalue_line("markers", "dirty: invalid, missing or failing input or environment, and how it is handled")



def _xdist_group(item):
    """The pytest-xdist group of a test: the tests that must share one worker under `-n`. A test that uses the session labs
    runs where one is booted (~15 s, ~1 GB each); `town_maps` / `vanilla_maps` are built once for their tests; the GUI tests
    share their one Tk window; test_offline_map has a lab of its own for its two maps."""
    names = set(item.fixturenames)
    if "town_maps" in names:
        return "mapgen_maps"
    if "vanilla_maps" in names:
        return "mapgen_vanilla"
    if names & {"legends_lab", "vanilla_lab"}:
        return "labs"
    return {"test_gui_search_start": "gui", "test_offline_map": "offline_map",
            "test_offline_trade": "offline_trade"}.get(item.module.__name__)


@pytest.hookimpl(tryfirst=True)       # before pytest-xdist adds the group names to the node ids
def pytest_collection_modifyitems(config, items):
    wrong = [item.nodeid for item in items
             if len({mark.name for mark in item.iter_markers()} & {"core", "edge", "dirty"}) != 1]
    if wrong:
        raise pytest.UsageError("every test needs exactly one of core / edge / dirty (conftest.py):\n  " + "\n  ".join(wrong))
    for item in items:
        group = _xdist_group(item)
        if group and not item.get_closest_marker("xdist_group"):
            item.add_marker(pytest.mark.xdist_group(group))
    if config.option.markexpr or config.getoption("--full"):
        return
    named = [str(a).replace("\\", "/") for a in config.args if "::" in str(a)]
    keep, dropped = [], []
    for item in items:
        slow = item.get_closest_marker("slow") and not any(item.nodeid.replace("\\", "/").startswith(n) for n in named)
        (dropped if slow else keep).append(item)
    if dropped:
        config.hook.pytest_deselected(items=dropped)
        items[:] = keep


def pytest_report_header(config):
    return "tiers: --full also runs the slow tests (whole maps, labs, search workers); without it they are deselected"


# ---------------------------------------------------------------- the GUI window's garbage
def pytest_fixture_post_finalizer(fixturedef, request):
    """After the GUI tests' window fixture (`app`, test_gui_search_start.py) is gone, collect its garbage HERE, on the main
    thread: tkinter's Variable.__del__ talks to Tcl, and when the collector runs it later inside a lab's big_stack thread
    (a lab booted by a test of a later module) it waits for the main thread's event loop for ever. Seen when the files
    ran in reverse order (test_gui_search_start before test_game_features): the run hung in the lab boot."""
    if fixturedef.argname == "app":
        import gc
        gc.collect()


# ---------------------------------------------------------------- shared labs
class InBigStack:
    """A lab whose every method call runs inside big_stack() (the interpreter recurses deeply: a Lab
    must only be called from such a thread). Attributes that are not methods are passed through; `.lab`
    is the Lab itself."""

    def __init__(self, lab):
        self.lab = lab

    def __getattr__(self, name):
        from bbseed.lab import big_stack
        attr = getattr(self.lab, name)
        if not callable(attr):
            return attr
        return lambda *args, **kwargs: big_stack(lambda: attr(*args, **kwargs))


def _have_game():
    from bbseed import profiles
    found = profiles.installed_summary()
    return found, found is not None and found["game_version"] == "1.5.2.3"


@pytest.fixture(scope="session")
def legends_lab():
    """One Legends lab (default Mod Options) for the whole session, in InBigStack. Skips without Legends 19.4.22 +
    MSU 1.9.0 on 1.5.2.3. Tests that call `world_map` or `roster` leave it usable: both build a fresh world state."""
    found, have = _have_game()
    if not (have and any("mod_legends-19.4.22" in m for m in found["mods"]) and any("1.9.0" in m for m in found["mods"])):
        pytest.skip("Battle Brothers 1.5.2.3 with Legends 19.4.22 + MSU 1.9.0 is not installed")
    from bbseed.lab import Lab, big_stack
    lab = InBigStack(big_stack(lambda: Lab("legends")))
    info = lab.info()
    if (info["game_version"], info["legends_version"]) != ("1.5.2.3", "19.4.22"):
        pytest.skip("the lab did not load Legends 19.4.22 on 1.5.2.3: %r" % ((info["game_version"], info["legends_version"]),))
    return lab


@pytest.fixture(scope="session")
def vanilla_lab():
    """One Vanilla lab (no mods) for the whole session, in InBigStack. Skips without Battle Brothers 1.5.2.3."""
    _found, have = _have_game()
    if not have:
        pytest.skip("Battle Brothers 1.5.2.3 is not installed")
    from bbseed.lab import Lab, big_stack
    return InBigStack(big_stack(lambda: Lab("vanilla")))
