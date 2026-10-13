"""The offline seed search: Battle Brothers' own campaign-start scripts, run without the game.

  rng.py       the game's seeded random generator (64-bit Mersenne Twister, sdbm string hash)
  sq/          a Squirrel 3.0.4 interpreter: source text (the mods) and compiled scripts
               (the base game's .cnut) run on one runtime
  engine.py,   a stand-in for the engine's native side — just enough to load the scripts
  world.py     and start a campaign's roster
  gamedata.py  finds the installed game and reads its script archives
  profiles.py  which script roots make up a setup (vanilla / legends / modded)
  lab.py       Lab(profile).roster(seed, origin) -> the starting brothers
  search.py    the parallel search (also `python -m bbseed.search`)

Nothing here ships game or mod files: they are read from the player's own install.
"""
