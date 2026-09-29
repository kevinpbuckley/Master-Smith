---
name: forge
description: Build a game-ready hard-surface asset (weapon, vehicle, aircraft, prop) with the ms tools - reference pictures, one whole-object seed from the model the owner picks, then Blender passes that improve it (material zones, glass, cockpit, fit, sharpen), six-view review, package. Assembly from separate parts only when the owner asks. Use when the owner asks to build, rebuild, fix or re-mesh a model.
---

# Build an asset with `ms`

`PY=.venv/Scripts/python.exe -m mastersmith.ms`. Everything below is run from the repo root. Read AGENTS.md's rules
first; read `mastersmith/skills/<category>.md` for the category. Say the cost of a step before spending.

Since 2026-09-29 an asset is ONE whole-object seed, improved in Blender (owner: "always just use a whole part unless
told otherwise and focus on letting user decide which seeding and models to use and then ... improve model that comes
back with blender skills"). On the M4A1 one Hi3D v3 multi-view request scored 6.5; the same model part by part 4.5
for 11x the money, Tripo parts 2.5-3. The part assembly is at the end, for when the owner asks for it.

## 0. Pictures that already exist are used, never redrawn without asking
Before ANY step that draws: `$PY status out/<Name>` (or `ls out/<Name>/ref out/<Name>/parts/*/`) and look at what is
there. `ref/ref_*.png` (and any `parts/<Part>/side.png`, `quarter.png`, `build.py`) are the asset's source, kept on
purpose. When they exist, show the owner the list and ASK whether to use them or draw again; use them unless told
otherwise. The tools refuse to draw over an existing picture; `--redraw` only after the owner said so.

## 1. Brief
`$PY new <Name> --category weapon|vehicle|aircraft|helicopter|prop --size <longest side, m> --description "..."`
Sizes: a rifle 0.65-1.0 m, a pistol 0.2 m, a truck 5-6 m, a gunship 12-18 m. `--tris 100000` for a hero asset.

## 2. The owner picks the models
`$PY models` lists every seed and picture model with what one call costs (built in: Hi3D v3, Tripo, Meshy, TRELLIS.2
and FLUX.2 on this PC; plus any registered local model). Show the owner the two short lists and ASK which picture
model draws the references and which seed model meshes the object, with your recommendation (hero picture nano-pro,
views nano; seed hi3d-mv, the best so far). Do not pick silently. A local model the owner runs on this machine is
registered once: `$PY models add <key> --kind seed --command "<exe> {image} {out} ..."` ({images} for several views,
`--inputs multiview`; a picture model takes {prompt} or {prompt_file}, {refs}, {out}).

## 3. Reference pictures (approve them with the owner before meshing anything)
- A hero picture: `$PY picture out/<Name> --out ref/ref_0.png --model <picture model> --prompt "..."` (`--ref` a photo
  when the owner gave one). Weapons: the hero is the side profile, muzzle to the right. Describe the design fully.
- Standard views from it: `$PY view out/<Name> --which side --from ref/ref_0.png` (forward end RIGHT; `--mirror` if not)
  and `--which front`; vehicles and aircraft also `--which back` and `--which top`. A multi-view seed is only as good
  as these: the views must be the same object, level and orthographic.
- Read each picture. Redraw with `--fixes "..."` when the design drifted; move a replaced draft into `ref/unused/`
  (never delete it). One line per job in `ref/notes.txt`, then `$PY refs out/<Name> [more jobs]` serves every picture
  with Approve / Redraw: give the owner the URL and WAIT unless told to skip it. Choices land in `ref/review.json`.

## 4. Grid and seed the whole object
- `$PY grid out/<Name> --side ref/ref_side.png --front ref/ref_front.png` (a weapon: `--side ref/ref_0.png`) ->
  `plan/side_grid.png`, dims. Read the grid; fix the size (`ms new --rebrief --size`) when the silhouette's length is
  not the real length (rotor blades, a crate stack's height).
- `$PY seed out/<Name> --model <seed model>` (say the price first) -> `parts/Body/seed.glb` from the approved views
  (multi-view models get side, front, back and the mirrored side; single-image ones the hero, or `--view`), registered
  to the side view -> `seed_render.png`, and a one-part plan that keeps the seed's own texture. Read `seed_render.png`
  beside `plan/side.png`: the same object, forward end right, upright, nothing missing. If it sits wrong,
  `$PY register out/<Name> Body --from side --yaw 180` (or `--pitch`). A failed seed is the owner's call: another model
  or better views (`--reseed` spends again).

## 5. Improve it in Blender (where the work goes)
The seed is the shape; these passes make it a game asset. Look at the six views after each and keep what helps.
- **Materials by zone**: in `plan/plan_draft.json` give the one part `zones` (percent boxes read off `plan/side_grid.png`)
  for every region in another material: bare dark steel (barrel, muzzle device, sights, bolts), glass (canopy,
  windows, lenses, lights), rubber (tyres, pads, grips), polymer, painted panels. The body keeps the seed's texture
  (`keep_texture`); a zone takes its planned colour and finish. `$PY plan out/<Name> plan/plan_draft.json`.
- **Outline**: `$PY fit out/<Name> Body` bends the seed through a lattice onto its side picture and refuses a fit that
  would crumple the surface; `$PY brush` for a local fault you can name (AGENTS.md, "Sculpting without a mouse").
- **Cockpit under glass**: when the canopy should show an interior, the seed needs an open cockpit (redraw the views
  with the canopy open, or cut it in Blender); then a cockpit part (`"interior": true`, `ms cabin` for its box and fit
  card, its own pictures and seed) and a glass part over it.
- **A weak detail** (a melted sight, a soft muzzle): ask the owner before replacing it with a separate part (the part
  tools below); a replacement is placed in its box on the body.

## 6. Assemble and review
`$PY assemble out/<Name>` (5-15 min) -> `delivery/SM_<Name>.glb`, previews, `preview_views.png`, `preview.html`.
After EVERY assemble that is reported, run `$PY preview out/<Name>` (background) and put the fresh URL in the message:
a delivery message without a live preview link is incomplete (owner, 2026-09-29).
Read `preview_views.png` and every `preview_*.png` yourself. Check, in this order:
1. Function (common sense): barrel, muzzle, sights and receiver on one axis from the FRONT and the TOP; the bore at
   the muzzle's centre; wheels on the ground; nothing floating, nothing poking through.
2. Proportions against the side picture.
3. Materials: steel dark and reflective, rubber matt, glass glassy, polymer satin; colours match the picture.
4. Edges crisp, muzzle round, no blobs.
5. Surfaces: the picture's white background as pale patches, or colours printed in the wrong place, mean the
   picture projection misfired: `assemble --no-projection`.
Score it /10 with the defects named by view; do not call it good under 7 without saying why.

## 7. Package
`$PY package out/<Name>` -> `delivery/<Name>.zip`. The delivery message carries, in this order: the preview URL (from
a `preview` run started after the last assemble), the GLB path, the zip path, the score /10 with defects by view, and
what was spent. A batch: write `delivery/scorecard.json` (`{"score", "spent", "defects"}`) per asset, then
`$PY results out/A out/B ...` serves them all on one page with a link to every preview.

## Assembly of parts (only when the owner asks)
The earlier way, kept for owners who want it: every part drawn alone, meshed alone and fitted into its box.
- Plan: `plan/plan_draft.json` split the way a modeller would (shape in AGENTS.md), percent boxes off the grids,
  touching boxes overlapping 1-2 %, real materials per part; `$PY plan out/<Name> plan/plan_draft.json`.
- Part pictures ($0.16 a part): `$PY part-pictures out/<Name> <Part>`; read both. The body's side picture is the
  approved view with the other parts erased; a side picture drawn facing backwards is turned round automatically.
- Code parts (free): `"method": "code"` and `parts/<Part>/build.py` (`def build(kit, L, W, H)`, hskit.py), `$PY build`.
  A code part's box is its TIGHT silhouette. `"skin": true` bakes the part's own diffused mesh's texture onto it.
  Machined parts meshed by diffusion come back wrong (the all-diffused M4A1 lost its barrel, its magazine a shell).
- Mesh and register: `$PY mesh out/<Name> <Part> --vendor <seed model>`; read `seed_render.png` beside the pictures.
- Part review gate before assembling: part, pass/fail, what differs, for the owner; drop a code part the seed
  already carries (a duplicate rail stood 6 mm off the handguard).
- The biggest part by volume is the body and keeps its seed's proportions; every other part fills its box.
