"""Per-origin hardcoded talent stars, sourced from Legends 19.3.24.

For each origin keyed by its GUI display name (matching ORIGINS in gui.py),
the value is a list of per-slot dicts in 1-based order. Each dict maps stat
short-name (matching STATS in gui.py) to the hardcoded talent-star count the
scenario writes via `bros[i].getTalents()[Const.Attributes.X] = N` after
calling `getTalents().resize(COUNT, 0)`. Empty dict {} = that slot's stars
are rolled by `fillTalentValues` and the scenario doesn't override them.

For the brute-forcer, hardcoded stars are invariant across seeds — setting
a non-matching requirement on a hardcoded slot will reject every iteration.
"""

ORIGIN_HARDCODED_STARS: dict[str, list[dict[str, int]]] = {
    "Custom":                    [],  # not a scenario
    # Vanilla origins (Legends-hooked)
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
    "Trading Caravan":           [{}, {"msk":2,"mdf":1,"hp":1}],
    # Legends-added origins (4 dropped: Build your own, Druid [Legacy],
    # Horse Party, Mage — all hard-disabled in the BB picker via `isValid()
    # { return false; }`)
    "Adventuring Party":         [{}, {}, {}, {}, {}, {}],
    "Assassin":                  [{}],
    "Berserker":                 [{}],
    "Crusader":                  [{}],
    "Escaped Slaves":            [{"res":3,"msk":1,"rdf":3}, {}, {"init":2,"res":2,"rsk":2}, {}, {}],  # requires Blazing Deserts DLC
    "The Free Company":          [{}, {}, {}, {}, {}],
    "The Inquisition":           [{"res":3,"hp":3,"msk":2}, {"res":3,"rsk":3}, {"res":3,"msk":2,"mdf":3}],
    "Master Necromancer":        [{}, {}, {}, {}, {}, {}],
    "Noble":                     [{}, {}, {}, {}, {}, {}],
    "Nomad Tribe":               [{}, {}, {}, {}, {}],
    "Original Beggar Challenge": [{}],
    "Ranger":                    [{}, {"msk":2,"hp":2}],
    "Scaling Beggar Challenge":  [{}],
    "Seer":                      [{}],
    "Sisterhood":                [{}, {}, {}, {}, {}, {}],
    "The Cabal":                 [{}, {}, {}, {}],
    "The Troupe":                [{}, {}, {}, {}],
}


def summarize(origin: str) -> str:
    slots = ORIGIN_HARDCODED_STARS.get(origin)
    if slots is None:
        return f'"{origin}" — no data available; assume fully rolled.'
    if not slots:
        return f'"{origin}" — no fixed roster; consult the scenario directly.'
    hardcoded = [(i + 1, d) for i, d in enumerate(slots) if d]
    rolled = [i + 1 for i, d in enumerate(slots) if not d]
    if not hardcoded:
        return f"All {len(slots)} slots fully rolled — every stat can be brute-forced."
    lines = ["Hardcoded stars (locked, cannot be brute-forced):"]
    for slot_num, stars in hardcoded:
        token = "  ".join(f"{k}:{v}" for k, v in stars.items())
        lines.append(f"  Slot {slot_num}: {token}")
    if rolled:
        joined = ", ".join(str(s) for s in rolled)
        label = "Slots" if len(rolled) > 1 else "Slot"
        lines.append(f"{label} {joined}: fully rolled.")
    return "\n".join(lines)


def conflicts(origin: str, stars_by_slot: dict) -> list:
    """Return user criteria that the origin's hardcoded stars make impossible.

    `stars_by_slot` is the shape the GUI/.nut use:
        {"*": {stat: min, ...}, "1": {stat: min, ...}, ...}
    A numeric slot key overrides "*" entirely for that slot (it is NOT merged),
    matching BBReroll_BF_StarsFor in the .nut.

    A slot with a non-empty hardcoded dict is fully determined: the scenario
    zeroes all talents (resize(COUNT, 0)) before assigning the listed stats, so
    listed stats take their value and every other stat is 0. A required minimum
    above the fixed value on such a slot can therefore never be met by any seed.

    Returns a list of (slot_number, stat, needed, have) tuples; empty = no
    provable conflict. Rolled slots (empty dict) are skipped — any stat is
    reachable there.
    """
    slots = ORIGIN_HARDCODED_STARS.get(origin) or []
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
            have = hardcoded.get(stat, 0)
            if need > have:
                out.append((idx, stat, need, have))
    return out
