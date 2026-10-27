# Master Smith cloud A/B test (2026-10-21): the Proteus Mk II through the pipeline, on a cloud box

You are the director of ONE of two independent runs of the same ship. Your prompt says which:
- **Test A, "as is"**: the models we have been using. The Hi3D v3 multi-view seed is already made and waits in the
  data repo (`cloud-data/out/ProteusShipMkII_Hi3D`, $2.10 paid on 2026-10-08). You spend nothing on a seed.
- **Test B, "new models"**: fal's September 2026 seed models, never tried: `tripo-p2` ($1.20), `meshy71` ($1.20),
  `meshy71-mv` ($1.20), and the Meshy v7 retexture (`ms retexture`, $0.30; `--resolution 8k` $0.45).

Both runs put the seed through the same Master Smith passes (zones, glass, sharpen, bevel, bake), score with the
same rubric, and leave their results in the PRIVATE data repo. The owner reads both and decides. The two earlier
attempts at this ship, for your anchors: a code-only procedural build (16 cloud rounds, 2026-10-09) plateaued at a
median 6.25, and a hand-built Blender job around the Hi3D seed (2026-10-08, pipeline bypassed) self-scored 8 but
reads as a 6: right hull, a flat plate fin, pods hanging off slabs, a wire canopy frame. The pipeline itself has
never been run on it.

## Two repositories

- **This one, `kevinpbuckley/Master-Smith` (PUBLIC)**: the code, this brief, the scripts under `cloud/`. Nothing of
  the owner's design goes here: no pictures, no seeds, no renders, no job folders. Your branch `cloud-test-<A|B>`
  carries only code fixes (see "Set up").
- **`kevinpbuckley/proteus-mkii-cloud` (PRIVATE)**: the data. `cloud-data/out/<job>` are the Master Smith jobs
  (`MASTERSMITH_DATA=cloud-data`), `cloud-data/rig_contract.json` the sockets a later rig step needs (out of scope
  here; the mount positions tell you where the three weapon plates go), `cloud-data/results/<A|B>/` is where every
  round of yours is committed. `ref/`, `contract/` and `output/` there belong to the earlier code-only runs; read
  `output/DECISIONS.md` for the settled reference conflicts (the sheet's views disagree; side and top views decide
  the silhouette, front and rear only the cross-section, the iso view the feel, the bottom view where the pods sit).

## Read first, in this order

1. `AGENTS.md` (the whole file: the owner's rules, the plan JSON, every `ms` command, materials, glass).
2. `.claude/skills/forge/SKILL.md` (the build recipe) and `mastersmith/skills/aircraft.md` (what a good aircraft is).
3. `cloud/review_rubric.md` (how you are scored).

## Set up

```
git checkout cloud-test && git checkout -b cloud-test-A        # or -B; in Master-Smith
bash cloud/setup.sh      # Blender 5.2.2, the venv, the data repo beside this one, cloud/env.sh
source cloud/env.sh      # in EVERY shell: $MS, $JOBS, $RESULTS, $DATA_REPO, BLENDER_BIN, MASTERSMITH_DATA
cd $DATA_REPO && git checkout -b cloud-test-A && cd -           # your results branch in the data repo
$MS status $JOBS/ProteusShipMkII_Hi3D
```
- `FAL_KEY` comes from the environment. NEVER print, echo or grep it, and never put it in a commit or a message.
- Always give `ms` the ABSOLUTE job path (`$JOBS/<Name>`): a relative `out/<Name>` resolves against this repo and
  does not exist here. `ms clone <src> <Name>` writes the new job into `$JOBS` by itself.
- No Unreal, no local models, no browser: `--no-open` on anything that opens a page; skip `ms preview`'s site,
  `ms rig` and the engine check (they run on the owner's PC afterwards).
- **If Blender will not start** (missing libraries and no apt): `.venv/bin/pip install bpy==5.2.2` (needs Python
  3.13; `uv venv --python 3.13` if the box has another), `chmod +x cloud/blender`, `export BLENDER_BIN=$PWD/cloud/blender`
  (the shim in `cloud/blender_shim.py` runs the scripts under the wheel). Say so in RESULT.md.
- A Linux-only break in `mastersmith/` (a path, an encoding) is fixed in its own commit titled `linux: ...` on
  `cloud-test-<A|B>` of Master-Smith so the owner can cherry-pick it; nothing else in `mastersmith/` changes.

## The run

**Test A**
1. `$MS clone $JOBS/ProteusShipMkII_Hi3D ProteusShipMkII_A --keep-seed` (free). Read `parts/Body/seed_render.png`
   against `ref/ref_0.png` and the six panels; state the seed's disposition (rule 10).
2. `$MS segment $JOBS/ProteusShipMkII_A` ($0.45). Read `segments.png`; name the labels.
3. Write the plan (AGENTS.md "The plan JSON"): one Body part, keep_texture; zones by segment: the canopy as a glass
   zone with `"shell": true` (and `"line": false` if you add an interior), the dome a metal zone, brass trim where the
   seed shows it, the three weapon mounts. If the seed's pods or fin are soft (rule 4: gooey is the seed), replace
   them: `sdf` parts with `"carve": true` and `"skin": true`, the pods tucked into the belly where the sheet's bottom
   view puts them, each pod a cream/oxblood banded duct with an open intake and a fan. `$MS plan`; fix every IGNORED.
4. `$MS fit` if registration's IoU (0.72 now) can be raised against the side and top silhouettes; keep it only if
   the outline improves without crumpling.
5. `$MS assemble $JOBS/ProteusShipMkII_A --draft` to nudge boxes (about a minute), then the full
   `$MS assemble ... --origin bottom` (5-15 min; run it in the background and keep working).
6. Review (below). Then the next round from the reviewers' `top_changes`. At most **8 full assembles**.
   Two rounds that gain under 0.3 mean the approach is wrong: change the construction of the weakest part, do not
   re-ask for the same fix.

**Test B**
1. `$MS clone $JOBS/ProteusShipMkII_Hi3D ProteusShipMkII_B --reseed Body` (free; the pictures and plan come along).
2. Seed it three ways, each in its own clone so the seeds can be compared: `ProteusShipMkII_B` with
   `--model tripo-p2` (from the hero, `--view hero`), `ProteusShipMkII_B2` with `--model meshy71`, `ProteusShipMkII_B3`
   with `--model meshy71-mv` ($3.60 in all; say the estimate first, as the tools do). Read each `seed_render.png`
   against the panels and each `registration.json` IoU; put all three on one sheet in `$RESULTS/B/seeds.png`.
3. Pick the best seed by what you SEE (silhouette against the panels, the canopy and pods present, paint right) and
   say why in RESULT.md. If its texture is soft or wrong, `$MS retexture` it once ($0.30) and compare before and
   after; keep whichever reads better.
4. Then steps 2-6 of Test A on that job.

**Both**: fal cap **$3 for A, $8 for B**; `ms status` prints the spend. Never spend on a step not listed here.

## Review (every full assemble)

1. Read `delivery/preview_views.png` and every `delivery/preview_*.png` yourself (rule 1) and write two lines on
   what is wrong before anyone else scores it.
2. `.venv/bin/python cloud/compare.py $JOBS/<job> $RESULTS/<A|B>/rounds/NN` writes `compare_<view>.png` and
   `contact.png`.
3. Three fresh reviewers in parallel (Agent tool, `model: "opus"`), each given ONLY `cloud/review_rubric.md`, that
   round's `compare_*.png`, `contact.png`, `delivery/report.json` and the `ms package` output; each writes
   `review_r1.json` / `review_r2.json` / `review_r3.json` in the round folder. Not your history, not your opinion.
4. `.venv/bin/python cloud/median_review.py $RESULTS/<A|B>/rounds/NN` -> `review.json`. The median is the score.
   Stop when it is **8.0 or more with every gate passing**, or at the assemble budget.
5. Write `delivery/scorecard.json` (`{"score", "owner_score": null, "scorer": "median of 3 reviewers", "spent",
   "defects": [...]}`) so `ms status` and `ms results` show it.

## Commit after every round (in the DATA repo)

```
cd $DATA_REPO && git add cloud-data/results/<A|B> && git commit -m "cloud-test <A|B> round NN: median X.XX" \
  && git push -u origin cloud-test-<A|B> && cd -
```
`cloud-data/results/<A|B>/rounds/NN/` holds `compare_*.png`, `contact.png`, `preview_views.png`, `review_r*.json`,
`review.json`, `plan.json` and `report.json` of that round. The final commit adds `cloud-data/results/<A|B>/RESULT.md`
(score per criterion, gates, triangle count, spend, the seed chosen and why, known shortcomings, what each round
changed) and the best round's `delivery/SM_ProteusShipMkII_*.glb` plus its `T_*.png` maps and `scorecard.json`
(leave out any file over 95 MB and say so). Do not commit the `cloud-data/out/*_A` or `*_B` job folders wholesale.
A run that dies mid-way must still leave its best round on GitHub. End with a short summary: the median score,
rounds used, fal spent, and where the files are.
