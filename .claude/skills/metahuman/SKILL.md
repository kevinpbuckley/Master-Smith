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
best). A separate head: a `Head` part from the close-up (`ms part-pictures`, `ms mesh --vendor tripo`, $0.60). Read the
six views: fingers, armpits, bald, nothing floating. State the seed's disposition (rule 10).

## 3. The conform mesh (offline, free)
`$PY mh-conform out/<Name> [--extra out/<Name>/parts/Head/seed.glb] [--strip hair,lash] [--height 1.78]`
-> `delivery/metahuman/<Name>_conform.glb` (one mesh, metres, Z up, facing -Y, feet on z=0, transforms applied),
`conform_report.json` and `conform_front.png` / `conform_side.png`: the seed white over the MetaHuman template's red
outline at the same height. Read both. The report's `pose_check` lists what the solver will get wrong: a closed armpit,
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
`$PY mh-bake out/<Name> --posed delivery/metahuman/in/<Name>_Posed.fbx [--resolution 4096]`
-> `T_<Name>_Head_BC.png`, `T_<Name>_Head_N.png`, `T_<Name>_Body_BC.png`, `T_<Name>_Body_N.png`, `bake_report.json`,
`bake_preview_<front|side>.png`. The head is the skin faces on UDIM 1001 (teeth, eyes, lashes, shells keep MetaHuman's
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
2. `svc.create_character(folder, "MH_<Name>", "")`, then `svc.import_from_custom_mesh(character, static_mesh, "",
   True, True, 1024)`: the face is tracked on a front-on render, the body and head solved (1-3 minutes, blocking).
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
4. `svc.commit_a_pose(character, static_mesh, "")`, eyes and teeth (`set_eye_color`, `set_settings "head"`),
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
   with `ImageWriteBlueprintLibrary.export_to_disk` writes PNGs at once (the viewport's high-res screenshot queue
   stalled); grooms are dyed on their `MI_WI_Hair_*` instances (`hairMelanin`, `hairRedness`, `hairDye`), the
   Cards and Helmet instances too.
Still by hand: an Epic login for the cloud steps, and saving (`EditorAssetLibrary.save_asset`, or the MCP's auto-save).
Lower-level when needed: `MetaHumanObjectService.list_functions("MetaHumanCharacterEditorSubsystem")`, the subsystem
in Python (`conform_to_target_meshes`, `get_mesh_data_for_conforming`, `get_preset_body_key_points`), and
`MetaHumanCharacterExportBlueprintLibrary.export_posed_dna / export_geometry / export_dcc`.
