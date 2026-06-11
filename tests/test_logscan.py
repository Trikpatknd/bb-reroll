"""logscan.py — the GUI's log-line recognition. These patterns are the GUI's
only window into the mod, so they're pinned two ways: against literal sample
lines exactly as the .nut emits them, and against the .nut source itself so a
reworded log line can't silently drift away from the regex that must match it.
"""
import re
from pathlib import Path

from bbreroll.logscan import (
    INIT_RE, FINISH_RE, DEPCHECK_RE, UNEXPECTED_RE, MATCH_RE,
    strip_html, analyze_tail,
)

ROOT = Path(__file__).resolve().parent.parent
NUT = (ROOT / "mod" / "bb_reroll_dump.nut").read_text(encoding="utf-8")


def _html(line: str) -> str:
    """Wrap like a BB log.html row."""
    return f'<div class="text">{line}</div>'


# ── literal samples (what the .nut's log calls produce) ──

INIT_LINE   = "[BBREROLL] mod queued (v3.4.5)"
INIT_OLD    = "[BBREROLL] mod queued (v3.4.3)"   # seen in a real stale-deploy log
FINISH_M    = "[BBREROLL2] *** FINISH: match found at seed=ABCDEFGH12. Restart BB, then enter this seed for a real campaign. ***"
FINISH_N    = "[BBREROLL2] *** FINISH: no seed matched in 10000 iters. last_fail=bro1 msk*1<2. Restart BB. ***"
DEPCHECK_L  = ("[BBREROLL2] BB Reroll: missing required mod(s): Legends (mod_legends), MSU (mod_msu). "
               "BB Reroll needs Legends + MSU plus the hooks framework (mod_hooks / modern_hooks). "
               "Install them and restart Battle Brothers.")
UNEXPECTED_L = ("[BBREROLL2] UNEXPECTED exception in startNewCampaign "
                "(NOT a BB Reroll finish — passing it through): the index 'x' does not exist")


def test_init_re():
    assert INIT_RE.search(INIT_LINE).group(1) == "3.4.5"
    assert INIT_RE.search(INIT_OLD).group(1) == "3.4.3"


def test_finish_re_both_variants():
    assert FINISH_RE.search(FINISH_M).group(1).startswith("match found at seed=ABCDEFGH12")
    assert FINISH_RE.search(FINISH_N).group(1).startswith("no seed matched in 10000 iters")


def test_depcheck_re_captures_mod_list():
    assert DEPCHECK_RE.search(DEPCHECK_L).group(1) == "Legends (mod_legends), MSU (mod_msu)"


def test_unexpected_re_captures_detail():
    assert UNEXPECTED_RE.search(UNEXPECTED_L).group(1) == "the index 'x' does not exist"


def test_patterns_match_through_html():
    text = strip_html("\n".join(_html(l) for l in
                                [INIT_LINE, DEPCHECK_L, FINISH_M, UNEXPECTED_L]))
    assert INIT_RE.search(text) and DEPCHECK_RE.search(text)
    assert FINISH_RE.search(text) and UNEXPECTED_RE.search(text)


# ── anti-drift: the .nut still contains the emitting fragments ──

def test_nut_still_emits_these_lines():
    assert ' mod queued (v" + ::BBReroll.Version' in NUT
    assert " *** FINISH: match found at seed=" in NUT
    assert " *** FINISH: no seed matched in " in NUT
    assert "missing required mod(s): " in NUT
    assert "UNEXPECTED exception in startNewCampaign" in NUT


# ── analyze_tail (connect-late classification) ──

def test_analyze_tail_full_session():
    text = "\n".join(["engine noise", INIT_LINE, "more noise", FINISH_M])
    out = analyze_tail(text)
    assert out["mod_version"] == "3.4.5"
    assert out["finished"].startswith("match found")
    assert out["missing_deps"] is None


def test_analyze_tail_ignores_events_before_last_init():
    # A FINISH from an older session followed by a fresh launch's init line:
    # the stale FINISH must not trigger the unstable-state banner.
    text = "\n".join([FINISH_M, "…BB relaunched…", INIT_LINE])
    out = analyze_tail(text)
    assert out["mod_version"] == "3.4.5"
    assert out["finished"] is None


def test_analyze_tail_no_init_reports_events_anyway():
    out = analyze_tail("\n".join(["noise", DEPCHECK_L]))
    assert out["mod_version"] is None
    assert out["missing_deps"] == "Legends (mod_legends), MSU (mod_msu)"


def test_analyze_tail_unexpected_scoped_like_others():
    # Caught from current-session content…
    out = analyze_tail("\n".join([INIT_LINE, UNEXPECTED_L]))
    assert out["unexpected"] == "the index 'x' does not exist"
    # …but a stale one from before a fresh launch's init line is ignored.
    out = analyze_tail("\n".join([UNEXPECTED_L, INIT_LINE]))
    assert out["unexpected"] is None


def test_analyze_tail_init_far_from_tail():
    # Init at the head, megabytes of run output after — the real-log shape
    # that broke the original tail-window scan.
    text = "\n".join([INIT_OLD] + ["[BBREROLL2] iter %d/10000 last_fail=x skipped=0" % i
                                   for i in range(0, 5000, 10)])
    out = analyze_tail(text)
    assert out["mod_version"] == "3.4.3"


def test_match_re_still_matches_verified_form():
    line = "[BBREROLL2] *** MATCH at iter 51 seed=ABCDEFGH12 (verified) ***"
    m = MATCH_RE.search(line)
    assert m and m.group(1) == "51" and m.group(2) == "ABCDEFGH12"
