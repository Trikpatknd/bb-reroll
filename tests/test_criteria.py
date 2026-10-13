"""bbreroll/criteria.py — the criteria the GUI hands to the search, and the pre-search checks."""
from bbreroll import criteria as C
from bbseed.search import first_failure, normalize


def test_default_criteria_are_fresh_copies_of_the_default_lists():
    a, b = C.default_criteria(), C.default_criteria()
    assert a == b and a["banned"] is not b["banned"]
    assert a["banned"] == C.DEFAULT_BANNED and a["required"] == C.DEFAULT_REQUIRED
    assert a["stars_by_slot"] == {"*": {}} and a["required_mode"] == "any"
    assert not set(C.DEFAULT_BANNED) & set(C.DEFAULT_REQUIRED)


def test_trivial_criteria_match_everything():
    assert C.is_trivial({"stars_by_slot": {"*": {}}, "banned": [], "required": []})
    assert not C.is_trivial({"stars_by_slot": {"*": {}, "2": {"msk": 1}}, "banned": [], "required": []})
    assert not C.is_trivial({"stars_by_slot": {"*": {}}, "banned": ["dumb"], "required": []})
    assert not C.is_trivial(C.default_criteria())


def test_the_search_accepts_the_gui_criteria_as_they_are():
    gui = {"stars_by_slot": {"*": {"hp": 1}, "2": {"msk": 2}}, "banned": ["dumb"], "required": ["brave", "tough"],
           "required_mode": "any"}
    crit = normalize(gui)
    zero = dict.fromkeys(C.STATS, 0)
    # a numeric slot row replaces the "*" row for that brother: bro 2 needs msk2, and no hp star
    good = [{"stars": dict(zero, hp=1), "traits": ["brave"]}, {"stars": dict(zero, msk=2), "traits": ["tough"]}]
    assert first_failure(good, crit) is None
    assert first_failure([good[0], {"stars": dict(zero, hp=3, msk=1), "traits": ["tough"]}], crit) == "bro2 msk*1<2"
    assert first_failure([{"stars": dict(zero, hp=1), "traits": ["brave", "dumb"]}, good[1]], crit) is not None


def test_number_checks():
    ok = {"Max seeds": 100000, "Stop after matches": 3, "Workers": 4}
    assert C.number_errors(ok, cpu_threads=8) == []
    assert C.number_errors(dict(ok, Workers=9), cpu_threads=8) == ["Workers: this PC has 8 CPU threads."]
    errors = C.number_errors({"Max seeds": None, "Stop after matches": 0, "Workers": 4}, cpu_threads=8)
    assert len(errors) == 2 and all("at least 1" in e for e in errors)
    assert C.to_int(" 42 ") == 42 and C.to_int("4.5") is None and C.to_int("") is None


def test_trait_names_typed_by_the_player():
    assert C.sanitize_trait("Iron Lungs") == "iron_lungs"
    assert C.sanitize_trait("  legend-Heavy! ") == "legend_heavy"
    assert C.sanitize_trait("???") == ""
    assert C.id_to_display("legend_steady_hands") == "Steady Hands"
    assert C.id_to_display("iron_jaw") == "Iron Jaw"


def test_roster_lines():
    bro = {"name": "Musa the Merchant", "background_name": "Background: Merchant",
           "stars": dict(dict.fromkeys(C.STATS, 0), res=3, msk=1), "trait_names": ["Bleeder", "Spartan"]}
    plain = dict(bro, name="Eduard", background_name="Caravan Hand", stars=dict.fromkeys(C.STATS, 0), trait_names=[])
    assert C.roster_lines([bro, plain]) == [
        " 1. Musa the Merchant (Merchant)  [res3 msk1]  Bleeder, Spartan",
        " 2. Eduard (Caravan Hand)  [no stars]  no traits",
    ]
