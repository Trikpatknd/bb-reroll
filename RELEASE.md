# Release checklist

The repo-root `VERSION` file is the single source of truth. Everything else
(the `.nut`'s `Version`, `mod_template.py`'s `NUT_VERSION`, the deploy zip's
`BBRR_MANIFEST.json`, the GUI title) derives from it.

## 1. Land + test on `testing`
- All work merged onto `testing`.
- `pip install -r requirements-dev.txt` then `python -m pytest` — all green.

## 2. Version bump (if releasing a new version)
- Edit `VERSION` (e.g. `3.4.5` → `3.4.6`).
- `python tools/embed_nut.py` and `python tools/build_zip.py` restamp the
  `.nut`, regenerate `mod_template.py`, and rebuild the zip.
- Commit the restamped `mod/bb_reroll_dump.nut` (the template + zip are
  gitignored).

## 3. Version consistency
Confirm all four agree (test_build.py covers this automatically):
`VERSION` == `.nut` `Version` == `mod_template.NUT_VERSION` ==
`mod/mod_bb_reroll_dump.zip` → `BBRR_MANIFEST.json` `version`.

## 4. Smoke tests (manual — require the game, can't be automated)
Deploy from testing: `python tools/deploy.py` (refuses on `main`; restart BB).
- **Loaded + version**: launch BB → `log.html` has `[BBREROLL] mod queued (vX)`;
  GUI title shows the same `vX` with no mismatch banner.
- **Finish flow**: REROLL run with trivial criteria → `*** FINISH: match … ***`
  in the log → GUI finish banner. BB shows a crash dialog OR returns to the
  menu — either is expected; restart BB.
- **Injected-exception (Phase 2)**: temporarily add `throw "x";` at the top of
  `BBReroll_BF_Run`, redeploy, run REROLL. Confirm `log.html` shows
  `[BBREROLL2] UNEXPECTED exception … passing it through` and the throw is NOT
  swallowed. Remove the injection and redeploy.
- **Dependency check (Phase 5)**: temporarily remove Legends from the data
  folder, launch BB. Confirm the `[BBREROLL2] … missing required mod(s)` log +
  in-game popup, and the GUI "mod doesn't appear to be loaded" banner. Restore
  Legends.
- **Unsatisfiability (Phase 4)**: pick Gladiators, set `* msk:2`, Save & Deploy
  → confirm the "Unsatisfiable criteria" dialog (bro 2 has no melee skill).

## 5. Merge to `main` (gated — confirm with maintainer)
`git checkout main && git merge testing`.

## 6. Tag + push (gated)
`git tag vX.Y.Z` on `main`; `git push --follow-tags origin main`.

## 7. Publish
- GitHub release for the tag; attach `mod/mod_bb_reroll_dump.zip` built from
  the tagged commit (`python tools/build_zip.py`).
- Update the Nexus page from `NEXUS_PAGE.md` (the source text; gitignored).
