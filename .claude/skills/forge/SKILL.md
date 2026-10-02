---
name: forge
description: Build a game-ready hard-surface asset (weapon, vehicle, aircraft, prop) with the ms tools - reference pictures, one whole-object seed from the model the owner picks, then Blender passes that improve it (material zones, glass cut-outs, cockpit, fit, bevels), before/after six-view review, delivery gate, package. Assembly from separate parts only when the owner asks. Use when the owner asks to build, rebuild, fix or re-mesh a model.
---

# Build an asset with `ms`

`PY=.venv/Scripts/python.exe -m mastersmith.ms`. Everything below is run from the repo root. Read AGENTS.md's rules
first; read `mastersmith/skills/<category>.md` for the category and `materials.md` for the finishes. Say the cost of
a step before spending.

Since 2026-09-29 an asset is ONE whole-object seed, improved in Blender (owner: "always just use a whole part unless
told otherwise and focus on letting user decide which seeding and models to use and then ... improve model that comes
back with blender skills"). On the M4A1 one Hi3D v3 multi-view request scored 6.5; the same model part by part 4.5
for 11x the money, Tripo parts 2.5-3. The part assembly is at the end, for when the owner asks for it.

Keep the owner in the loop (AGENTS.md rule 12): answer their question before the next tool call, a one-line status
with the preview link at least every ~15 minutes or two assembles, and stop to show them after three assembles on the
same defect. Anything over a minute runs in the background.

## 0. Pictures that already exist are used, never redrawn without asking
Before ANY step that draws: `$PY status out/<Name>` (or `ls out/<Name>/ref out/<Name>/parts/*/`) and look at what is
there. `ref/ref_*.png` (and any `parts/<Part>/side.png`, `quarter.png`, `build.py`) are the asset's source, kept on
purpose. When they exist, show the owner the list and ASK whether to use them or draw again; use them unless told
otherwise. The tools refuse to draw over an existing picture; `--redraw` only after the owner said so. `status` also
prints the models the owner picked, what has been spent and the owner's notes (`decisions.json`): read it after a
compacted context instead of guessing; record a decision the moment it is made with `$PY note out/<Name> "..."`.

**Re-running a job** (another seed model, a benchmark, a rebuild with the current code): `$PY clone out/<Old>
<New>` - the pictures, the tuned plan (zones, glass, lettering) and every other part's seed come along, so only the
seed changes; `--keep-seed` to re-assemble the same seed for free. Never rebuild a tuned job from a fresh plan
(2026-09-30: the re-run Havoc lost its cockpit insert and canopy shell and fell from 9 to 5). The owner's standard
test set is `$PY bench --model <key>` (six assets, says the cost and waits for `--yes`) or `$PY bench --keep-seed`
(the same seeds, the current code, free); then score each against its baseline in `mastersmith/bench.json`.

## 1. Brief
`$PY new <Name> --category weapon|vehicle|aircraft|helicopter|prop --size <longest side, m> --description "..."`
Sizes (the category skills have more): a pistol ~0.2 m, a carbine 0.75-0.9, a rifle 0.9-1.1, a sniper rifle
1.1-1.3; a car 4.5, a truck 5-6, a main battle tank 8-10 with the gun; a fighter ~15; an attack helicopter 14-18
fuselage (rotors overhang); a gunship 12-18. `--tris 100000` for a hero asset.

## 2. The owner picks the models
`$PY models` lists every seed and picture model with what one call costs (built in: Hi3D v3, Tripo, Meshy, TRELLIS.2
and FLUX.2 on this PC; plus any registered local model). Show the owner the two short lists and ASK which picture
model draws the references and which seed model meshes the object, with your recommendation (hero picture nano-pro,
views nano; seed: Tripo from the hero, $0.60, for a first or benchmark run - it tied Hi3D multi-view on the M4A1 and
beat Tripo multi-view on the Havoc; `hi3d-mv`, $2.10, when the owner wants the best whatever it costs - it made the
eight Proteus weapons; AGENTS.md, What costs money). Do not pick silently; `note` the answer. A Codex session reads
"which trillio" as a question too: ask which model is meant, with the prices. A local model the owner runs on this machine is
registered once: `$PY models add <key> --kind seed --command "<exe> {image} {out} ..."` ({images} for several views,
`--inputs multiview`; a picture model takes {prompt} or {prompt_file}, {refs}, {out}).

## 3. Reference pictures (approve them with the owner before meshing anything)
- Picture rank: the owner's photos or screenshots > pictures found for the real thing > generated pictures > memory.
  A real or published design (an M4A1, an AH-64, the G-Police Havoc) is drawn from real photos or screenshots, never
  from memory - the Havoc came back as a generic plane twice (Tonetta); ask the owner for photos, nothing in `ms`
  looks one up. Disambiguate a name with its source ("Havoc gunship, G-Police").
- A hero picture: `$PY picture out/<Name> --out ref/ref_0.png --model <picture model> --prompt "..."` (`--ref` the
  owner's photo). Name the object first, then its construction and its materials as surfaces; one angle per prompt;
  plain background, even light, no text, watermark or people. Weapons: the hero is the side profile, muzzle right.
- Standard views from it: `$PY view out/<Name> --which side --from ref/ref_0.png` (forward end RIGHT; `--mirror` if not)
  and `--which front`; vehicles and aircraft also `--which back` and `--which top`. A multi-view seed is only as good
  as these: the same object, level and orthographic. A sheet of several views in one picture fuses into one mesh;
  strong perspective seeds a foreshortened mesh; a generated mechanism is not to be trusted.
- A muzzle is an open dark bore in every prompt and brief: never "a lens", "a crystal", "a glowing tip" or "a cap" in
  a muzzle (AGENTS.md rule 2; the laser cannon's ruby lens was the agent's own words, 2026-10-01). Glow belongs on a
  coil, a band or a lamp, never in a bore.
- Read each picture: `$PY refs out/<Name> [more jobs] --sheet --no-open` writes `<job>/ref_sheet.png` with every
  picture labelled, the checklist and what the pixels can warn (a long gun's muzzle on the left). What drifted on the
  Proteus weapons (9 of 38 pictures redrawn, 2026-09-30): heroes drawn three-quarter or facing left, a back view that
  was the front drawn again, a muzzle drawn closed or with a window in it, three tubes drawn as four in a diamond
  (accepted without a word - say it to the owner). Redraw with `--fixes "..."` when the design drifted; move a
  replaced draft into `ref/unused/` (never delete it). A weapon's back view often fails: when it is dropped, plan a
  `"flat"` zone on the rear cap (the mesher printed the muzzle onto it).
- One line per job in `ref/notes.txt`, then `$PY refs out/<Name> [more jobs]` serves every picture with Approve /
  Redraw: give the owner the URL and WAIT unless told to skip it. Choices land in `ref/review.json`.

## 4. Grid and seed the whole object
- `$PY grid out/<Name> --side ref/ref_side.png --front ref/ref_front.png` (a weapon: `--side ref/ref_0.png`) ->
  `plan/side_grid.png`, dims. Read the grid; fix the size (`ms new --rebrief --size`) when the silhouette's length is
  not the real length (rotor blades, a crate stack's height).
- `$PY seed out/<Name> --model <seed model>` (say the price first) -> `parts/Body/seed.glb` from the approved views
  (multi-view models get front, side and back; the far side is the side view mirrored only for weapons unless you
  pass `--mirror-far-side` for a symmetric vehicle; single-image models get the hero, or `--view`), registered to the
  side view -> `seed_render.png`, and a one-part plan that keeps the seed's own texture.
- Read `seed_render.png` beside `plan/side.png` and `$PY sheet out/<Name>/parts/Body/seed.glb` (the six views of the
  raw seed: the "before" for §6), and state the seed's disposition to the owner: **Ready**, **Targeted adaptation**
  (name the change: "cut the canopy glass", "zone the barrel steel"), or **Unsuitable** (the shape is wrong: another
  model or better views, the owner's call; `--reseed` spends again). If it only sits wrong, `$PY register out/<Name>
  Body --from side --yaw 180` (or `--pitch`).

## 5. Improve it in Blender (where the work goes)
The seed is the shape; these passes make it a game asset. Protect the seed: never hole-fill, boolean, decimate to
pass a check, strip parts or run "delete loose / remove small islands" on it (a latch and a bar are small islands too);
copy the mesh before a carve; two failed tries at the same part mean the approach is wrong - restore it and try a
different, smaller change. Look at the six views after each pass and keep only what helps.
- **Materials by zone**: in `plan/plan_draft.json` give the one part `zones` (percent boxes read off
  `plan/side_grid.png`) for every region in another material (materials.md): bare dark steel (barrel, muzzle device,
  sights, bolts), glass (canopy, windows, lenses, lamp covers), rubber (tyres, pads), `emissive` lights and screens
  (`"strength": 8`, 6-12), painted panels. The body keeps the seed's texture (`keep_texture`, its roughness lifted
  when it is glaze); a zone takes its planned colour and finish. `$PY plan out/<Name> plan/plan_draft.json`.
- **Glass is cut out**: a glass zone's faces are picked by the seed's texture colour inside the box (`"pick": "auto"`
  on a kept-texture seed: dark or pale paint, whichever covers more of the outside skin; `"dark"`, `"pale"`, `"lit"`
  to force one, `"box"` for every face in the box), only on the outside skin (the cockpit under it stays opaque:
  owner, 2026-09-29, "we also rendered the inside of the cockpit as glass"), grown across seams, small runs dropped,
  holes closed, up to 8 panes, and cut into a real see-through part (alpha 0.3, specular 0.45, no normal). Holes
  straight through the frame get a glass shell. The report checks it (`glass_zones` in report.json: mode, faces,
  coverage, `pane_faces` of shell); a canopy is 1-6% of the seed's faces. For one render, show the picked faces
  bright (red) and LOOK: a Tripo canopy is painted pale on its panes and dark on its roof and cockpit.
- **Whatever the glass shows has to exist**: a fighter or gunship cockpit (a dark tub hiding the shell, a seat, an
  instrument panel with screens, a stick, a HUD frame), a car cab (floor, two seats, a dash, a wheel, door cards):
  200-800 triangles, matte 0.7-0.9, nothing poking through, built LAST once the outside reads. A cockpit is about
  0.9 m wide and 1.3-1.4 m tall inside; a canopy 1.5-2.5 m long. A cockpit part (`"interior": true`, vendor, its
  own pictures and seed) under the glass REPLACES the seed's own: the assembler carves the seed's cockpit contents out
  of the body first (the faces in the interior's box that cannot see out with the canopy closed; the seed file is not
  touched), and `ms cabin` measures the carved well for its box and fit card. The Havoc (2026-09-29): Tripo's cockpit
  was a closed lump; plan box read off the grid, cabin's walls and sill, 2 Nano pictures and a Tripo mesh ($0.76).
  Then look at three things: the report's `pokes_out` (the share of the insert a ray sideways or down sees leave the
  hull; under 3%), the side close-ups (a tub rim above the sill blacks out the windows: sink the box), and the
  windscreen (a glare shield past the sloping glass: pull the box's front back).
- **Markings are paint**: stencils, numbers, stripes and painted vents stay in the texture, never geometry. A word
  the seed blurred, embossed or mirrored gets a `"lettering"` box on the part (percent off the side grid, generous):
  the picture's word prints whole on both sides and the relief is flattened. Check it in a close-up of each side,
  lit AND unlit (base colour only): shading ghosts come from the seed's normal map or leftover slivers, not the paint.
- **Shattered-looking glass** (the pick left opaque shards between glass faces): `"shell": true` on the glass zone
  rebuilds the canopy as one clean shell with a painted frame band and crease bars (AGENTS.md, Materials). Check it
  with the glass hidden and the frame bright once: what is left behind the glass should be the cockpit only. Only a
  single pane still opaque after that (a windscreen) takes `"pick": "fitted"` with a pane surface you fitted to its
  frame (AGENTS.md, The plan JSON); two failed glass passes on one canopy: restore the opaque canopy and show the owner.
- **Looking closely** without a probe script: `$PY closeup out/<Name> --box x0,x1,zt,zb --view left` (a box off the
  side grid), `--highlight glass` (the picked glass red), `--hide glass` (what is behind it), `--highlight lining`,
  `--highlight <Zone>` (a zone's faces red), `--unlit` (the paint alone: lettering ghosts from the normal map show as
  what they are), `--clay` (the shape alone), `--section y=0.2` (cut open, the near side away). Read each one.
- **Nudging boxes** (a cockpit insert 1% lower, a glass pick, a zone's edge): `$PY assemble out/<Name> --draft` stops
  before the bake (about a minute instead of 5-15) and renders the placed parts with their glass, lining and muzzle
  into `delivery/draft/`, with `pokes_out`, `glass_zones` and the muzzle in `draft/report.json`. The full assemble
  runs once, when the draft reads right (the Havoc took ~18 full assembles for 1% nudges, 2026-09-29).
- **Cockpit behind glass**: the walls seen through the canopy are lined from behind (a dark matte inside) so the far
  panels' backs and their mirrored lettering do not show. A pane modelled with a thickness has its inner skin taken
  as glass too (it was lined black). Show the lining bright once (`MI_<Name>_Interior`) to see what it covers.
- **Outline**: `$PY fit out/<Name> Body` bends the seed through a lattice onto its side picture and refuses a fit that
  would crumple the surface; `$PY brush` for a local fault you can name (AGENTS.md, "Sculpting without a mouse").
- **Symmetry**: a seed broken on one side is repaired about the asset's own centre plane (not world Y=0), mirroring the
  intact side by scale -1 with its UVs.
- **A weak detail** (a melted sight, a soft muzzle): ask the owner before replacing it with a separate part (the part
  tools below); a replacement is placed in its box on the body.

- **A blurry or washed-out seed texture** (paid, the owner's pick in `ms models`): `$PY retexture out/<Name>` repaints the
  whole seed on its own UVs from the hero picture and the brief (Meshy v5, ~$0.30); `registered_before_retexture.blend`
  is the undo. Compare before and after; keep it only when it reads better.

## 6. Assemble and review
`$PY assemble out/<Name>` (5-15 min, in the background) -> `delivery/SM_<Name>.glb`, previews, `preview_views.png`,
`preview.html`, and it prints the preview link; `--no-bevel` drops the baked edge bevel, `--drop-floaters` deletes only
far, small islands (measured in the report either way), `--origin` sets the pivot (a vehicle: `bottom`; a pylon
weapon: `mount`), `--tubes N` names a launcher's loaded tubes. The finish is the restrained profile (AGENTS.md rule 4)
and a kept texture takes the pictures only in its lettering boxes, its colour cast graded to the picture
(`--projection full` for the old way). After EVERY assemble that is reported, put the preview link in the message
(`$PY preview out/<Name> --no-open` prints it again): a delivery message without a live preview link is incomplete
(owner, 2026-09-29: "where's my preview link?"). Every page is on ONE site and
port (owner, 2026-09-29): http://127.0.0.1:8765/ lists every build, /results shows them with their six views, /refs the
reference review, and each preview is http://127.0.0.1:8765/<Name>/delivery/preview.html with a nav bar back.
Read `preview_views.png` and every `preview_*.png` yourself, and `delivery/report.json`'s `gate` (warnings) and
`islands`. What each view proves: FRONT only the nose end-on (a wheel seen as a circle from the front faces the wrong
way); SIDE proportions and ground contact; TOP symmetry and centring (paired parts are proved from TOP, BOTTOM or FRONT,
never called single from the SIDE); BOTTOM open hulls and missing faces; the iso previews hide gaps. Check, in this order:
1. Function (common sense): barrel, muzzle, sights and receiver on one axis from the FRONT and the TOP; the bore at
   the muzzle's centre and open (`preview_detail_muzzle.png` end-on, `report.json` `muzzle`; the gate warns when it is
   closed - a lens, a cap or a glow in a bore is a defect); wheels on the ground; nothing floating, nothing poking
   through.
2. Proportions against the side picture and the real sizes (a grip 30-35 mm across, a bore 5.6-7.6 mm, a car 4.5 x
   1.8 x 1.45 m on 0.65 m wheels 2.7 m apart). Detail follows attention: the business end, the front and the cockpit.
3. Materials: steel dark and reflective, rubber matt, glass see-through with the cockpit behind it, polymer satin,
   lights glowing; colours match the picture. "Bumpy relief" on a glossy surface and a painted hull under 0.35 mean
   roughness (reads plastic) are defects.
4. Edges crisp but broken (a small bevel, never razor), muzzle round, no blobs.
5. Surfaces: the picture's white background as pale patches, or colours printed in the wrong place, mean the
   picture projection misfired: `assemble --no-projection`.
6. Before and after: compare the delivery with the raw seed's six views (§4). A part lost, markings lost, a coloured
   model turned grey or washed out, its surface detail flattened, or glass turned opaque is a defect caused by a pass:
   that pass is dropped, not repaired again.
Write the review from a part list (what the pictures show, and what is deliberately absent; a part the pictures do
not show is a defect even if the real-world cousin has it): defects worst first, each naming the part and the view and
what is wrong (not how to fix it) - three real problems beat twelve observations; what no view can prove goes in an
"unverifiable" list. If nothing improved since the last review, change the approach, not the effort.
Score it /10 against the owner's anchors, not against your last build (2026-09-29: a parts batch self-scored 7-8; the
owner put its M4A1 at 3):
- 3: the Tripo-parts M4A1 with code parts (out/M4A1) - parts misaligned from the TOP, a plasticky mix of surfaces.
- 5: the Tripo-benchmark Apache, shotgun and Havoc of 2026-09-30 - an opaque canopy, a raised tail wheel, garbled
  lettering, a closed-looking muzzle, a blue cast.
- 6.5: one Hi3D multi-view or one Tripo seed of the M4A1 with zones (out/M4A1_hi3d_whole, out/M4A1_tripo_whole) -
  coherent, soft sights and controls, glossy.
- 9: out/HavocGunship_tripo_whole - clean glass with the cockpit behind it, the lettering whole on both sides, the
  reference's colours.
A first assemble of a seed is usually 5-7. 8 or more needs every reference feature present from all six views,
nothing misaligned from the TOP, nothing seen through glass but the cockpit, and the colours on the reference's. Write
`delivery/scorecard.json` (`{"score", "spent", "defects", "unverifiable"}`); the pages show it as "self" until the
owner scores it (`"owner_score"`).

## 7. Package
`$PY package out/<Name>` -> `delivery/<Name>.zip`, printing the delivery gate's warnings (LOD0 within the budget
x1.05, BaseColor/Normal/ORM present, size within +-10% of the brief, glass present when asked for, mean roughness
>= 0.3, UCX hull <= 256 triangles, the muzzle open, the FBX read back at size with unit node scale). The delivery
message carries, in this order: the preview URL, the GLB path, the zip path, the score /10 with defects by view, the
pivot and sockets for a game asset, and what was spent. The same when another project takes the asset (the Proteus
weapons went without previews, scores or zips, 2026-09-30).
A batch: `$PY batch assemble out/A out/B --parallel 2` (a log per job, one line each; a spending command needs
`--yes`), write `delivery/scorecard.json` per asset, then `$PY results out/A out/B ...` gives the builds page for just
those (http://127.0.0.1:8765/results?jobs=A,B). Several briefs at once: `$PY new --from briefs.json`.
For an engine (AGENTS.md, Unreal handoff): the FBX is centimetres with `SOCKET_` empties; a rigged weapon is
`$PY rig out/<Name> [--origin mount] [--barrel 0.6,0.74] [--loop jet]` -> `delivery/rig/`; check the size, pivot and
sockets in the engine before calling it done.

## Assembly of parts (only when the owner asks)
The earlier way, kept for owners who want it: every part drawn alone, meshed alone and fitted into its box.
- Plan: `plan/plan_draft.json` split the way a modeller would (shape in AGENTS.md), percent boxes off the grids,
  touching boxes overlapping 1-2 % (Tonetta overlaps 5-15 mm on a handheld, 2-5 cm on a vehicle), real materials
  per part; `$PY plan out/<Name> plan/plan_draft.json`.
- Part pictures ($0.16 a part): `$PY part-pictures out/<Name> <Part>`; read both. The body's side picture is the
  approved view with the other parts erased; a side picture drawn facing backwards is turned round automatically.
- Code parts (free): `"method": "code"` and `parts/<Part>/build.py` (`def build(kit, L, W, H)`, hskit.py), `$PY build`.
  A code part's box is its TIGHT silhouette. `"skin": true` bakes the part's own diffused mesh's texture onto it.
  Machined parts meshed by diffusion come back wrong (the all-diffused M4A1 lost its barrel, its magazine a shell).
- Mesh and register: `$PY mesh out/<Name> <Part> --vendor <seed model>`; read `seed_render.png` beside the pictures.
- Part review gate before assembling: part, pass/fail, what differs, for the owner; drop a code part the seed
  already carries (a duplicate rail stood 6 mm off the handguard).
- The biggest part by volume is the body and keeps its seed's proportions; every other part fills its box.
