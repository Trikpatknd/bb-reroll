"""A search in another Python: its events through JSON (bbseed/search.py --events-json, bbreroll/external_search.py)."""
import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from bbreroll import external_search
from bbseed import search as S

REPO = str(Path(__file__).resolve().parent.parent)
EVENTS = [
    ("ready", (1, 2, {"mods": [], "legends_version": "19.4.22"})),
    ("progress", (5, 1.5, 0, {"chance": None, "never": [1], "maps": 0})),
    ("near", {"seed": "0000000003", "roster": None, "map": None, "distance": (0, 1, 0), "confirmed": False, "differences": []}),
    ("match", {"seed": "0000000004", "roster": [{"name": "Ä", "stars": {"hp": 1}}], "stable": True, "failure": None, "map": None}),
    ("notice", "text"),
    ("error", "bad seed"),
    ("finished", (9, 2.5, 1, False)),
]


def child_script(tmp_path, body):
    path = tmp_path / "child.py"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return [sys.executable, str(path)]


def run(command, should_stop=None):
    got = []
    external_search.run(command, dict(os.environ, PYTHONPATH=REPO, PYTHONIOENCODING="utf-8"), lambda k, p: got.append((k, p)), should_stop)
    return got


@pytest.mark.core
def test_the_events_are_the_same_through_json(tmp_path):
    (tmp_path / "events.json").write_text(json.dumps(EVENTS), encoding="utf-8")
    command = child_script(tmp_path, """
        import json, sys
        from pathlib import Path
        from bbseed import search as S
        events = json.loads((Path(__file__).parent / "events.json").read_text(encoding="utf-8"))
        def fake_search(profile, origin, criteria, **kw):
            for kind, payload in events:
                kw["on_event"](kind, payload)
            return []
        S.search = fake_search
        S.main(["--profile", "legends", "--origin", "trader_scenario", "--events-json"])
    """)
    got = run(command)
    assert [list(event) for event in got] == json.loads(json.dumps(EVENTS)), "one line per event, nothing else on the output"


@pytest.mark.core
def test_events_json_stops_when_the_stop_file_is_there(monkeypatch, capsys, tmp_path):
    seen = []

    def fake_search(profile, origin, criteria, **kw):
        seen.append(kw["should_stop"]())
        (tmp_path / "stop").write_text("x")
        seen.append(kw["should_stop"]())
        kw["on_event"]("finished", (0, 0.0, 0, True))
        return []
    monkeypatch.setattr(S, "search", fake_search)
    monkeypatch.setenv(S.STOP_FILE_VARIABLE, str(tmp_path / "stop"))
    S.main(["--profile", "legends", "--origin", "trader_scenario", "--events-json"])
    assert seen == [False, True]
    assert [json.loads(line) for line in capsys.readouterr().out.splitlines()] == [
        {"kind": "finished", "payload": [0, 0.0, 0, True]}]


@pytest.mark.core
def test_a_worker_process_really_starts_under_events_json(tmp_path):
    """2026-11-03: a thread reading stdin made every spawned worker hang at its start on Windows (and only with real workers:
    the stand-in search has none). The search reported nothing until the stop."""
    command = child_script(tmp_path, """
        import multiprocessing as mp, sys
        from bbseed import search as S

        def worker(out):
            out.put("started")

        def fake_search(profile, origin, criteria, **kw):
            ctx = mp.get_context("spawn")
            out = ctx.Queue()
            p = ctx.Process(target=worker, args=(out,), daemon=True)
            p.start()
            kw["on_event"]("notice", out.get(timeout=60))
            p.join(30)
            kw["on_event"]("finished", (0, 0.0, 0, False))
            return []

        if __name__ == "__main__":
            S.search = fake_search
            S.main(["--profile", "legends", "--origin", "trader_scenario", "--events-json"])
    """)
    began = time.time()
    got = run(command)
    assert [k for k, _p in got] == ["notice", "finished"] and got[0][1] == "started"
    assert time.time() - began < 60


@pytest.mark.core
def test_the_child_ends_when_this_program_ends(tmp_path):
    """The window closed during a search: no search goes on without it (a worker takes 1.5 GB)."""
    pid_file = tmp_path / "pid.txt"
    child = child_script(tmp_path, """
        import json, os, time
        open(%r, "w").write(str(os.getpid()))
        print(json.dumps({"kind": "ready", "payload": [1, 1, {}]}), flush=True)
        time.sleep(120)
    """ % str(pid_file))
    parent = tmp_path / "parent.py"
    parent.write_text(textwrap.dedent("""
        import os, sys, threading
        from pathlib import Path
        sys.path.insert(0, %r)
        from bbreroll import external_search

        def go():
            external_search.run(%r, dict(os.environ), lambda k, p: None)
        threading.Thread(target=go, daemon=True).start()
        pid = Path(%r)
        import time
        end = time.time() + 30
        while time.time() < end and not (pid.exists() and pid.read_text()):
            time.sleep(0.05)
        time.sleep(0.5)
    """ % (REPO, child, str(pid_file))), encoding="utf-8")
    subprocess.run([sys.executable, str(parent)], env=dict(os.environ, PYTHONPATH=REPO), timeout=60)
    deadline = time.time() + 10
    pid = int(pid_file.read_text())
    while time.time() < deadline and alive(pid):
        time.sleep(0.1)
    assert not alive(pid)


def alive(pid):
    out = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid, "/NH"], capture_output=True, text=True).stdout
    return str(pid) in out


@pytest.mark.core
def test_stop_ends_the_child_and_its_workers(tmp_path, monkeypatch):
    """A child that does not answer the stop: it and the process it started end all the same, by the exact PID."""
    monkeypatch.setattr(external_search, "STOP_SECONDS", 0.5)
    pids = tmp_path / "pids.txt"
    command = child_script(tmp_path, """
        import json, os, subprocess, sys, time
        worker = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        open(%r, "w").write("%%d %%d" %% (os.getpid(), worker.pid))
        print(json.dumps({"kind": "ready", "payload": [1, 1, {}]}), flush=True)
        time.sleep(120)
    """ % str(pids))
    began = time.time()
    got = run(command, should_stop=lambda: pids.exists() and pids.read_text().strip() != "")
    assert time.time() - began < 30
    child, worker = map(int, pids.read_text().split())
    assert not alive(child) and not alive(worker)
    assert got[-1] == ("finished", [0, 0.0, 0, True])
    assert "fatal" not in [k for k, _p in got], "a Stop is no error"


@pytest.mark.core
def test_a_child_that_answers_the_stop_ends_as_a_search_does(tmp_path):
    ready = tmp_path / "ready.txt"
    command = child_script(tmp_path, """
        import json, os, time
        print(json.dumps({"kind": "ready", "payload": [1, 1, {}]}), flush=True)
        open(%r, "w").write("x")
        while not os.path.exists(os.environ["BBSEED_STOP_FILE"]):
            time.sleep(0.02)
        print(json.dumps({"kind": "near", "payload": {"seed": "1"}}), flush=True)
        print(json.dumps({"kind": "finished", "payload": [7, 1.0, 0, True]}), flush=True)
    """ % str(ready))
    got = run(command, should_stop=ready.exists)
    assert [k for k, _p in got] == ["ready", "near", "finished"] and got[-1][1] == [7, 1.0, 0, True]


@pytest.mark.dirty
def test_a_child_that_dies_gives_a_fatal_event(tmp_path):
    command = child_script(tmp_path, """
        import json, sys
        print(json.dumps({"kind": "progress", "payload": [4, 2.0, 0, {}]}), flush=True)
        sys.exit(3)
    """)
    got = run(command)
    assert [k for k, _p in got] == ["progress", "fatal", "finished"]
    assert got[1][1] == external_search.CHILD_DIED % 3
    assert got[2][1] == [4, 2.0, 0, True]


@pytest.mark.dirty
def test_a_broken_line_of_output_gives_a_fatal_event(tmp_path):
    command = child_script(tmp_path, """
        import time
        print("this is not an event", flush=True)
        time.sleep(120)
    """)
    began = time.time()
    got = run(command)
    assert time.time() - began < 30
    assert [k for k, _p in got] == ["fatal", "finished"] and "this is not an event" in got[0][1]


@pytest.mark.dirty
def test_a_program_that_cannot_start_raises_for_the_caller(tmp_path):
    with pytest.raises(external_search.CannotStart):
        run([str(tmp_path / "no such program.exe")])


@pytest.mark.core
def test_the_stop_folder_goes_away_when_this_program_ends_during_a_search(tmp_path):
    """The run's thread is a daemon: its own clean-up does not run when the window closes."""
    temp = tmp_path / "temp"
    temp.mkdir()
    pid_file = tmp_path / "pid.txt"
    child = child_script(tmp_path, """
        import json, os, time
        open(%r, "w").write(str(os.getpid()))
        print(json.dumps({"kind": "ready", "payload": [1, 1, {}]}), flush=True)
        time.sleep(120)
    """ % str(pid_file))
    parent = tmp_path / "parent.py"
    parent.write_text(textwrap.dedent("""
        import os, sys, threading, time
        from pathlib import Path
        sys.path.insert(0, %r)
        from bbreroll import external_search

        def go():
            external_search.run(%r, dict(os.environ), lambda k, p: None)
        threading.Thread(target=go, daemon=True).start()
        pid = Path(%r)
        end = time.time() + 30
        while time.time() < end and not (pid.exists() and pid.read_text()):
            time.sleep(0.05)
        time.sleep(0.5)
    """ % (REPO, child, str(pid_file))), encoding="utf-8")
    subprocess.run([sys.executable, str(parent)], env=dict(os.environ, PYTHONPATH=REPO, TEMP=str(temp), TMP=str(temp)), timeout=60)
    assert not alive(int(pid_file.read_text()))
    assert list(temp.glob("bb_reroll_stop_*")) == []


@pytest.mark.core
def test_two_runs_at_once_keep_their_own_clean_up(tmp_path):
    """One run's end must not take away the clean-up of another."""
    import atexit
    calls = []
    real_register, real_unregister = atexit.register, atexit.unregister
    registered = []
    try:
        atexit.register = lambda f, *a: registered.append(f)
        atexit.unregister = lambda f: calls.append(f)
        run(child_script(tmp_path, "pass"))
    finally:
        atexit.register, atexit.unregister = real_register, real_unregister
    assert len(registered) == 1 and calls == registered, "the function of this run, not one shared by all runs"
    assert registered[0] is not external_search._end_tree
