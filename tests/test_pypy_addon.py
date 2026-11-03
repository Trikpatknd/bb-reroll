"""The optional PyPy download: which folder counts, which searches use it, and the tool that builds it."""
import hashlib
import importlib.util
import io
import json
import sys
import textwrap
import zipfile
from pathlib import Path

import pytest

from bbreroll import pypy_addon as P


def make_folder(tmp_path, version="4.5.0", leave_out=()):
    folder = tmp_path / P.FOLDER
    for parts in P._NEEDED:
        if parts not in leave_out:
            path = folder.joinpath(*parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x", encoding="utf-8")
    folder.mkdir(exist_ok=True)
    if version is not None:
        (folder / "VERSION").write_text(version + "\n", encoding="utf-8")
    return folder


@pytest.mark.core
def test_no_folder_no_option(tmp_path):
    assert P.find(tmp_path, "4.5.0") == (None, "")


@pytest.mark.core
def test_a_folder_of_this_version_is_used(tmp_path):
    folder = make_folder(tmp_path)
    addon, reason = P.find(tmp_path, "4.5.0")
    assert reason == "" and addon.folder == folder
    assert addon.command(["--origin", "x"]) == [str(folder / "pypy" / "pypy3.exe"), "-m", "bbseed.search", "--origin", "x"]
    env = addon.env()
    assert env["PYPY_GC_NURSERY"] == "2M" and env["PYTHONPATH"] == str(folder) and "PYTHONHOME" not in env


@pytest.mark.dirty
def test_a_folder_of_another_version_is_ignored_and_says_why(tmp_path):
    make_folder(tmp_path, version="4.4.9")
    addon, reason = P.find(tmp_path, "4.5.0")
    assert addon is None
    assert "4.4.9" in reason and "4.5.0" in reason and reason.isascii()


@pytest.mark.dirty
@pytest.mark.parametrize("missing", [("pypy", "pypy3.exe"), ("bbseed", "search.py"), ("bbseed", "native_surface.json")])
def test_a_damaged_folder_is_ignored_and_says_why(tmp_path, missing):
    make_folder(tmp_path, leave_out=(missing,))
    addon, reason = P.find(tmp_path, "4.5.0")
    assert addon is None and "damaged" in reason and missing[-1] in reason


@pytest.mark.dirty
def test_a_folder_without_its_version_file_is_damaged(tmp_path):
    make_folder(tmp_path, version=None)
    addon, reason = P.find(tmp_path, "4.5.0")
    assert addon is None and "VERSION" in reason


@pytest.mark.core
def test_a_roster_search_never_uses_pypy():
    assert P.applies({"stars_by_slot": {"1": {"hp": 2}}}, "trader_scenario") is False
    assert P.applies({"banned": ["dumb"], "map": {"ports": 4}}, "trader_scenario") is False, "the roster comes first"
    assert P.applies({}, "trader_scenario") is False


@pytest.mark.core
def test_a_map_only_search_and_deserters_use_it():
    assert P.applies({"map": {"ports": 4}}, "trader_scenario") is True
    assert P.applies({}, "deserters_scenario") is True
    assert P.applies({"stars_by_slot": {"1": {"hp": 1}}}, "deserters_scenario") is True


@pytest.mark.core
def test_the_arguments_reach_the_command_line_parser(tmp_path):
    args = P.arguments("legends", "trader_scenario", tmp_path / "c.json", 8, 3, 100, {"mod_legends:Settlements": 24})
    for part in ("--events-json", "--origin", "trader_scenario", "--workers", "8", "--count", "3", "--max-seeds", "100",
                 "--profile", "legends", "--mod-setting", "mod_legends:Settlements=24"):
        assert part in args
    assert "--max-seeds" not in P.arguments(None, "x", "c", 1, 1, None, None)


class ScriptAddon:
    """An add-on whose "PyPy" is this Python running a small script."""

    def __init__(self, tmp_path, body):
        self.folder = tmp_path
        self.script = tmp_path / "child.py"
        self.script.write_text(textwrap.dedent(body), encoding="utf-8")

    def command(self, args):
        return [sys.executable, str(self.script)] + list(args)

    def env(self):
        import os
        return dict(os.environ)


def run_search(addon, should_stop=None):
    got = []
    why = P.search(addon, "legends", "trader_scenario", {"map": {"ports": 4}}, 2, 1, 10, None, lambda k, p: got.append((k, p)), should_stop)
    return why, got


@pytest.mark.core
def test_a_search_in_the_addon_sends_the_events_and_its_criteria_file_goes_away(tmp_path):
    seen = tmp_path / "seen.json"
    addon = ScriptAddon(tmp_path, """
        import json, sys
        path = sys.argv[sys.argv.index("--criteria") + 1]
        json.dump({"path": path, "criteria": json.load(open(path, encoding="utf-8")), "args": sys.argv[1:]}, open(%r, "w"))
        print(json.dumps({"kind": "ready", "payload": [1, 2, {}]}), flush=True)
        print(json.dumps({"kind": "finished", "payload": [3, 1.0, 0, False]}), flush=True)
    """ % str(seen))
    why, got = run_search(addon)
    assert why is None and [k for k, _p in got] == ["ready", "finished"]
    found = json.loads(seen.read_text())
    assert found["criteria"] == {"map": {"ports": 4}} and not Path(found["path"]).exists()


@pytest.mark.dirty
def test_a_failed_pypy_start_searches_on_with_the_exes_python(tmp_path):
    class Missing(ScriptAddon):
        def command(self, args):
            return [str(tmp_path / "no such pypy.exe")] + list(args)
    why, got = run_search(Missing(tmp_path, ""))
    assert why and "PyPy did not start" in why and got == []


@pytest.mark.dirty
def test_a_pypy_that_dies_before_its_workers_are_ready_counts_as_not_started(tmp_path):
    why, got = run_search(ScriptAddon(tmp_path, "import sys; sys.exit(7)"))
    assert why and "PyPy did not start" in why and got == [], "the caller searches on, with no fatal banner"


@pytest.mark.dirty
def test_a_pypy_that_dies_after_its_workers_are_ready_is_a_fatal_of_the_search(tmp_path):
    why, got = run_search(ScriptAddon(tmp_path, """
        import json, sys
        print(json.dumps({"kind": "ready", "payload": [1, 2, {}]}), flush=True)
        sys.exit(7)
    """))
    assert why is None and [k for k, _p in got] == ["ready", "fatal", "finished"]


@pytest.mark.edge
def test_a_stop_before_the_workers_are_ready_is_no_failed_start(tmp_path):
    why, got = run_search(ScriptAddon(tmp_path, """
        import os, sys, time
        while not os.path.exists(os.environ["BBSEED_STOP_FILE"]):
            time.sleep(0.02)
        sys.exit(1)
    """), should_stop=lambda: True)
    assert why is None and got[-1][0] == "finished" and got[-1][1][3] is True


def load_tool():
    path = Path(__file__).resolve().parent.parent / "tools" / "build_pypy_addon.py"
    spec = importlib.util.spec_from_file_location("build_pypy_addon", path)
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    return tool


def fake_pypy_zip(tool, path, licence=True):
    prefix = tool.PYPY_NAME + "/"
    with zipfile.ZipFile(path, "w") as z:
        for name in ("pypy3.exe", "libpypy3.11-c.dll", "Lib/os.py", "Lib/test/big.py", "tcl/x.tcl") + (("LICENSE",) if licence else ()):
            z.writestr(prefix + name, "x")
    return path


@pytest.mark.core
def test_the_tool_builds_a_folder_that_find_accepts(tmp_path, monkeypatch):
    tool = load_tool()
    pypy = fake_pypy_zip(tool, tmp_path / "pypy.zip")
    monkeypatch.setattr(tool, "PYPY_SHA256", tool.sha256(pypy))
    built = tool.build(pypy, tmp_path)
    version = (tool.ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert built.name == "bb_reroll_pypy-%s.zip" % version
    unpacked = tmp_path / "unpacked"
    with zipfile.ZipFile(built) as z:
        names = z.namelist()
        z.extractall(unpacked)
    assert "bb_reroll_pypy/pypy/LICENSE" in names, "PyPy's licence goes with it"
    assert not any("Lib/test" in n or "tcl/" in n or "__pycache__" in n for n in names)
    assert "bb_reroll_pypy/bbseed/sq/runtime.py" in names
    addon, why = P.find(unpacked, version)
    assert why == "" and addon is not None


@pytest.mark.dirty
def test_the_tool_refuses_a_zip_with_another_checksum_and_leaves_nothing(tmp_path):
    tool = load_tool()
    pypy = fake_pypy_zip(tool, tmp_path / "pypy.zip")
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(ValueError, match="SHA-256"):
        tool.build(pypy, out)
    assert list(out.iterdir()) == []


@pytest.mark.dirty
def test_the_tool_refuses_a_pypy_without_its_licence(tmp_path, monkeypatch):
    tool = load_tool()
    pypy = fake_pypy_zip(tool, tmp_path / "pypy.zip", licence=False)
    monkeypatch.setattr(tool, "PYPY_SHA256", tool.sha256(pypy))
    with pytest.raises(ValueError, match="LICENSE"):
        tool.build(pypy, tmp_path)


@pytest.mark.core
def test_the_tool_fetches_the_zip_it_checks(tmp_path, monkeypatch):
    tool = load_tool()
    data = b"the zip"
    asked = []

    class Answer(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(tool.urllib.request, "urlopen", lambda url, timeout: asked.append(url) or Answer(data))
    target = tool.fetch(tmp_path / "z.zip")
    assert asked == [tool.PYPY_URL] and target.read_bytes() == data
    assert tool.sha256(target) == hashlib.sha256(data).hexdigest()


@pytest.mark.dirty
def test_a_worker_that_cannot_load_counts_as_a_failed_start(tmp_path):
    """Damage that find() cannot see: a file of bbseed is missing. The real search's workers die at their import; it says so."""
    import shutil
    from pathlib import Path as P2
    from bbseed import search as real
    copy = tmp_path / "addon"
    shutil.copytree(P2(real.__file__).parent, copy / "bbseed", ignore=shutil.ignore_patterns("__pycache__", "world.py"))

    class Damaged(ScriptAddon):
        def __init__(self):
            self.folder = copy

        def command(self, args):
            return [sys.executable, "-m", "bbseed.search"] + list(args)

        def env(self):
            import os
            return dict(os.environ, PYTHONPATH=str(copy), PYTHONIOENCODING="utf-8")
    got = []
    why = P.search(Damaged(), "legends", "trader_scenario", {"map": {"ports": 4}}, 2, 1, 4, None, lambda k, p: got.append((k, p)))
    assert why and "PyPy did not start" in why
    assert [k for k, _p in got if k != "preparing"] == []


@pytest.mark.core
def test_the_criteria_file_goes_away_when_this_program_ends_during_a_search(tmp_path):
    import subprocess
    temp = tmp_path / "temp"
    temp.mkdir()
    started = tmp_path / "started.txt"
    child = tmp_path / "child.py"
    child.write_text(textwrap.dedent("""
        import json, time
        open(%r, "w").write("x")
        print(json.dumps({"kind": "ready", "payload": [1, 1, {}]}), flush=True)
        time.sleep(120)
    """ % str(started)), encoding="utf-8")
    parent = tmp_path / "parent.py"
    repo = str(Path(__file__).resolve().parent.parent)
    parent.write_text(textwrap.dedent("""
        import os, sys, threading, time
        from pathlib import Path
        sys.path.insert(0, %r)
        from bbreroll import pypy_addon

        class Script:
            folder = Path(%r)
            def command(self, args):
                return [sys.executable, %r] + list(args)
            def env(self):
                return dict(os.environ)

        def go():
            pypy_addon.search(Script(), "legends", "x", {}, 1, 1, 1, None, lambda k, p: None)
        threading.Thread(target=go, daemon=True).start()
        end = time.time() + 30
        while time.time() < end and not Path(%r).exists():
            time.sleep(0.05)
        time.sleep(0.5)
    """ % (repo, str(tmp_path), str(child), str(started))), encoding="utf-8")
    import os
    subprocess.run([sys.executable, str(parent)], env=dict(os.environ, PYTHONPATH=repo, TEMP=str(temp), TMP=str(temp)), timeout=60)
    assert started.exists() and list(temp.glob("bb_reroll_*")) == []
