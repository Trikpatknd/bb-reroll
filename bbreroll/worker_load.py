"""Is the number of workers more than this computer can carry? No tkinter: the window shows the lines.

A search runs one process per worker, and each holds the whole game's scripts in memory. Too many of them fill the memory (a
16-worker Legends run coincided with a PC crash on 2026-10-15). This only warns: the player decides.

    memory()                                   -> (total bytes, available bytes), or None when it cannot be read
    gb_per_worker(vanilla, pypy)               -> the most one worker uses
    most_workers(available, per_worker)        -> how many fit into the free memory
    problems(workers, threads, per_worker, found_memory) -> lines for the player, [] when it fits
    memory_is_low(found_memory)                -> the line for a search that runs now, or None
"""
import ctypes
import math
import sys

# Peak working set of one worker, measured in real searches (2026-11-03: Legends 934-977 MB with maps, 776 MB rosters only, PyPy
# 1408-1491 MB; Vanilla 342 MB with maps, 223 MB rosters only, PyPy 536 / 415 MB). Rounded up. A setup with other mods: as Legends.
GB_LEGENDS, GB_LEGENDS_PYPY = 1.0, 1.5
GB_VANILLA, GB_VANILLA_PYPY = 0.35, 0.55
USABLE_SHARE = 0.9          # of the free memory: Windows and the other programs need some of it too
LOW_SHARE = 0.05            # of all memory: a search that runs is told to stop below this ...
LOW_BYTES = 1 << 30         # ... or below this, whichever is more

MEMORY_LINE = "Workers: %d workers need approximately %s GB of memory, and %s GB is free now. Use %d workers or less."
MEMORY_ONE = "Workers: 1 worker needs approximately %s GB of memory, and %s GB is free now. Close other programs."
THREADS_LINE = "Workers: this computer has %d processor threads, and %d workers use all of them. The computer can become slow. Use %d workers or less."
LOW_LINE = "The memory of this computer is almost full: %s GB is free. The computer can stop working. Stop the search and use fewer workers."
DIALOG_TITLE = "Too many workers"


def memory():
    """(total bytes, available bytes) of the physical memory; None when they cannot be read (not on Windows, or the call fails):
    then there is no warning, and the search goes on as before."""
    if sys.platform != "win32":
        return None

    class Status(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    status = Status()
    status.dwLength = ctypes.sizeof(Status)
    try:
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
    except OSError:
        return None
    return status.ullTotalPhys, status.ullAvailPhys


def gb_per_worker(vanilla, pypy):
    if vanilla:
        return GB_VANILLA_PYPY if pypy else GB_VANILLA
    return GB_LEGENDS_PYPY if pypy else GB_LEGENDS


def _gb(value):
    """"17", "0.7": one decimal below 10 GB, none above."""
    return "%.1f" % value if value < 10 else "%.0f" % value


def most_workers(available, per_worker):
    """How many workers fit into USABLE_SHARE of the free memory; 0 when not even one does."""
    return math.floor(available * USABLE_SHARE / (per_worker * (1 << 30)))


def problems(workers, threads, per_worker, found_memory):
    """Lines for the player, memory first; [] when it fits. workers None or below 1: another check says so."""
    if workers is None or workers < 1:
        return []
    lines = []
    if found_memory is not None:
        available = found_memory[1]
        most = most_workers(available, per_worker)
        free = _gb(available / (1 << 30))
        if most < 1:
            lines.append(MEMORY_ONE % (_gb(per_worker), free))
        elif workers > most:
            lines.append(MEMORY_LINE % (workers, _gb(workers * per_worker), free, most))
    if threads > 1 and workers >= threads:
        lines.append(THREADS_LINE % (threads, workers, threads - 1))
    return lines


def memory_is_low(found_memory):
    """The line for a search that runs now, when the memory is almost full; else None."""
    if found_memory is None:
        return None
    total, available = found_memory
    if available < max(LOW_BYTES, total * LOW_SHARE):
        return LOW_LINE % _gb(available / (1 << 30))
    return None
