# Master Smith - worked by a coding agent in this folder

Master Smith builds game-ready hard-surface 3D assets (weapons, vehicles, aircraft, props) from ONE whole-object seed
by default (since 2026-09-29): the approved views go to the seed model the owner picks, and the Blender passes improve
what comes back (material zones, glass, cockpit, fit, sharpen). An ASSEMBLY of parts - every part drawn alone, meshed
alone and fitted into its box - only when the owner asks for it. Since 2026-09-28 the owner works it from here: the coding agent (Claude Code, Codex, or another that reads this file) is
the director, planner and reviewer; the deterministic tools
in `python -m mastersmith.ms` do the drawing, meshing, registering and assembling. No server, no web page, no
container, no paid model API: the service and the chat app were deleted on 2026-09-28 (git history before commit
"Delete the service" has them); the one-seed build came back as `ms seed` on 2026-09-29. Lessons from Tonetta's
production forge (E:/az-dev-ops/ToneBoard/tonetta-forge, compared 2026-09-29) are folded into these files.

Run everything from this folder with the venv: `.venv/Scripts/python.exe -m mastersmith.ms <command>`.
The step-by-step recipe is `.claude/skills/forge/SKILL.md` (Claude Code invokes it as `/forge`; Codex as `$forge`
through the `.agents/skills` link). Run `./scripts/setup-skills.ps1` once on Windows to create the link.
Keep shared skills in `.claude/skills`; both agents use the same files. Read the recipe before a build.
Agent-specific notes live in that agent's own file: `CLAUDE.md` (Claude Code reads it itself) and `CODEX.md` (Codex:
read it before the first command; it covers the sandbox, output truncation and the co-author line).

## Where things live

- `out/<Name>/` one job (folder name = asset name; `ms new` makes it):
  `brief.json` · `ref/` reference pictures · `plan/` side.png, front.png, `*_grid.png`, `dims.json`, `plan.json` ·
  `parts/<Part>/` side.png, quarter.png, seed.glb, registered.blend, registration.json, seed_render.png, fit.json ·
  `delivery/` SM_<Name>.glb + LODs, T_ maps, preview_*.png, `preview_views.png` (six sides), `preview.html`
  (written by `assemble`; `ms preview` opens it on the one site, http://127.0.0.1:8765/), report.json, zip;
  `delivery/draft/` (`assemble --draft`), `delivery/closeups/` (`ms closeup`), `delivery/rig/` (`ms rig`) ·
  `decisions.json` the models the owner picked, every paid call's cost and the owner's notes (`ms status` prints it) ·
  `ref_sheet.png` every reference picture on one sheet (`ms refs --sheet`).
- `mastersmith/bench.json` the owner's standard test set ("the test we have been running": the bullpup, M4A1, tank,
  Apache, shotgun and seeded Havoc), each from its best-tuned job, with its baseline score (`ms bench`).
- `mastersmith/skills/<category>.md` what a good asset of that category is (weapon, vehicle, aircraft, helicopter,
  prop, character, environment). Read the one for the job's category before planning.
- `mastersmith/blender/` the Blender scripts: `register_part.py` (turn the seed to match its picture),
  `assemble.py` (fit, tint, zones, glass, sharpen, bore alignment, bake, LODs, previews), `six_views.py`.
- `.env` holds FAL_KEY (git-ignored). NEVER print, echo, cat or grep the keys; never put them in a message.
- Local models: TRELLIS.2 (`trellis-cli.exe`, E:/local-models) meshes for free; FLUX.2 klein draws locally
  (`--model local`, weak). Any other model running on this machine is registered by its command line
  (`ms models add`, kept in the git-ignored `local_models.json`) and then used like a built-in one. ComfyUI at E:/local-models/ComfyUI (Qwen-Image-Edit angles LoRA, unused so far).

## What costs money

- `ms models` lists every model with its price; the OWNER picks the picture model and the seed model for each job
  (ask, with a recommendation; never pick silently; `ms note` the answer so it survives a compacted context).
  Pictures: Nano Banana (`nano`) about $0.08, `nano-pro` $0.15, FLUX.2 klein on this PC free. A whole-object seed:
  Hi3D v3 multi-view (`hi3d-mv`) $2.10; Tripo $0.60 (billed 2026-09-28; not $0.30); Meshy v7 $0.05; TRELLIS.2 on this
  PC free (TRELLIS.2-fast meshed an M4A1 in 44 s at silhouette overlap 0.82). What the builds showed (2026-09-29 to
  10-01): on the M4A1 one Tripo seed ($0.60) scored the same 6.5 as one Hi3D multi-view ($2.10); on the Havoc a Tripo
  seed from the hero beat Tripo multi-view (the multi-view grew stray pylons and lost its rocket pods; the hero seed
  reached 9 after the Blender passes); Hi3D multi-view gave eight Proteus weapons usable seeds when the owner asked
  for the best regardless of cost ("those look awesome"); the six-asset Tripo benchmark scored 5-7. Recommend Tripo
  from the hero for a first or benchmark run, `hi3d-mv` when the owner wants the best whatever it costs.
  A part build pays per part (a 14-part gun: ~28 pictures, ~$2.30, plus a mesh per part).
- Blender passes: free. Registration ~30 s, assembly 5-15 min, six views ~2 min.
Say the estimate before a step that spends, in one line; never spend on a step the owner did not ask for.

## The owner's rules (learned the hard way; do not relearn them)

1. LOOK at every picture and render with the Read tool before moving on. Nothing is "good" until you have seen
   `delivery/preview_views.png` from all six sides (top, bottom, front, back, left, right) and the previews. Your
   score is a claim, not a result: score against the anchors in the recipe (§6) - on 2026-09-29 a parts batch was
   self-scored 7-8 and the owner put its M4A1 at 3; a Havoc called 8 with "the seat shows through the glass" showed
   the background through it. The pages mark a score "self" until the owner gives one (`owner_score`).
2. Judge function by common sense, no reference needed: a bullet must be able to leave the gun (barrel, muzzle,
   sights and receiver on ONE axis, seen from the front and the top), wheels touch the ground, a canopy sits on the
   hull, nothing floats or pokes through. A muzzle is round, not oval, and an OPEN dark bore: never write a lens, a
   crystal, a plug, a cap or a glow into a muzzle's brief, picture prompt or plan - a muzzle flash or an energy beam
   is the engine's effect (owner 2026-10-01: the laser cannon's orange tip "should just be hollow"; the agent had
   written "a glowing ruby-red crystal lens set inside the muzzle" into the brief itself). `assemble` measures the
   bore end-on, renders `preview_detail_muzzle.png` and warns when the muzzle is closed.
3. Real materials: metal (barrel, muzzle device, bolt, rails) is dark reflective steel, grips and pads are rubber,
   optics have glass, furniture is polymer. One graphite-looking material everywhere is a fail. Colours come from
   the picture (`ms plan` samples them per part), not from guesses.
4. Edges are crisp but broken, never razor (Tonetta: "a perfectly sharp edge reads as fake"; owner 2026-09-29: code
   parts "too sharp"): the assembler flattens a seed's planar panels and creases their edges, then every edge carries
   a small bevel - on a seed baked into the normal map from Blender's Bevel shader, on a code part a geometric edge
   break. The finish is the restrained profile by default (since 2026-10-02): the baked bevel 0.05% of the length and
   at most 1.5 mm, the normal and bump relief weakened, matte floors by finish, no metallic on paint or polymer. The
   old 0.2% bevel grew to 28 mm on the 14 m Havoc and, with the stacked 1 mm bumps and glossy worn edges, read as
   melted ("are you able to ... fix the gooeyness?", owner 2026-09-30); `--finish-profile standard` brings it back,
   `--no-bevel` turns the bevel off. Panel edges 1-3 mm, micro detail 0.5-1 mm or none. A soft-plastic look the
   restrained finish does not cure is the seed: soft sights and lumpy controls are geometry - redraw, re-seed, or
   replace that detail after asking.
5. One whole-object seed unless the owner asks for parts (2026-09-29: one Hi3D v3 multi-view M4A1 scored 6.5; the
   same model part by part 4.5 for 11x the money, Tripo parts 2.5-3). Its other materials come from zones on the one
   part; weak details are fixed in Blender, or replaced by a part after asking. For a part build (the owner asked),
   hybrid since the evening of 2026-09-28 (the all-TRELLIS carbine came back "a mess": leaning sights, a rail that was
   an upper receiver, crumpled edges): SCULPTED parts (receiver, grip, handguard, a hull, a tyre) are meshed from their
   own pictures; MACHINED parts (rails, sights, trigger, charging handle, barrel, muzzle device, magazine, selector)
   are `"method": "code"` - built by `parts/<Part>/build.py` with the hard-surface kit (`ms build`), crisp by
   construction. Split the way a modeller would: barrel, muzzle device, each rail, each sight, magazine, grip, stock,
   handguard, each control, each wheel, each pod. Never lump (four tyres together came back as one black blob).
6. The part pictures are kept in `parts/<Part>/` so the same parts can be meshed again with a better model later.
   Never delete them. They, `ref/ref_*.png` and `parts/<Part>/build.py` are the asset's SOURCE: before drawing
   anything, check what exists (`ms status`) and ask the owner whether to use it; the picture tools refuse to draw
   over an existing picture and only `--redraw`, after a yes, draws again (2026-09-28: a job is routinely cleared
   down to its pictures and rebuilt for free).
7. Sizes are read off the gridded picture as percent boxes; touching parts overlap 1-2 %; boxes cover the whole
   silhouette. Thin free-standing parts (barrel, muzzle) get their height measured off the silhouette by `ms plan`.
8. The biggest part keeps the depth the mesher gave it (`keep_depth`); every other part fills its box on all three
   axes (`fill_box`). Parts on the bore axis (barrel, muzzle, suppressor, sights) are `centreline` parts and get
   moved onto the body's bore by the assembler.
9. Registration: a seed from a three-quarter picture is yaw-swept, pitch-swept, and, when long, sheared out of its
   perspective. Check `parts/<Part>/seed_render.png` against `side.png`; if it sits wrong, `ms register <job>
   <Part> --yaw <deg> --pitch <deg>` (yaw about the vertical, pitch in the side plane, degrees) and look again.
10. Protect the seed. Before editing, state its disposition: Ready, Targeted adaptation (name the change), or
    Unsuitable. Never hole-fill, boolean, decimate to pass a check, strip parts or run "delete loose / remove small
    islands" on a seed (latches and bars are small islands); copy the mesh before a carve; two failed attempts at the
    same part mean the approach is wrong - restore it and try a different, smaller change. Review before against after
    (`ms sheet parts/Body/seed.glb` vs the delivery): a lost part, lost markings, colour turned grey, a surface washed
    out or its detail flattened, or glass turned opaque is a defect caused by a pass, and the pass is dropped.
11. Commit only when `.venv/Scripts/python.exe -m pytest tests -q` passes. Commit messages end with
    the agent's own co-author line (see its file). `dev` is the working branch (owner, 2026-09-28): commit and
    push there directly. `master` is what people run; it changes only by a PR from `dev` that the owner merges.
    When another session or a long run is working in this tree, do not change code under it (owner, 2026-09-29: "wait
    til this other current run ends before changing code"): work in a git worktree with `MASTERSMITH_DATA=<the main
    tree>` (the jobs stay in its out/), absolute job paths and the main tree's `.env`, and commit only your own hunks
    (`git add -p`); another session's work is committed only when the owner says so (a commit on 2026-09-29 swept in
    another session's hunks).
12. Keep the owner in the loop. Answer an owner's question before the next tool call; never go more than ~15 minutes
    or two assembles without a one-line status and the preview link; after three assembles on the same defect, stop
    and show the owner what you have (2026-09-29: 57 minutes of silent canopy polishing, "what are you doing?" never
    answered, then "stop"; 2026-10-01: "are you stuck?"). Run anything over a minute in the background and say so;
    nudge boxes with `assemble --draft` (about a minute) and run the full assemble once.
13. The delivery steps hold whoever takes the asset: a preview link per job, a score /10 with defects, `scorecard.json`
    and `ms package` - the eight Proteus weapons went to another project with none of them (2026-09-30). An asset
    for a game is checked in the engine before it is called done: its size, its pivot and its sockets (see Unreal
    handoff; "the weapons are massive and not attached to the ship", 2026-10-01).

## The plan JSON (written by you, validated by `ms plan`)

Percent boxes are read off `plan/side_grid.png` (0 = left/top edge, 100 = right/bottom edge; forward end on the
RIGHT) and `plan/front_grid.png` when there is one (looking back at the forward end, the object's left on the right
of the picture). Without a front picture, `front_span` is your estimate of the part's width as percent of the
object's full width, centred parts symmetric about 50.

```json
{"parts": [
  {"name": "Barrel", "what": "one sentence: shape, features, colour and finish, as seen alone in the picture",
   "method": "vendor",
   "side_box": [x_left, x_right, z_top, z_bottom],
   "front_span": [y_left, y_right],
   "material": {"color": "#rrggbb", "finish": "metal|polymer|rubber|painted|glass|wood|fabric|concrete|emissive",
                "metal": true, "roughness": 0.35, "glass": false, "keep_texture": false},
   "zones": [{"name": "Pad", "side_box": [...], "front_span": [...], "material": {...}},
             {"name": "Canopy", "side_box": [...], "front_span": [...], "material": {"finish": "glass"}},
             {"name": "Lamp", "side_box": [...], "front_span": [...], "material": {"finish": "emissive", "strength": 8}}]}
 ],
 "notes": "anything the assembly must respect"}
```
`zones` are areas of a part in a different material (rubber pad on a polymer stock, glass lens on a scope); on a
whole-object seed they carry every material that is not the seed's own texture. A glass zone is cut out into a real
see-through part: its faces are picked by the seed's texture colour inside the box (`"pick": "auto"`, the default on
a kept-texture seed, takes whichever of `"dark"` (near-black, blue-grey) and `"pale"` (light unsaturated grey, a pane
painted with the sky in it) covers more of the outside skin; `"lit"` for a glowing window; `"box"`, the default
otherwise, takes every face), grown across seams, small runs dropped, holes closed, up to 8 panes kept. Only the
OUTSIDE skin is glass: a face whose rays all hit the model (seats, panels, the cockpit lump) stays opaque. Holes that
go straight through a canopy frame get a glass shell (the canopy's convex hull, set just inside the frame; `"fill":
false` turns it off). The report checks the kept panes hold 60% of the pick, at most 40 islands, at most 8% of the
part (a box test alone is never enough, Tonetta: "never assign glass face by face from a normal or a box test").
Which glass pass, in this order (three exist; on 2026-09-30 a re-run invented a third instead of using the one that had
worked): the colour pick above; `"shell": true` when that pick reads as shattered (opaque shards between glass faces -
the Havoc's 9/10 canopy); `"pick": "fitted"` only for one pane that stays opaque under both, a windscreen whose pane
surface you fitted to the frame yourself and checked in a close-up: `"vertices": [[x, y, z], ...]` (metres, the asset
frame), `"triangles": [[i, j, k], ...]`, `"tolerance"` (metres either side of the pane) and optional `"bounds": [[lo],
[hi]]`; only the thin skin under it goes, the frame and the cockpit stay (the Havoc's windscreen, 2026-10-01). Two
failed glass passes on one canopy: restore the seed's opaque canopy and show the owner (rule 10). An
`emissive` zone glows at `"strength"` 6-12 (on the zone or its material) and is baked into T_<Name>_E. With `"glow"` it glows only where the
texture already shows the glow's colour: `{"hue": degrees, "hue_tol": 20, "min_sat": 0.35, "min_val": 0.35}` or
`"#rrggbb"` (2026-09-30: a ray gun's lens, violet bands between gunmetal rings, a torpedo's lit tip); the rest of
the box keeps its own colour and finish, so a generous box is fine as long as nothing else in it has that hue.
`"flat": true` on a zone paints its planned colour alone, none of the texture: for a face the mesher textured wrong
(a seed with no back view printed its glowing muzzle onto the rear cap; a tint kept the lightning at +-50%). `metal`
is true only for bare metal. A dark metal is lifted to 7% reflectance by adding grey (`mastersmith/blender/colour.py`), but a tinted colour
still renders more saturated on large flat faces: give blued or black steel a near-neutral colour (the shotgun's #283446 came out navy,
2026-09-29). `"reference_detail": false` on a code part skips projecting the reference picture's
surface detail onto it (for a part whose coded shape is not the drawn one: folding sights, 2026-09-28). `"skin": true` on a code part dresses its exact coded shape in the texture of its own diffused mesh (draw its pictures and `ms mesh` it; the assembler bakes that mesh's colour onto the code part and tints it to the plan): code parts no longer read as flat CG beside the diffused ones (owner, 2026-09-29; an all-diffused M4A1 lost its barrel and its magazine came back a see-through shell, so machined parts stay code). Every code part's edges get a small round (0.08% of the asset's length, `"edge_break": false` keeps them razor sharp, `assemble --no-edge-break` for all). `"interior": true` marks a cockpit or cabin: `ms cabin` measures the body's well and gives it the box that fits, its pictures are drawn as an insert of that size, and the assembler reports how much of it pokes into the body. Under a glass zone it replaces the seed's own cockpit (2026-09-29): the assembler carves the body's faces in the interior's box that cannot see out with the canopy closed (the seed file stays as it was), `ms cabin` measures that carved well (its rays start at the interior's planned top, under a hood or frame bars), and the report's `pokes_out` is the share of the insert that a ray sideways or down sees leave the hull and its glass (keep it under 3%). The glass, its shell and the lining are counted in the triangle budget. `"color_lock": true` always tints a vendor part to its planned colour. A rifle is 10-16 parts, a pistol 6-10, a truck 12-20, an aircraft 8-14.
`ms plan` prints `IGNORED ...` for every key or value it did not take (a misspelt key, a pick that does not exist, a
zone whose box failed): fix the draft, they do nothing otherwise. After a default changes, re-read the job's own
`plan_draft.json` for options it still forces (a draft's `"pick": "dark", "keep": 4` outlived the new default and cost
an assemble, 2026-09-29).

## Commands (`python -m mastersmith.ms ...`)

| command | does |
|---|---|
| `new <Name> --category weapon --size 0.68 --description "..."` / `new --from briefs.json` | makes `out/<Name>/` with brief.json (`--from`: a JSON list of `{"name", "category", "size", "description"}`, several jobs at once) |
| `clone <job> <NewName> [--reseed Body] [--keep-seed]` | a job to rebuild from: its pictures, its tuned plan (zones, glass, lettering) and every part's seed but the re-seeded one (the cockpit insert comes along); `--keep-seed` copies the seeds too, for a free re-assemble with the current code. A re-run of a job that has a tuned plan starts here, never from a fresh plan (2026-09-30: the re-run Havoc lost its insert and shell, 9/10 -> 5/10) |
| `bench --model <key> [--yes] \| --keep-seed [--only A,B] [--tag T]` | the owner's standard set (`mastersmith/bench.json`): each asset cloned from its best-tuned job, seeded (says the cost and stops without `--yes`), assembled; a summary in `out/_bench/` and the results link; then score each against its baseline |
| `batch <command> <job> <job> ... [--parallel 2] [--args "..."] [--yes]` | one command over several jobs, a log per job (`<job>/batch_<command>.log`), one line each; a spending command needs `--yes` after the owner agreed |
| `note <job> "the owner picked tripo"` | the owner's decision in `decisions.json`, beside every paid call's cost; `ms status` prints them |
| `open <job> [--part Body] [--rig]` | the delivery (or a part's seed, a copy kept first; or the rig) in Blender's own window with the user's add-ons (BlenderMCP), for work by hand or a live MCP session; every other Blender run is headless with factory settings |
| `picture <job> --out ref/ref_0.png --prompt "..." [--ref file] [--model nano\|nano-pro\|local]` | draws a picture |
| `view <job> --which side\|front\|back\|top\|quarter --from ref/ref_0.png [--mirror] [--fixes "..."]` | one standard view of the same object |
| `grid <job> --side ref/ref_side.png [--front ref/ref_front.png] [--mirror]` | crops to the silhouette, draws the percent grids, writes dims.json |
| `models [add <key> --kind seed\|picture --command "..." [--inputs multiview] \| remove <key>]` | every seed and picture model with its price (built in: Hi3D v3, Tripo, Meshy, TRELLIS.2, FLUX.2, Nano Banana); `add` registers a model that runs on this machine by its command line: `{image}` / `{images}` / `{out}` (seed), `{prompt}` / `{prompt_file}` / `{refs}` / `{out}` (picture) |
| `seed <job> --model <key> [--view hero\|left\|front] [--part Body] [--replan] [--reseed] [--mirror-far-side]` | the whole object in ONE request from the approved views (multi-view models get front, side and back; the far side is the side view mirrored only for weapons by default, since a vehicle's fuel door or an ejection port is one-sided - `--mirror-far-side` for a symmetric vehicle), registered to the gridded side view, with a one-part plan that keeps the seed's texture when there is none: the default build |
| `retexture <job> [--model meshy-retexture] [--part Body] [--prompt "..."] [--no-picture]` | a paid pass the owner picks (Meshy v5 retexture, ~$0.30): the registered seed's geometry goes out with one UV layer and no maps, a new texture comes back on every side, guided by the hero picture and the brief, fitted onto the seed's bounds; `registered_before_retexture.blend` is the undo |
| `plan <job> plan.json` | validates your plan, snaps thin parts, samples colours, writes plan/plan.json |
| `part-pictures <job> <Part> [--fixes "..."] [--no-quarter] [--no-front] [--with-front] [--no-side]` | side picture of that part alone + its three-quarter picture. A side picture drawn facing the wrong way is turned round (kept in `unused/`). Only the body's three-quarter picture gets the whole-object front view (it made 8 of 13 parts come back as the whole rifle; `--with-front` for another part). An `interior` part is drawn as the insert that fills its box, with `fit_card.png` |
| `build <job> <Part>` | a `"method": "code"` part: runs `parts/<Part>/build.py` (`def build(kit, L, W, H)`, kit in `mastersmith/blender/hskit.py`) -> `<Part>.blend` + side/front/iso renders |
| `mesh <job> <Part> [--vendor local\|tripo\|hitem3d3] [--from quarter\|side]` | meshes the part and registers it |
| `register <job> <Part> [--yaw deg] [--pitch deg] [--from side]` | registers again, with your correction |
| `fit <job> <Part> [--quarter] [--free]` | bends the registered seed through a coarse lattice until its outline lies on its side picture (and three-quarter picture), reports the overlap before/after and how far the surface turned; a fit that would crumple the surface or gains nothing is refused and the mesh left as it was (`--free`: the old per-vertex fit, which crumpled a Tripo fuselage by 1 m); `registered_unfitted.blend` is the undo |
| `cabin <job> <Part> [--hull <Part>]` | measures the body's open cockpit well (floor, walls, sill) with rays on its registered seed placed as the assembler places it, prints the interior's box that fits (mm and plan percents) and draws `parts/<Part>/fit_card.png` |
| `brush <job> <Part> --op inflate\|move\|smooth\|flatten\|crease --at front+0,0,-0.01 --radius 10 --strength 2` | one headless brush stroke (mm; anchors front/back/top/bottom/left/right/centre); logged in `brush_log.json`, `--replay` after a re-mesh |
| `sdf <job> <Part> [sdf.py]` | an exact part from `parts/<Part>/sdf.py` (`def part(kit, L, W, H)`, the kit in `mastersmith/sdfkit.py`): marching cubes in the part's box, imported as `registered.blend` with the planned material |
| `assemble <job> [--draft] [--projection auto\|full\|letters\|off] [--origin centre\|bottom\|top\|rear\|front\|mount\|grip] [--tubes N] [--finish-profile restrained\|standard] [--parts A,B] [--no-sharpen] [--no-bevel] [--drop-floaters]` | fits, tints, zones, glass cut-outs, bakes (BaseColor, Normal with the bevel, ORM, Emissive), LODs, previews, six views, the muzzle close-up, sockets, exports (GLB and .blend in metres, FBX in centimetres, read back); `report.json` carries `islands` (loose pieces far from the body, open edges, non-manifold share - measured, not deleted; `--drop-floaters` deletes only far, small ones), `muzzle`, `sockets`, `fbx_check` and the delivery `gate`; prints the preview link. `--draft` stops before the bake (about a minute): renders of the placed parts with their glass, lining and muzzle into `delivery/draft/`, the delivery untouched. `--tubes N`: a launcher's loaded or capped tubes as Muzzle_0..N-1 |
| `closeup <job> [--box x0,x1,zt,zb] [--view iso\|left\|right\|front\|back\|top\|bottom\|iso_rear] [--unlit] [--clay] [--hide glass,lining] [--highlight glass\|lining\|frame\|<zone>] [--section y=0.1]` | one close-up of the delivery the way a review needs it: a box off the side grid, the glass hidden or red, a zone's faces red, the paint unlit, clay, or cut open -> `delivery/closeups/`. It replaces the throwaway probe scripts (17 on the Havoc, 2026-09-29) |
| `rig <job> [--origin keep\|mount\|...] [--barrel 0.6,0.74] [--recoil 0.05] [--kick 0] [--loop jet\|coil] [--idle coil] [--no-glow]` | a delivered weapon rigged for an engine: Root/Body/(Barrel)/Muzzle bones at the measured muzzles, rigid skin, Idle/Fire/Equip(/FiringLoop) clips, `SK_<Name>.fbx` and `A_<Name>_<Clip>.fbx` in centimetres with no node scale, read back, the T_ maps beside them -> `delivery/rig/` |
| `sheet <file.glb>` | six views of any GLB |
| `refs [<job> ...] [--no-open] [--sheet]` | serves the reference pictures of the listed jobs (all jobs when none) on one local page with Approve / Redraw and a note per picture; the owner's choices land in `ref/review.json` (`ms status` prints them). Drafts moved to `ref/unused/` are not shown; `ref/notes.txt` is shown above a job's pictures. `--sheet` writes `<job>/ref_sheet.png` (every picture labelled, with the checklist and the warnings the pixels give: a long gun's muzzle on the left) for you to Read before the owner sees them |
| `results [<job> ...] [--no-open]` | every delivered job (or the listed ones) on one local page: six views, score and defects from `delivery/scorecard.json` (`{"score", "spent", "tonetta", "defects"}`, written by the agent after its review), cost, links to each job's 3D preview, GLB and zip, all from one port |
| `serve [--restart\|--stop] [--no-open]` | the ONE local site on port 8765 (`MASTERSMITH_PREVIEW_PORT`): the home page lists every build (score, 3D preview, six views, references, zip) and every job still without a build; `/results` the builds with their six views and defects, `/refs` the reference review; every page, the 3D previews included, carries the same nav bar. `preview`, `refs` and `results` start it when it is not running and restart it when its code changed; nothing else opens a port (owner, 2026-09-29) |
| `preview <job> [--no-open]` | writes `delivery/preview.html` (3D viewer, six views, every part's pictures beside its seed) and opens it on the site: `http://127.0.0.1:8765/<Name>/delivery/preview.html` |
| `package <job>` | README, manifest, zip in delivery/; prints the delivery gate's warnings (LOD0 within the budget x1.05, BaseColor/Normal/ORM present, size within +-10% of the brief, glass present when asked for, mean roughness >= 0.3, UCX hull <= 256 triangles) |
| `status <job>` | what the job has so far: pictures and their review, parts, delivery, score (self or owner), the models used, the money spent and the owner's notes (`decisions.json`) |

`<job>` is `out/<Name>`. Every command prints where it wrote; Read those files.

## Materials

Two passes in `assemble` make the surfaces (both on by default; `--no-projection`, `--no-materials` to compare):
- **Picture projection** (#14): each part's own side picture (the far side takes it at the same place along the
  length, with its own occlusion test) and the approved front view are projected as base colour where the faces look
  at them (a picture that does not line up with its part is skipped; openings stay open), luminance-flattened so the picture's lighting
  does not print; the mesher's texture stays where no picture sees. On a kept-texture part (a whole-object seed) it
  prints only inside the `lettering` boxes (`--projection auto`, the default since 2026-10-02): printed all over a
  seed's own paint it left pale slot patches on the bullpup, white marks round the tank's wheels and washed out the
  Havoc's hull, and was switched off on most builds of 2026-09-29/30. The seed's overall colour is graded to the
  picture's instead: its saturation brought down to the picture's mean chroma (never below half) and per-channel gains
  on its mean chromaticity, its brightness kept, at most +-33% (the Havoc's render moved from 17.5 to 9.6 blue-over-red
  against the reference's 10.7). `--projection full` is the old way, for a seed painted wrong all over (the M4A1's
  Tripo receiver stays slightly olive under the grade; full projection made it neutral) - then check slots, wheels and
  panels for pale patches; `off` none. A dark rough metal also reads warmer than it is under the preview's warm light.
- **Smart materials** (#15): a CC0 surface set per finish (`mastersmith/materials.py`, fetched once from ambientCG
  into `E:/local-models/pbr/`): brushed or parkerised steel, anodised aluminium, black polymer, rubber, powder-coat
  paint - light/dark variation over the planned colour, real roughness structure, a fine bump, and ambient-occlusion
  dirt in cavities and at joins, its wear and grain scaled to the asset's length (a rifle's grime was invisible on a
  14 m aircraft). The per-finish rules the plan should follow are in `mastersmith/skills/materials.md`.
- **A kept texture** (a whole-object seed) keeps its colours and material split; its roughness is lifted to
  0.35 + 0.65r when its mean is under 0.40 (Tripo seeds measured 0.17-0.27: glaze). On a painted or polymer part
  its metallic is capped at 0.12 and roughness floored at 0.30: Tripo mapped the Havoc's canopy hood as chrome and it
  rendered black (2026-09-29); bare metal is a metal zone. Zones override it.
- **Lettering**: `"lettering": [[x0, x1, z0, z1], ...]` on a part (percent boxes off the side grid, around each
  painted word). Inside them the side picture prints at full strength over the mesher's own blurred copy, the far
  side reads the box mirrored back so the word is not reversed, the mesher's embossed letters (Tripo's garbled
  "TNALT") are laid onto the panel, and the seed's normal map gives way to the surface's own normal. Make a box
  generous: Tripo's own letters ran past the picture's word.
- **Canopy rebuild** (`"shell": true` on the glass zone): the seed's canopy glazing is replaced, not cut out. Every
  glass-painted face on the canopy's envelope goes (the panes, their inner skins, the ragged pieces the colour pick
  leaves, the small frame and sill strips between them, and what is left deep inside), then one clean shell (the
  hull of the kept panes, set just inside the frame) is the glass. A painted frame band runs along its smoothed edge,
  and bars run along its long, sharp creases (`MI_<Name>_Frame`, the body's planned colour). A deleted face the shell
  does not cover comes back. Use it when the colour-picked glass reads as shattered: Tripo paints its panes in pale
  and dark patches (the Havoc, 2026-09-29). With an insert under it, `"line": false`: the tub hides the walls.
- **Cockpit lining**: a glass zone lines the walls seen through it from behind (`"line": false` turns it off). A
  mesher's cockpit walls are one skin thick, and through the canopy the eye met the back of the far side's panels,
  lettering mirrored. They get a dark matte inner copy of their own material (`MI_<Name>_Interior`, outside the atlas).
- **Glass** is its own part: alpha 0.3, specular 0.45 (0.8 on grey read opaque), roughness 0.05, no normal map,
  blended, seen from both sides. Lights are `emissive` cores inside glass; glass is never emissive.
- **Preview light** is calibrated so a matte surface renders near its own texture colour: the studio HDRI at 0.8
  with a warm tint (2026-09-29: at 0.45 the Havoc rendered 30% darker and bluer than its texture and the reference).
  Judge a colour against the reference only in these renders.
- **Bake**: the margin grows with the atlas (max(4, size/128) px) and the gutters are dilated, so mipmaps do not bleed
  dark or gloss into the seams. Markings are paint in the texture, never geometry (materials.md).

## Unreal handoff

What the eight Proteus weapons taught (2026-10-01), now in `assemble` and `ms rig`:
- **Units**: the FBX is written in centimetres with no scale on any node (`global_scale` 0.01 cancels the exporter's
  own x100); the GLB and the .blend stay in metres. `report.json`'s `fbx_check` reads the FBX back: its size must be
  the asset's and its root node scale 1 (`node_scale`). A rigged FBX left in metres came into Unreal 5.8's Interchange
  with a x100 root bone: "the weapons are massive and not attached to the ship". Never hand over an FBX whose check
  failed (the gate says so).
- **Sockets**: `SOCKET_<Name>` empties under the mesh in the FBX (Unreal's static-mesh sockets) and in the GLB, listed in
  `report.json` (metres, Blender frame: +X forward, +Y left, +Z up; Unreal's Y points right). A weapon's `Muzzle` is
  measured at its open bore end-on, never the box centre; several bores or tubes give `Muzzle_0..n` (top first) and
  `Muzzle` between them; `--tubes N` when a launcher's tubes are loaded or capped. `Grip` and `Sight` come from a
  part or zone named so.
- **Pivot**: `--origin centre` (the default), `bottom` (a vehicle standing on the ground plane), `mount` (the top
  centre of a pylon weapon's mounting plate, the hardpoint), `grip`, `rear`, `front`, `top`. Say which in the delivery.
- **Rigged weapons**: `ms rig` (bones, clips, centimetres, read back). In the editor: import `SK_<Name>.fbx` as a
  skeletal mesh, then the `A_` clips onto its skeleton; an import that replaces an asset reuses its old skeleton
  (delete the old one first); Play-In-Editor blocks saves; `socket_name` is read-only from Python.
- **Check in the engine** before calling it done: the imported bounds against the brief's size, where the pivot sits on
  its mount, a shot leaving the muzzle socket. A muzzle flash, a flame or a beam is sized to the new muzzle (the
  flamethrower's old VFX came out "too big" on a 5 cm nozzle).

## Sculpting without a mouse

Three tools stand in for an artist's hands; use them after looking, never blind, and never to model a stencil,
a number or a painted vent (paint, materials.md). A seed broken on one side is repaired about the asset's own centre
plane (not world Y=0) by mirroring the intact side with scale -1, UVs kept.
- **`fit`** when a seed's outline is off its picture (a fat magazine, a tapered handguard drawn straight): the
  picture is the target. Check `seed_render.png` after; run `assemble` to see it in place.
- **`brush`** for a local fix you can name: "the grip's heel swells 3 mm too far" -> `--op inflate --at back+0,0,-0.03
  --radius 12 --strength -3`; a soft panel -> `--op flatten`; a rounded edge that should be crisp -> `--op crease --at
  ... --to ...`. Coordinates are metres in the part's frame (centred, X forward, Z up); `--radius`/`--strength` in mm.
- **`sdf`** for parts that ARE geometry: barrel, muzzle device, rails, sights, pins, knobs, magazine bodies. Write
  `parts/<Part>/sdf.py`:
  ```python
  def part(kit, L, W, H):                        # the part's box, metres, centred at the origin, X forward
      tube = kit.cylinder(W / 2, L, axis="x")
      bore = kit.cylinder(kit.mm(5.56) / 2, L * 1.1, axis="x")
      return tube - bore
  ```
  Idioms: a Picatinny rail = `box` minus `box(slot).repeat([mm(10), 0, 0], [n, 1, 1])`; a muzzle brake = `cylinder`
  minus `cylinder(port, axis="y").repeat(...)` minus the bore; a moulded join = `smooth_union(a, b, mm(2))`; a
  rounded body = `rounded_box`; a tapered stock comb = `wedge`; symmetric features = `.mirror("y")`. Sizes come
  from the plan's box (L, W, H) and the mm you can read off the picture. Then `assemble`.

## Testing and code changes

`.venv/Scripts/python.exe -m pytest tests -q` (about 15 s; the tests pin the LLM/no-spend env). Blender scripts
cannot be unit-tested; keep their maths in a pure-numpy module the tests can load (`blender/muzzle.py`,
`restrained_finish.py`), run the rest on a real job and look - on a `ms clone`, never on a job's own delivery. Every
Blender run is `-b --factory-startup -Y` (no user add-ons: BlenderMCP printed errors in every headless run) and
streams into `out/<Name>/<tag>.log` while it runs, with a header and a footer (`finished in N s, exit C`); a log
without the footer is still running - the old log is gone, so it is never last run's traceback. Keep the code style:
one-line docstrings that say why, dated notes for lessons learned. Shell hygiene (the logs of 2026-09-29/10-01:
quoted multi-line heredocs broke about eleven times): write a script or a patch with the file tools and run the file;
use the venv's python (system python has no numpy); open files with `encoding="utf-8"` and write them with
`newline="\n"` (`core.autocrlf` turns CRLF writes into spurious changes); `PYTHONIOENCODING=utf-8` for any python
that prints a model's text.
Blender 5.x (pinned 5.2): colour sockets take four floats (RGBA); `use_auto_smooth` is gone - set `use_smooth` per
polygon and keep hard edges with `harden_normals`; `shade_smooth` needs a selected, active object;
`bpy.ops.mesh.corrective_flip_normals()` fixes a seed with inward faces; build the new objects before deleting the
old; call `me.validate()` after `to_mesh`; the asset's right side is Blender -Y (engine +Y), which matters for sockets.
