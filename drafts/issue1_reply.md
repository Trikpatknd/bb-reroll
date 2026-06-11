<!--
DRAFT reply for https://github.com/Trikpatknd/bb-reroll/issues/1 ("An error occurred." — user Temlpe)
Do NOT post automatically. Review, then paste into the issue.

Context recap:
- Screenshot = the world_state.onRender:899 crash.
- Temlpe: typed REROLL, crash on starting the game, Steam version, "no logs",
  and the BB Reroll GUI "showed no response".
- "GUI showed nothing" + "no logs" strongly implies our mod never initialised
  → most likely a missing dependency (Legends / MSU / hooks). v3.4.5 adds an
  in-mod dependency self-check and a GUI "mod not loaded" banner for exactly
  this case, but Temlpe is on v3.4.4.
-->

Thanks for the details — the "GUI showed no response" part is the key clue.

When the mod loads correctly, the very first thing it writes to `log.html`
(before BB even reaches the title screen) is:

```
[BBREROLL] mod queued (v3.4.4)
```

and the GUI tails that file live, so it would light up the moment you launch
BB. If the GUI showed nothing **and** `log.html` has no `[BBREROLL]` lines, the
mod never initialised — which almost always means a missing dependency.

**1. Please list every `.zip` in your `Battle Brothers\data\` folder.** BB
Reroll needs all of these installed and enabled:

- `mod_legends-19.3.24.zip` (or later — the **scripts** pack, NOT
  `mod_legends-assets-…zip`, which is only sprites/audio)
- `mod_msu-….zip` (MSU)
- `mod_hooks….zip` **and** `mod_modern_hooks….zip` (the hooks framework)
- `mod_bb_reroll_dump.zip` (this mod)

If any of those are missing, the mod's startup hook never runs.

**2. Please open `log.html` and check for `[BBREROLL]`.** The real path is
(replace the username with your Windows account name — it isn't literally
"USERNAME"):

```
C:\Users\<your Windows username>\Documents\Battle Brothers\log.html
```

Open it in a browser or Notepad and search for `BBREROLL`. If there's nothing,
the mod didn't load (points to a missing dependency above). If there are
`[BBREROLL]` lines, copy the section around the error and paste it here.

**3. Was the BB Reroll GUI window open *while* BB was running?** It has to be
open to tail the log and show progress/matches. If you only opened it to click
Save & Deploy and then closed it, you wouldn't see any feedback.

One more note: the `world_state.onRender:899` crash in your screenshot isn't
unique to this mod — Battle Brothers can hit it whenever its world state is
left half-initialised, including for unrelated reasons. So even after fixing
the dependency issue you might occasionally see that dialog; the important
question right now is whether BB Reroll loaded at all, which the `log.html`
contents (or absence) will tell us.

(For what it's worth: the next release adds an explicit "missing dependency"
message in-game and a "the mod doesn't appear to be loaded" warning in the GUI,
so this is easier to diagnose going forward.)
