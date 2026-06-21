"""Log-line recognition for BB's log.html — shared by the GUI's live watcher
and its connect-time tail scan, and unit-testable without tkinter.

Every pattern here must match a line the .nut actually emits (see
mod/bb_reroll_dump.nut); tests in tests/test_logscan.py pin them against the
exact emitted strings so the two can't silently drift apart.
"""
import re

# ── live-watch patterns ──
MATCH_RE    = re.compile(r"\[BBREROLL2\]\s+\*\*\*\s+MATCH\s+at\s+iter\s+(\d+)\s+seed=(\S+?)(?:\s+\(verified\))?\s+\*\*\*")
PROGRESS_RE = re.compile(r"\[BBREROLL2\]\s+iter\s+(\d+)/(\d+)")
START_RE    = re.compile(r"\[BBREROLL2\]\s+brute force start")
# Mod logs this when a candidate triggers the authoritative world rebuild.
# v3.4.6+ wording is "candidate ... — confirming"; older builds said
# "stars-pass ... — verifying". Match both so the verify LED works either way.
VERIFY_RE   = re.compile(r"\[BBREROLL2\]\s+iter\s+(\d+)\s+(?:candidate|stars-pass)\s+seed=(\S+)")
# Init line, written once at BB launch (after Legends loads). Doubles as the
# "mod is loaded" signal and the source of the installed mod version.
INIT_RE     = re.compile(r"\[BBREROLL\]\s+mod queued \(v([0-9][0-9A-Za-z.\-]*)\)")
# Clean-finish marker emitted just before the loop throws its sentinel.
FINISH_RE   = re.compile(r"\[BBREROLL2\]\s+\*\*\*\s+FINISH:\s+(.+?)\s+\*\*\*")
# Dependency self-check failure (Phase 5). Captures the missing-mod list.
DEPCHECK_RE = re.compile(r"\[BBREROLL2\]\s+BB Reroll: missing required mod\(s\): (.+?)\. BB Reroll needs")
# Non-sentinel exception passed through by the startNewCampaign catch (Phase 2).
UNEXPECTED_RE = re.compile(r"\[BBREROLL2\]\s+UNEXPECTED exception in startNewCampaign[^:]*:\s*(\S.*)")

# Seed-report inputs, both logged once at brute-force start. The Map Options
# line is space-separated key=value (numbers / true|false, no spaces). The
# Seed Report Info line is " | "-separated because buildName ("Left & Right")
# and battleSisters ("Enabled (Cosmetic)") contain spaces/parens.
MAPOPTS_RE    = re.compile(r"\[BBREROLL2\]\s+Map Options:\s*(.+)")
REPORTINFO_RE = re.compile(r"\[BBREROLL2\]\s+Seed Report Info:\s*(.+)")

_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(s: str) -> str:
    # Replace tags with a newline, NOT "". log.html is one giant HTML line with
    # entries separated only by tags; collapsing them onto one line let a greedy
    # capture (e.g. REPORTINFO_RE's (.+)) swallow following entries into the last
    # field. Inserting newlines keeps each log entry on its own line.
    return _TAG_RE.sub("\n", s)


def analyze_tail(text: str) -> dict:
    """Classify already-written log content (GUI connected late, BB launched
    first, or the GUI was reopened after a run).

    BB truncates log.html on every launch, so the tail is normally the current
    session. If an init line exists, only events AFTER the last init count —
    anything before it belongs to an older session that survived in the same
    file. Without an init line, the whole text is considered.

    Returns {mod_version, finished, missing_deps, unexpected, report_info}
    (scalar fields None when absent; report_info is always a dict).
    """
    inits = list(INIT_RE.finditer(text))
    version = inits[-1].group(1) if inits else None
    scope = text[inits[-1].end():] if inits else text

    finishes = list(FINISH_RE.finditer(scope))
    depchecks = list(DEPCHECK_RE.finditer(scope))
    unexpecteds = list(UNEXPECTED_RE.finditer(scope))
    return {
        "mod_version": version,
        "finished": finishes[-1].group(1) if finishes else None,
        "missing_deps": depchecks[-1].group(1) if depchecks else None,
        "unexpected": unexpecteds[-1].group(1) if unexpecteds else None,
        "report_info": parse_report_info(scope),
    }


def parse_report_info(text: str) -> dict:
    """Extract everything the Discord seed report needs from the log.

    Reads the LATEST `Map Options:` line (7 world settings) and the latest
    `Seed Report Info:` line (Legends version + build name + Battle sisters).
    Returns a fixed-shape dict; fields are None / {} when their line is absent,
    so callers can render "(unknown)" without special-casing.
    """
    info = {"version": None, "build_name": None, "battle_sisters": None,
            "origin": None, "map_options": {}}

    mo = list(MAPOPTS_RE.finditer(text))
    if mo:
        for tok in mo[-1].group(1).split():
            if "=" in tok:
                k, v = tok.split("=", 1)
                info["map_options"][k] = v

    ri = list(REPORTINFO_RE.finditer(text))
    if ri:
        for field in ri[-1].group(1).split(" | "):
            if "=" not in field:
                continue
            k, v = field.split("=", 1)
            k, v = k.strip(), v.strip()
            if k == "legendsVersion":
                info["version"] = v
            elif k == "buildName":
                info["build_name"] = v
            elif k == "battleSisters":
                info["battle_sisters"] = v
            elif k == "origin":
                info["origin"] = v
    return info
