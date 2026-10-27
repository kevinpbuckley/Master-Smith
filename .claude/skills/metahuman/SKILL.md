---
name: metahuman
description: Build a humanoid character that becomes an Unreal 5.8 MetaHuman - the A-pose pictures and seed, ms mh-conform (the combined conform mesh with its pose check), the editor steps (import from custom mesh, auto solve, posed DNA, rig, textures, build) by hand or through the Unreal MCP, ms mh-bake (the seed's look on the MetaHuman topology), ms mh-attach (hair, horns, armour on the MetaHuman skeleton), and the engine check. Use when the owner asks for a character, a MetaHuman, or to turn a mesh into one.
---

# A character as a MetaHuman

`PY=.venv/Scripts/python.exe -m mastersmith.ms`. Read AGENTS.md's rules and `mastersmith/skills/character.md` first.
Source: the owner's video of 2026-10-04 ("Turn ANY Character into an Animated Metahuman - Full AI Workflow", UE 5.8:
AI concept -> 3D -> MetaHuman conform -> Blender bake -> accessories -> Unreal) and the editor's own API, read with the
Unreal MCP the same day. The editor is NOT part of a build: everything Master Smith needs offline is in
`mastersmith/metahuman/` (the templates, `template.py`) and the three `mh-` commands; the editor steps are a short list
the owner can do by hand, or the agent through the MCP when it is connected.

## 0. What exists already
`$PY status out/<Name>`; pictures and seeds are never redrawn without asking (AGENTS.md rule 6). A character job is
`--category character --size <height m>` (`ms new`); a model the owner already has (a GLB from elsewhere) goes straight
to §3 with `--source`.

## 1. Pictures (the solver's taste, character.md)
Hero: full body, front, A-pose with the arms about 25 degrees out and the armpits open, legs apart, hands open with the
fingers spread, bald, no lashes, nothing worn above the skin, white background. Say in the prompt what is NOT there.
`$PY picture out/<Name> --out ref/ref_0.png --model nano-pro --prompt "..."`; a back view only when the back differs;
a head close-up (`ref/ref_head.png`) when the face needs detail the full-body seed will not carry. Accessories (hair,
horns, armour) are drawn alone as parts later (`ms part-pictures`), never on the hero. Owner approves on `ms refs`.

## 2. Seed
`$PY grid out/<Name> --side ref/ref_0.png` then `$PY seed out/<Name> --model tripo` ($0.60; `hi3d-mv` $2.10 for the
best). ALWAYS a separate head when the face matters (the AINavigator, 2026-10-05: the body seed's soft face put the
tracked landmarks, the solved mouth and the baked eyes in the wrong places): a head close-up (`ms picture --out
ref/ref_head.png --ref ref/ref_0.png --model nano-pro`: front view, bald, eyes open, mouth closed, nothing worn) meshed
alone into `parts/Head/seed.glb` (Hi3D $2.10 gave a clean face with eyes, lips and ears). Read the six views
(`ms sheet`): fingers, armpits, bald, nothing floating; the head's face on the LEFT panel means it faces -Y already.
State each seed's disposition (rule 10).

## 3. The conform mesh (offline, free)
`$PY mh-conform out/<Name> [--head parts/Head/seed.glb [--head-yaw deg]] [--strip hair,lash] [--height 1.78]`
-> `delivery/metahuman/<Name>_conform.glb` (one mesh, metres, Z up, facing -Y, feet on z=0, transforms applied),
`conform_report.json` and `conform_front.png` / `conform_side.png`: the seed white over the MetaHuman template's red
outline at the same height. With `--head` the head seed is scaled onto the body's skull (its widest row above the
neck), cut below the neck and exported alone as `<Name>_head.glb` (`conform_head_front/side.png` show what the face
tracker will see; `--head-yaw` turns it when its face is not on -Y): the editor conforms HeadAndBody, tracking the
face on the head mesh, and `mh-bake` bakes the head from it. `--extra` joins a mesh into the body instead. Read all. The report's `pose_check` lists what the solver will get wrong: a closed armpit,
a T-pose, legs too close, fused fingers, a suspected hairdo, no head, a height outside 1.35-2.20 m. Fix by redrawing
with `--fixes` and re-seeding, or `--strip` for an object the seed carries as its own mesh; a last-resort local fix is
`ms brush` (AGENTS.md, Sculpting without a mouse). Do not decimate: the same mesh is the baking source.

## 4. In Unreal 5.8 (by hand, or through the MCP when connected)
Prerequisites (once per project): every MetaHuman plugin enabled, "MetaHuman Creator Core Data" optional content
installed, an Epic account signed in (the auto-rig and the texture sources are cloud calls). The MCP's
`MetaHumanSetupService.get_status()` says which are missing.
1. Import `<Name>_conform.glb` into `/Game/<Project>/Characters/<Name>/` with default settings (centimetres, a static mesh).
2. Create a MetaHuman Character asset there (`MH_<Name>`); open it; **Import > From custom mesh > Combined mesh**: drop
   the static mesh; **Auto Solve** (2 minutes on a 4070). Watch the fingers and the armpits: a fused hand is corrected
   in **Manual Solve** by moving or adding key points (ctrl + mouse buttons, hotkeys shown in the panel), then **Solve
   Body**. The MCP: `MetaHumanCharacterService.create_character`; the solve is the subsystem's
   `import_from_custom_mesh` (the face tracked on a render, auto solve), see the end.
3. **Manual Solve > Save Pose**: the POSED DNA (the solved MetaHuman still in the seed's pose) into the character's
   folder. This is the baking target; the next tab re-poses the character into the MetaHuman A-pose
   (`CommitPosedStateAsAPose`), after which a bake no longer lines up. MCP: `ExportPosedDNA`.
4. Head / Body tab: adjust if wanted (eyes bigger, etc.). Materials tab: set the eyes and the teeth (kept MetaHuman's);
   skin tone matters little, the bake replaces the skin. Hair and clothing: skip unless a MetaHuman groom or outfit is
   wanted (`MetaHumanCharacterService.add_wardrobe_item`, slots Hair / Eyebrows / Eyelashes / Beard / Outfits).
5. **Create Full Rig** (`request_auto_rig`, JointsOnly or JointsAndBlendShapes; cloud) then **Download Texture Sources**
   (`request_texture_sources`); then **Build / Assemble** (`build`, Cinematic or Optimized) ->
   `/Game/MetaHumans/<Name>/BP_<Name>` with `Body/SKM_MH_<Name>_BodyMesh`, `Face/SKM_MH_<Name>_FaceMesh`, their
   `Baked/` textures (T_Body_BC 8k, T_Body_N, T_Body_SRMF, T_Head_LOD3_BC/N/SRMF, T_Head_LOD5to7_*), the eye and teeth
   maps, `PHYS_`, the DNA assets. Place `BP_<Name>` in the level: it is the character in MetaHuman's generic skin.
6. Exports back to Master Smith (Content Browser > Asset Actions > Export, FBX, default options), into
   `out/<Name>/delivery/metahuman/in/`: (a) the skeletal mesh generated from the posed DNA (right-click the posed DNA
   asset > Generate Skeletal Mesh) as `<Name>_Posed.fbx`; (b) the built `SKM_MH_<Name>_BodyMesh` and, for a face
   accessory, `SKM_MH_<Name>_FaceMesh`. (The MCP's asset exporter crashed the editor's Python on a skeletal mesh on
   2026-10-04; export by hand or add a guarded `export_fbx` to the MCP.)

## 5. The character's look on the MetaHuman (offline, free)
`$PY mh-bake out/<Name> --posed delivery/metahuman/in/<Name>_Posed.fbx [--resolution 4096] [--skin-color #b5cfe0]
[--far-pass] [--head-source <mesh>]`
-> `T_<Name>_Head_BC.png`, `T_<Name>_Head_N.png`, `T_<Name>_Body_BC.png`, `T_<Name>_Body_N.png`, `bake_report.json`,
`bake_preview_<front|side>.png`. The head bakes from `<Name>_head.glb` when the conform wrote one, and its face is
FITTED onto the MetaHuman's first (`mh_face_fit.py`, 2026-10-06): a stylised head carries its eyes lower and wider than
any MetaHuman (the AINavigator's sat 3 cm under the sockets, 4 cm further out), and baked as placed its painted eyes
landed on the cheeks beside the nose with the mouth on the chin - two pairs of eyes in the comms portrait. The fit
reads the seed's eye corners, lids, brows, nose, mouth corners, chin and ears off its texture and shape, finds the same
points on the posed head by MetaHuman's shared UVs (`metahuman/templates/face_landmarks.json`), and thin-plate warps
the head seed onto them (the cranium, back and neck onto the MetaHuman's nearest surface). Read `face_fit_front.png`
(the fitted seed with the MetaHuman's landmarks as red dots: its painted corners and lips sit on them) and
`bake_report.json` `face_fit` (pairs, moves, `missing`); a misread landmark is given by hand with `--head-landmarks
<json>` (metres, the conform's frame), `--no-face-fit` bakes as placed. In UV space the eyes belong at v 0.62 and the
lip corners at v 0.41 (u 0.42 / 0.58): a head BC with features elsewhere is the wrong fit. A posed mesh that is
the seed's height but stands off it (19 cm behind on a tracked solve) is moved onto the seed's bounds first
(`alignment.shifted_onto_seed`, a rigid ICP: yaw and translation; `--no-align` keeps it). A MetaHuman body stands
up to 3 cm off a slim seed: `--cage 30` covered 91% of the AINavigator's body texels where 12 mm covered half; `--far-pass`
adds a 2.5x-cage pass for the rest (4x printed the seed's shaded far side as dark patches); what both miss takes the
nearest seed point's colour. Image.pixels are sRGB bytes for the bake and the seed texture alike: never convert
(a linear-to-sRGB "fix" turned the suit pale, 2026-10-05). `--skin-color` recolours low-saturation texels to a
planned skin and is rarely wanted: a light-blue skin (155,195,211) is itself near the threshold.
What the AINavigator's nine bakes taught (2026-10-05), all in `mh-bake` now: the posed arms are swung onto the seed's
hands through the posed mesh's own armature (the solve stood them 12 cm forward; `--no-swing-arms` keeps them); with
a head source the body seed loses its own head above the neck (`--body-cut`, default the conform's neck; set it at
the collar top when the seed's neck skin shows above it) and the face mesh's neck below that height is baked from the
BODY source (the two seeds disagreed about where the turtleneck ends); rays see only the source and the target (the
body's neck had sampled the head seed's skin); the POSITION pass is calibrated to the part's bounds (it came back 16x,
so every nearest-point fill had landed on the hands); the neighbour fill stays on the mesh (it had crept across UV
gutters from the hand islands); a hit darker than `dark_is_miss` (0.1) counts as a miss (inside-out hits on the
elbows); the normal map follows the colour map's hit masks and is flat elsewhere. `T_<Name>_<Part>_SRC.png` colours
every texel by the pass that wrote it (green near, yellow far, red nearest point, blue neighbour fill): read it when
a colour is wrong before changing anything. The head is the skin faces on UDIM 1001 (teeth, eyes, lashes, shells keep MetaHuman's
maps); the body is tile 1002 moved onto 0-1 (Blender bakes one tile). Read the previews and the report: `alignment`
(the posed mesh must sit on the seed: a height or centre off means the wrong FBX), `coverage` per map (the UV islands'
share, about 50-70%), and the neck: the seed's head and body textures meet at the MetaHuman's neck seam, and the
video's fix is a hue/saturation match on the seed before baking, or a clone-brush pass in Blender (`ms open`).
In Unreal: import the four PNGs; the `_N` maps with **Flip Green Channel** ticked (Blender bakes OpenGL +Y), sRGB off,
compression Normalmap; then either replace `Body/Baked/T_Body_BC`, `T_Body_N`, `Face/Baked/T_Head_LOD3_BC`, `_N` (LOD0
reads the LOD3 set; the LOD5to7 set is for far LODs), or set them on `MI_Body_Baked` and `MI_Face_Skin_Baked_LOD3`.
A toon or AI-retextured look instead of a bake: export the built body and face meshes, keep only the head skin
material, shift the body UVs by -1, GLB -> Tripo (or `ms retexture`) with "keep original UV": the texture comes back on
MetaHuman's UVs and drops in the same way.

## 6. Accessories (offline, free)
Each accessory is a part with a seed (`ms part-pictures`, `ms mesh`) or a mesh cut off the seed (the video kept the
dryad's branches on the head for a seamless hair join, then sculpted the custom head onto the exported MetaHuman head).
`$PY mh-attach out/<Name> Hair --built delivery/metahuman/in/SKM_MH_<Name>_BodyMesh.fbx --bone head [--offset 0,0,0.01]
[--decimate-to 20000]` -> `SK_<Name>_Hair.fbx` (centimetres, the skeleton named root, no leaf bones), its T_ maps,
`attach_report.json` (bounds, weights, the read-back) and `attach_<front|side>.png` (the accessory, tinted, on the
MetaHuman). `--bone transfer` takes the MetaHuman mesh's own weights (brows, a face plate, a vest over the body);
`--bone spine_05` a chest plate, `hand_r` a gauntlet (`mastersmith/metahuman/template.py` BODY_BONES). The accessory is
expected in the conform's frame (metres, feet at z=0); the built MetaHuman is in the MetaHuman A-pose, so a shoulder
pad modelled on the seed's pose may sit off: read the renders, `--offset`, or model it on the exported body (`ms open`).
In Unreal: import the FBX as a skeletal mesh and pick the MetaHuman body's skeleton in the dialog (`metahuman_base_skel`
or the character's own); for a bake done in Blender tick Flip Green Channel on its normal map; open `BP_<Name>` and
drag the skeletal mesh onto the **Body** component (it follows the skeleton and the animations). The same for a body
accessory with transferred weights.

## Garments: real clothing with volume (offline, free except the picture and the seed)
A painted outfit (the skin texture) has no volume: collars, lapels and hems lie flat on the skin. `GARMENTS.md`
(`mastersmith/blender/garment_fit.py` + `garment_tex.py`) cuts a garment from a seed of the character WEARING the
outfit (nano-pro, ~$0.15; a Hi3D seed, $2.10), fits it onto the built body (collar on the neck/spine bones only,
armpits weighted by an inward ray, boots rigid on the A-pose foot), and `garment_attach.py` exports it as a drop-in
skeletal mesh FBX whose bind pose is the body's to the last digit (`fbx_patch_bones.py`), so it follows the
Blueprint's Body component under leader pose with no further rigging:
```
$PY garment-fit out/<Name> --args parts/Garment/fit_args.json           # GARMENTS.md's options in full
$PY garment-attach out/<Name>
$PY garment-test out/<Name>                                             # 12-pose check; read posetest_report.json
```
In the editor (GARMENTS.md's numbered steps): clear the wardrobe's own Outfit slot (or the body has no torso to show
through it), import the SK_ FBX onto the body's skeleton, a two-sided material on its slots, attach it under Body,
and give the Outfit component `use_bounds_from_leader_pose_component` + `bounds_scale` ~1.5 on the BP TEMPLATE (a
garment with no physics asset computes its bounds as a 36 cm box at the actor's feet otherwise, and every comms
close-up culls it: MissionCommander, PilotAceVex, PilotMockingbird, 2026-10-07).

**Re-fitting a shipped garment without a new seed.** The owner asks for a garment tweak ("scaled down a bit", "a
wider neck", "weight-paint it so it doesn't clip") far more often than a whole new outfit. `ms garment-refit` runs
the fix as ONE Blender process, always in this order (each stage reads what the one before left):
1. **reseat** - the body changed shape (a Creator rebuild) but the garment and its seed did not: each garment
   vertex moves by the body's OWN per-vertex change at its nearest point on the OLD body, smoothed; the collar
   (any neck/head weight) keeps only the vertical part of that change, so a wider neck fills the collar instead of
   pushing it outward. Needs `--reseat-old`/`--reseat-new` (the two built body FBX exports); skipped by default.
2. **shrink** - "scaled down": a vertex's gap to the body proxy is mapped `floor + k*(gap - floor)` (`--shrink-k`
   0.7 keeps 70%), which keeps every vertex's ORDER (a belt stays proud of the shirt it is cinching), held near the
   collar and the boots so neither moves.
3. **collar** - pushed clear of the (possibly rebuilt) face mesh near the neck, radially, fading over the cloth.
4. **lift** - the same push against the body everywhere else (the "weight-paint it so it doesn't clip" rest pokes).
5. **weights** - the garment vertex's weights blended toward the body's own weights at the point under it, where the
   cloth sits close (smoothstep between `--weights-near`/`--weights-far`), skipping a vertex whose weight is already
   blended across two bone families (an armpit, a shoulder cap: exact body weights there gave a 12x stretch, GARMENTS
   v5) and a vertex on the wrong family entirely.
Then `ms garment-attach --run <run>` and `ms garment-test --run <run> --against <previous run>` as usual. The shared
maths (the gap mapping, the collar/band smoothstep, the mixed-band test, old-mesh-to-rebuilt-mesh UV matching for a
reseat whose export gained a vertex) is pure numpy in `garment_refit_core.py` - read it before changing a stage's
formula, and add a test in `tests/test_garment_refit_core.py` rather than only checking a real run's numbers.

**Two lessons from the day's reviews (MissionCommander), both about "the neck", answered two different ways:**
- **Never move the EAR landmarks to change the face.** A Creator landmark move on the ear rim/root landmarks
  crumples the ear (2026-10-06/07, every character so far); if an ear reads wrong, leave the face-fit's landmarks
  alone and move the ear geometry rigidly instead, or accept the preset's ears.
- **The neck's WIDTH comes from the Creator's body constraints, not a landmark move**: `get_body_constraints`,
  find "Neck" / "Neck Base" (cm girth), `.copy()` each constraint, edit the copy, and set the list back as a NEW
  list (editing an item from a loop in place did nothing); only the constraints you actually want to move may be
  ACTIVE (pinning every constraint blocked the change). The widening lands on the FACE MESH's neck and needs a
  rebuild (unrig -> apply -> look -> rebuild). After the rebuild, the garment does not need a new seed or fit: run
  `garment-refit --reseat-old <old BodyMesh.fbx> --reseat-new <new BodyMesh.fbx>` to carry it onto the garment, then
  `--collar-face <new FaceMesh.fbx> --collar-neck-r <wider>` to open the collar back up to the thicker neck (both in
  one `garment-refit` call, `--stages reseat,collar`, or add lift/weights too if the clearance pass finds new pokes).

## Editor safety (the shared Proteus editor; `editor-hang-rules` memory has the full list)
Save discipline above all: **never save a MetaHuman Creator character (`MH_<Name>`) in the same call that changed
it** - it deadlocks the editor waiting on async work (face texture synthesis, groom bindings) only the game thread
advances (`mh_editor.safe_save`: close the edit session, defer the save ~15 s/45 frames, poll `saved_status`).
Likewise **never save a Blueprint right in the call after a capture or a stage probe destroys its actors** - issue
BP changes BEFORE the capture, not after; a save that lands while groom bindings are rebuilding (any character's,
any session's) waits on them and they never finish while the save blocks the game thread. A blocking call (auto-rig,
texture sources, a build) runs 3-10 minutes and can outlive the MCP client's own timeout: the work goes on in the
editor regardless - poll `get_summary` and the build folder, never re-issue the same call on top of itself. Treat
any multi-minute editor step (a build, a batch of captures) as a background run and say so in one line (AGENTS.md
rule 12), and restart the editor only when the owner has said you may
(`E:/az-dev-ops/Proteus/BuildAndLaunchGame.ps1 -SkipBuild`) - never on your own initiative, and never on a
production character this workflow was told not to touch. **If the session's own Unreal MCP tool connection drops
while the editor is fine** (it does; a 57 s call was enough to lose it on 2026-10-07), `ms ue -c "..."` /
`mastersmith.ue_client.run(code)` calls the editor's own MCP endpoint (VibeUE, `execute_python_code`,
`auto_save=False` always) directly over HTTP, no tool reconnection needed.

## Hair
Two routes, pick by what the character needs:
- **A MetaHuman wardrobe groom** (sections 4-5 above): `add_wardrobe_item` from `/MetaHumanCharacter/Optional/Grooms/
  Bindings`, picked and judged by its own THUMBNAIL render, never its name (`WI_Goatee_M_Pointed`'s thumbnail is
  "Goatee_L_Pointed"; `WI_Mustache_S_Horseshoe` built as thin wisps against a thick thumbnail) - export the
  thumbnails once (`export_thumbs.py` pattern) and keep a sheet. Coloured ON THE METAHUMAN CHARACTER, before the
  build (owner rule 2026-10-07: edit the MetaHuman, not the Blueprint): `MetaHumanCharacterService.
  set_wardrobe_item_parameters(c, "Hair", '{"Melanin":.48,"Redness":.53}')` sets the worn item's Creator values
  (`Melanin`, `Redness`, `Whiteness` for grey, `DyeColor` for an out-of-nature colour; Hair also has Ombre and
  Highlights - `get_wardrobe_item_parameters` lists them) and every build carries them; `mh_editor.dye_grooms`
  does that and mirrors the values onto the current build's `MI_WI_*` so it matches without a rebuild. Never dye
  only the built `MI_WI_*`: a rebuild resets them and the Creator never sees them. Measure the dyed hue in the
  render against the portrait's, do not guess from the scalar. Large grooms (scalp hair, full
  beards) render in a capture ONLY while the editor is the foreground window with one realtime perspective viewport
  pointed at the actor (`mh_editor.capture` does this; a capture that shows no hair is stale, re-capture before
  judging). The **HairTop layering recipe** (a second groom binding layered over the first without a rebuild, by
  duplicating the plugin's own binding and retargeting it at the built face mesh, Legacy source kept) handles a
  style no single wardrobe groom covers (a part, a fringe over a buzzed back); see the day's DrHart r4 notes in
  `proteus-metahuman-batch` memory for the exact calls and whether it built clean.
- **A custom groom from curves** (a style no preset nor layering reaches: a specific haircut from the reference,
  fully offline, free): another agent is building this route in `out/_HairTools/` (`hairgen_core.py` - pure numpy,
  `python -m hairgen_core --selftest` outside Blender; `hairgen_blender.py` - finds the scalp on the built face mesh
  from its own geometry, grows Blender Curve hair from a JSON style spec in `presets/`, renders review angles,
  exports Alembic for Unreal's groom importer). Read its own docstrings and `presets/*.json` before touching hair by
  hand; extend its presets or its core maths rather than writing a second curve generator.

## 7. Check in the engine, then deliver
Place `BP_<Name>`, or swap it into the third-person template's character: the size against the brief, the feet on the
floor, nothing poking through the body in idle and in a walk, the accessories following the head and the body, the face
rig working (a Live Link Face app, or `MetaHumanAnimatorService` on a video / audio clip; the markerless body capture
needs the "MetaHuman Animator Markerless Motion Capture" plugin from Fab). Then `delivery/scorecard.json` with the
defects by view, and the delivery message: what is in `delivery/metahuman/` (the conform GLB, the T_ maps, the SK_
accessories), what was spent (pictures and seeds only; the MetaHuman steps are free with an Epic account), and the Unreal
steps that remain if the editor was not connected.

## When the MCP is connected: the whole editor side in eight calls
`MetaHumanCharacterService` (VibeMetaHumans, extended 2026-10-04 for this pipeline; its `metahuman-creator` skill
has the full example). `execute_python_code`, `svc = unreal.MetaHumanCharacterService`:
1. Import the conform GLB: an `AssetImportTask` on `delivery/metahuman/<Name>_conform.glb` into
   `/Game/<Project>/Characters/<Name>/` (Interchange puts the mesh under `.../<Name>_conform/StaticMeshes/`). It
   lands facing +Y, feet on z=0, centimetres: what the solver wants (checked 2026-10-04).
2. `svc.create_character(folder, "MH_<Name>", "")`, then `svc.import_from_custom_mesh(character, static_mesh, head_mesh,
   True, True, 1024)` (`head_mesh` the imported `<Name>_head.glb`, "" for a combined mesh): the face is tracked on a
   front-on render of the head mesh, the body and head solved (1-3 minutes, blocking).
   Read `warnings` (feet off the floor, metres, facing) and `face_tracking` (curves, points, and `render`: the
   front-on picture the tracker saw, in the project's `Saved/VibeMetaHumans/`); a failed tracking leaves the
   archetype face - the seed needs eyes in its sockets and a bald head facing +Y; fix it and run again.
3. The baking target comes from a SCRATCH character solved body-only (`import_from_custom_mesh(..., True, False, 1024)`),
   because the face-tracked solve stands the posed body 19 cm behind the mesh (the AINavigator, 2026-10-05):
   `svc.save_posed_dna(scratch, static_mesh, "", folder, "<job>/delivery/metahuman/in", "<Name>_Posed")`, then
   delete the scratch character. Conform once per fresh character; a second conform after `commit_a_pose` twisted the
   posed DNA. Then `svc.generate_skeletal_mesh_from_dna(folder + "/<Name>_Posed", folder,
   "SKM_<Name>_Posed", "body")` and `svc.export_fbx(that, "<job>/delivery/metahuman/in/<Name>_Posed.fbx")` for
   `ms mh-bake`.
4. The wardrobe lives on the character asset: a NEW character (a re-conform makes one) starts with none, and its build
   ships bald with no brows or lashes (the AINavigator's comms portrait, 2026-10-06). `get_summary(c)["wardrobe_selections"]`
   before every build; add Hair / Eyebrows / Eyelashes again (`add_wardrobe_item`). A rebuild regenerates the
   Blueprint and the material instances: the baked T_ maps go back onto the MIs and the rigid accessories back onto
   the Blueprint afterwards (read their relative transforms off the old Blueprint first).
   Build into the PROJECT's character folder, never the engine default `/Game/MetaHumans` (the owner looked for
   the AINavigator beside Proteus's other MetaHumans and did not find it, 2026-10-06): in Proteus
   `build(c, "Cinematic", "Cinematic", "/Game/Proteus/Characters/MetaHumans/<Name>", "<Name>")` ->
   `<Name>/<Name>/BP_<Name>`, the Creator asset `MH_<Name>` beside the `<Name>` folder, and the T_ maps,
   accessories and conform imports in `<Name>/Textures`, `<Name>/Accessories`, `<Name>/Source` - outside the
   build output so a rebuild cannot touch them.
   `svc.commit_a_pose(character, static_mesh, "")`, eyes and teeth (`set_eye_color`, `set_settings "head"`),
   `request_auto_rig(character, "JointsOnly", True)`, `request_texture_sources(character, True)` (both cloud, Epic
   login), `build(character, "Cinematic", "Cinematic", "/Game/MetaHumans", "")` -> `BP_<Name>`.
5. `svc.export_fbx("/Game/MetaHumans/<Name>/Body/SKM_MH_<Name>_BodyMesh", "<job>/delivery/metahuman/in/SKM_MH_<Name>_BodyMesh.fbx")`
   for `ms mh-attach`.
6. The baked maps back: `svc.import_texture(png, "/Game/MetaHumans/<Name>/Body/Baked", "T_<Name>_Body_N", "normal",
   True)` (the green flip for Blender's OpenGL normals; "color" for BC) and `svc.set_material_texture(MI_Body_Baked,
   "Normal Baked", texture)`; the head onto `MI_Face_Skin_Baked_LOD3` ("Basecolor Baked", "Normal Baked").
7. The accessories. A RIGID piece (a headset, a visor, horns) goes on as a static mesh on the head socket, no skinning:
   import its GLB, then `svc.attach_static_mesh_to_blueprint(BP, "Headset", SM, "Body", "head", rel_loc, rel_rot)`
   with the relative transform in the head bone's frame: the built MetaHuman's head is NOT where the seed's head was
   (the AINavigator's sat 5 cm sideways and 23 cm back, 2026-10-05) - measure the built face mesh's bounds against the
   conform mesh's, add that offset to the accessory's frame, and take it relative to the body's `head` socket
   (`MathLibrary.make_relative_transform`); `unreal.Rotator(roll=, pitch=, yaw=)` by name. The skeletal route
   (`ms mh-attach` -> import onto `metahuman_base_skel` -> `attach_skeletal_mesh_to_blueprint`) came back 90 degrees
   off through Blender's armature round trip: keep it for pieces that must deform (brows, a vest) and check the
   bind pose. Respawn a placed actor after changing the Blueprint.
8. `svc.spawn_in_level(character, location, rotation, False)` or place `BP_<Name>`, and look: a SceneCapture2D
   with `RenderingLibrary.export_render_target` (synchronous; the ImageWriteQueue stopped flushing mid-session, and
   the viewport's high-res screenshot queue stalled). A SceneCapture does NOT drive texture streaming: an actor the
   viewport does not look at renders its 4K maps at the lowest mips, which read as blurry blobs and "eyes on the
   cheeks" (2026-10-05: a whole afternoon was spent re-baking a texture that was right all along). Set the baked
   textures `never_stream`, set `force_mip_streaming` on the actor's components, point the viewport at it, and wait
   about 90 editor ticks (a slate post-tick callback) before capturing. Groom colour lives on the
   character (Hair above); `dye_grooms` also mirrors it onto the build's `MI_WI_*` instances (Cards and Helmet too). `import_texture` over an
   existing asset of the same name keeps the OLD data: delete it first. The skin shader's `Scatter Baked` map stays
   the build's own (`T_Body_Scatter`, `T_Head_Scatter`). Eye colour on a stylised character: the built eye material
   (`MI_EyeL/R_Baked`) reads `Iris Basecolor Baked` / `Sclera Basecolor Baked` and IGNORES its colour multipliers and
   hue scalars; MetaHuman's pink sclera reads brown under the lids against a blue skin (the AINavigator, 2026-10-06).
   Export `T_EyeIris*_BC` / `T_EyeScleraL_BC` (AssetExportTask + TextureExporterPNG), recolour them (the iris's
   luminance onto the seed's iris colour ramp, the sclera desaturated to a cool white), import them as
   `T_<Name>_EyeIrisL/R_BC`, `T_<Name>_EyeSclera_BC` and set them on both eye MIs. A rebuild REPLACES `BP_<Name>`:
   anything already holding its class in memory (a comms speaker profile's `MetaHumanActorClass`) keeps the old class,
   renamed `BP_<Name>_TEMP_..._C` in /Engine/Transient - the old build with no grooms and dead textures - until it
   is set again or the editor restarts.
Still by hand: an Epic login for the cloud steps, and saving (`EditorAssetLibrary.save_asset`, or the MCP's auto-save).
Save the build folder (`save_directory("/Game/MetaHumans/<Name>")`, seconds) BEFORE the character asset, and save the
character only after `svc.end_edit(c)` with `svc.save(c)`: saved while still open for editing after a build, its
SavePackage streamed MetaHuman's preview lighting levels and hung the editor for 20+ minutes with nothing written; the
kill lost the whole session (2026-10-06). After `end_edit` the same save took 0.6 s.
Lower-level when needed: `MetaHumanObjectService.list_functions("MetaHumanCharacterEditorSubsystem")`, the subsystem
in Python (`conform_to_target_meshes`, `get_mesh_data_for_conforming`, `get_preset_body_key_points`), and
`MetaHumanCharacterExportBlueprintLibrary.export_posed_dna / export_geometry / export_dcc`.
