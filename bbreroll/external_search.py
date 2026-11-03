"""A search in another Python: `python -m bbseed.search --events-json ...` as a child process, its events as if search() ran
here. The GUI uses this for the optional PyPy download (bbreroll/pypy_addon.py). No tkinter.

run(command, env, on_event, should_stop): one call per event, the same kinds and payloads as bbseed.search.search() sends
(JSON made the tuples lists: every reader unpacks them or calls tuple()), and always a last "finished". A child that dies, or a
line that is not an event, gives one "fatal" event and ends the child. Stop asks the child on its stdin, so its search ends as
a search does and shows the closest seed; a child that does not end in STOP_SECONDS is ended with its workers, by its exact PID.
"""
import json
import queue
import subprocess
import threading
import time

STOP_SECONDS = 5.0
POLL_SECONDS = 0.1
STOP_LINE = "stop\n"
CHILD_DIED = "The search process ended without a result (exit code %s)."
BROKEN_LINE = "The search process sent text that BB Reroll cannot read: %s"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class CannotStart(Exception):
    """The child did not start: the caller can search on in its own Python."""


def _end_tree(pid):
    """Ends a process and the processes it started, by its exact PID. A child that is gone already is no error."""
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)


def _read_lines(stream, lines):
    for line in stream:
        lines.put(line)
    lines.put(None)


def run(command, env, on_event, should_stop=None, cwd=None):
    """Raises CannotStart when the program cannot be started. Returns when the child has ended."""
    try:
        child = subprocess.Popen(command, env=env, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", bufsize=1,
                                 creationflags=NO_WINDOW)
    except OSError as e:
        raise CannotStart(str(e)) from e
    lines = queue.Queue()
    threading.Thread(target=_read_lines, args=(child.stdout, lines), daemon=True).start()
    tested, secs, found, finished = 0, 0.0, 0, False
    stop_asked = None
    failure = None
    try:
        while True:
            if should_stop is not None and stop_asked is None and should_stop():
                stop_asked = time.monotonic()
                try:
                    child.stdin.write(STOP_LINE)
                    child.stdin.flush()
                except OSError:
                    pass
            if stop_asked is not None and time.monotonic() - stop_asked > STOP_SECONDS:
                break
            try:
                line = lines.get(timeout=POLL_SECONDS)
            except queue.Empty:
                continue
            if line is None:
                break
            try:
                event = json.loads(line)
                kind, payload = event["kind"], event["payload"]
            except (ValueError, KeyError, TypeError):
                failure = BROKEN_LINE % line.strip()[:200]
                break
            if kind == "finished":
                finished = True
            elif kind == "progress":
                tested, secs = payload[0], payload[1]
            elif kind == "match":
                found += 1
            on_event(kind, payload)
    finally:
        _end_tree(child.pid)
        child.wait()
        child.stdin.close()
    if finished:
        return
    if failure is None and stop_asked is None:
        failure = CHILD_DIED % child.returncode
    if failure is not None:
        on_event("fatal", failure)
    on_event("finished", [tested, secs, found, stop_asked is not None or failure is not None])
