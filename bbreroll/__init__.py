"""BB Reroll helper package.

gui.py (the entry point) stays at the repo root; the tkinter-free, unit-tested
pieces of the GUI live here: the criteria model and default trait lists
(criteria), the game setups and origins the search offers (offline_origins), the
per-origin hardcoded-stars catalog (origin_hardcoded_stars), the trait
display-name map (trait_names) and the Discord seed post (seed_report).

The search itself — the game's campaign-start scripts run without the game — is
the separate top-level package bbseed/.
"""
