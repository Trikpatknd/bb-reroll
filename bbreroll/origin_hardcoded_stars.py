"""Per-origin hardcoded talent stars, sourced from Legends 19.3.24, re-checked against 19.4.22
and corrected on 2026-10-15 from what the game's own scripts give (bbseed/catalog.py: 12 origins
had fixed stars missing). The GUI uses the catalog of the installed game when it has one; this
table is only the fallback until that catalog is built.

For each origin keyed by its GUI display name (matching ORIGINS in offline_origins.py),
the value is a list of per-slot dicts in 1-based order. Each dict maps stat
short-name (matching STATS in criteria.py) to the hardcoded talent-star count the
scenario writes via `bros[i].getTalents()[Const.Attributes.X] = N` after
calling `getTalents().resize(COUNT, 0)`. Empty dict {} = that slot's stars
are rolled by `fillTalentValues` and the scenario doesn't override them.

For the brute-forcer, hardcoded stars are invariant across seeds — setting
a non-matching requirement on a hardcoded slot will reject every iteration.

Some slots have fixed stars AND a talent roll on top (ROLLED_ON_TOP, e.g. Berserker: HP 3 and
MSK 3, then two more stats rolled): there only the listed stats are known; the others can still
get stars.
"""

ORIGIN_HARDCODED_STARS: dict[str, list[dict[str, int]]] = {
    # Vanilla origins (Legends-hooked)
    "A New Company":             [{"hp":2,"fat":1,"res":1}, {"res":1,"msk":2,"mdf":1}, {"init":1,"rsk":2,"rdf":1}],
    "Anatomist":                 [{"res":1,"msk":2,"rsk":2}, {"hp":2,"init":3,"msk":1}, {"res":2,"mdf":3,"rdf":3}],
    "Band of Poachers":          [{"rsk":2,"rdf":1,"init":1}, {"rsk":2,"fat":1,"init":1}, {"rsk":2,"res":1,"init":1}],
    "Beast Slayers":             [{"msk":2,"mdf":2,"init":2}, {"fat":2,"msk":1,"mdf":1}, {"rsk":2,"rdf":1,"fat":1}],
    "Davkul Cultists":           [{}, {}, {}, {}, {}],
    "Deserters":                 [{}, {}, {}],
    "Gladiators":                [{"msk":3,"mdf":2,"fat":2}, {"hp":3,"fat":2,"res":2}, {"msk":2,"mdf":2,"init":3}],
    "Lone Wolf":                 [{"msk":3,"mdf":2,"fat":3,"rsk":2}],
    "Manhunters":                [{"msk":1,"res":2,"rdf":1}, {"fat":2,"msk":1,"hp":1}, {}, {}, {}, {}],
    "Northern Raiders":          [{"msk":2,"hp":2,"fat":1}, {"msk":2,"hp":1,"fat":2}, {"msk":1,"mdf":2,"hp":2}, {"res":3}],
    "Oathtakers":                [{"res":3,"msk":1,"rdf":2}, {"init":3,"msk":2,"mdf":1}],
    "Peasant Militia":           [{}] * 12,
    "Southern Mercenaries":      [{"hp":2,"fat":1,"res":1}, {"res":1,"msk":2,"mdf":1}, {"init":1,"rsk":2,"rdf":1}],  # requires Blazing Deserts DLC
    "Trading Caravan":           [{}, {"msk":2,"mdf":1,"hp":1}],
    # Legends-added origins (4 dropped: Build your own, Druid [Legacy],
    # Horse Party, Mage — all hard-disabled in the BB picker via `isValid()
    # { return false; }`)
    "Adventuring Party":         [{"hp":3}, {"init":2,"msk":2}, {"msk":3,"mdf":3}, {"fat":2}, {"res":3,"msk":3}, {"fat":2,"rsk":3}],
    "Assassin":                  [{"init":3,"msk":2,"rsk":1}],
    "Berserker":                 [{"hp":3,"msk":3}],
    "Crusader":                  [{"msk":3,"mdf":3}],
    "Escaped Slaves":            [{"res":3,"msk":1,"rdf":3}, {}, {"init":2,"res":2,"rsk":2}, {}, {}],  # requires Blazing Deserts DLC
    "The Free Company":          [{}, {}, {}, {}, {}],
    "The Inquisition":           [{"res":3,"hp":3,"msk":2}, {"res":3,"rsk":3}, {"res":3,"msk":2,"mdf":3}],
    "Master Necromancer":        [{"hp":3}, {}, {}, {}, {}, {}],
    "Noble":                     [{"res":3,"msk":3}, {}, {}, {}, {}, {}],
    "Nomad Tribe":               [{}, {}, {}, {}, {}],
    "Original Beggar Challenge": [{}],
    "Random Party":              [],  # 4-6 bros rolled per seed — no fixed roster
    "Random Solo":               [{}],
    "Random Trio":               [{}, {}, {}],
    "Ranger":                    [{"fat":3,"rsk":3}, {"msk":2,"hp":2,"fat":2}],
    "Risen Legion":              [{}] * 8,
    "Scaling Beggar Challenge":  [{}],
    "Seer":                      [{"fat":3,"init":3}],
    "Sisterhood":                [{}, {}, {}, {}, {}, {}],
    "The Cabal":                 [{"res":1,"init":1}, {"mdf":2,"rdf":1}, {"msk":1,"rsk":2}, {}],
    "The Troupe":                [{"rdf":3}, {}, {}, {}],
}

# Slots (1-based) with fixed stars plus a talent roll on top (Legends 19.4.22).
ROLLED_ON_TOP: dict[str, set[int]] = {
    "Adventuring Party": {1, 2, 3, 4, 5, 6}, "Assassin": {1}, "Berserker": {1}, "Crusader": {1},
    "The Inquisition": {2}, "Master Necromancer": {1}, "Noble": {1}, "Ranger": {1, 2}, "Seer": {1},
    "The Cabal": {1, 2, 3}, "The Troupe": {1},
}


def summarize(origin: str) -> str:
    slots = ORIGIN_HARDCODED_STARS.get(origin)
    if slots is None:
        return f"There is no data for {origin}."
    if not slots:
        return f"The brothers of {origin} change with the seed."
    hardcoded = [(i + 1, d) for i, d in enumerate(slots) if d]
    rolled = [i + 1 for i, d in enumerate(slots) if not d]
    if not hardcoded:
        return f"All {len(slots)} brothers get random stars."
    lines = ["Fixed stars (the seed cannot change them):"]
    on_top = ROLLED_ON_TOP.get(origin, set())
    for slot_num, stars in hardcoded:
        token = ", ".join(f"{k.upper()} {v}" for k, v in stars.items())
        lines.append(f"  Brother {slot_num}: {token}" + (", and random stars" if slot_num in on_top else ""))
    if rolled:
        joined = ", ".join(str(s) for s in rolled)
        label = "Brothers" if len(rolled) > 1 else "Brother"
        lines.append(f"{label} {joined}: random stars.")
    return "\n".join(lines)


def conflicts(origin: str, stars_by_slot: dict) -> list:
    """Return user criteria that the origin's hardcoded stars make impossible.

    `stars_by_slot` is the shape the GUI/.nut use:
        {"*": {stat: min, ...}, "1": {stat: min, ...}, ...}
    A numeric slot key overrides "*" entirely for that slot (it is NOT merged),
    matching BBReroll_BF_StarsFor in the .nut.

    A slot with a non-empty hardcoded dict is fully determined: listed stats take
    their value and every other stat is 0 — unless the slot also rolls talents on
    top (ROLLED_ON_TOP): then only the listed stats are known (the roll skips stats
    that already have stars, so they cannot go higher). A required minimum above
    the fixed value can therefore never be met by any seed.

    Returns a list of (slot_number, stat, needed, have) tuples; empty = no
    provable conflict. Rolled slots (empty dict) are skipped — any stat is
    reachable there.
    """
    slots = ORIGIN_HARDCODED_STARS.get(origin) or []
    on_top = ROLLED_ON_TOP.get(origin, set())
    out = []
    for idx, hardcoded in enumerate(slots, start=1):
        if not hardcoded:
            continue  # rolled slot — anything is possible
        crit = stars_by_slot.get(str(idx))
        if crit is None:
            crit = stars_by_slot.get("*", {})
        for stat, need in crit.items():
            try:
                need = int(need)
            except (TypeError, ValueError):
                continue
            if idx in on_top and stat not in hardcoded:
                continue  # the roll on top may star it
            have = hardcoded.get(stat, 0)
            if need > have:
                out.append((idx, stat, need, have))
    return out
