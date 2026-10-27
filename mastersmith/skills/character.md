---
reference_view: full body, facing the camera, standing fully upright (never hunched or crouched) in a relaxed A-pose with the arms held about 25 degrees away from the body and a clear gap under each armpit, hands open with the fingers spread apart, feet a shoulder's width apart, bald head with no eyelashes, no hat, no weapon, no cape
second_view: seen directly from behind
mirror_as_third_view: false
forward_axis: up
origin: bottom
default_tris: 80000
default_size_m: 1.8
front_hint: the face and chest
---
# Characters (humanoids), for Unreal's MetaHuman

Since 2026-10-04 a humanoid character is built FOR Unreal 5.8's "custom mesh to MetaHuman" conform (the owner's
video, "Turn ANY Character into an Animated Metahuman"): `ms` draws and seeds it, prepares the combined mesh the conform
solver takes (`ms mh-conform`), and after Unreal has conformed, rigged and built the MetaHuman, bakes the character's
own look onto the MetaHuman's topology (`ms mh-bake`) and rigs its accessories to the MetaHuman skeleton
(`ms mh-attach`). The recipe is `.claude/skills/metahuman/SKILL.md`. A creature that is not a humanoid (a beholder, a
quadruped) is finished as one static mesh as before; it gets no MetaHuman.

## What the conform solver wants (the input is the whole battle)
The solver conforms the MetaHuman body and head templates to the seed. What the seed gets wrong, the MetaHuman gets wrong
(the acrobat's four fingers read as two; a head with hair conformed into a lumpy skull). So the picture and the seed are
drawn to its taste, not to the game's:
- **One combined mesh**, body and head joined, high-poly kept (the solver takes any vertex count, and the same mesh is the
  baking source later: never decimate it). The head may be seeded alone from a close-up for detail (`--extra` joins it).
- **A-pose**: arms about 25 degrees from vertical (the template's own pose, `mastersmith/metahuman/template.py`), a clear
  gap at the armpits (3 cm or more), legs apart (the template's feet are 26 cm apart), hands open, every finger
  separated. Not a T-pose, never hands on hips or arms crossed. The pose belongs to the animation; the mesh is a neutral
  stance even when the brief says hunched, crouching or fighting.
- **Bald, no eyelashes, nothing on the skin**: hair, eyebrows and lashes come from MetaHuman's grooms or your own hair
  mesh; ears that are not human, horns, branches, a helmet, armour, a backpack, clothes with volume are SEPARATE meshes
  (`ms mh-attach` rigs them afterwards). Skin-tight clothing may stay on the mesh: it becomes the baked texture.
- **Real height** in metres (the MetaHuman sliders run 1.35-2.20 m; stylised proportions - a big head, long legs - are
  fine, the body model bends to them), feet on the floor, Z up, facing -Y in Blender (Unreal's +X after import), rotation
  and scale applied. `ms mh-conform` does the frame; you set the height in the brief.
- Plain white background, even light, no text. One character in frame including the feet. Describe the skin, the face,
  the build and the proportions; name what is NOT on the mesh ("bald", "no eyelashes", "no clothing above the skin").

## Seeding
Hero = the front A-pose view; a back view is worth paying for when the back differs (a tail, a hump, markings). Tripo
from the hero ($0.60) is the first run. 8K textures help the bake on a hero character; 4K is what goes to the engine.
Read the seed's six views: fingers separate? armpits open? the head bald? nothing floating? Then `ms mh-conform` and read
its two overlays (the seed white over the template's red outline) and its report: arm angles, armpit and knee gaps,
finger tips per hand, a hair suspicion. A closed armpit or fused fingers are fixed by redrawing the picture with
`--fixes` and re-seeding (cheap), not by sculpting the mesh (slow, and the solver reads the picture's intent off the mesh).

## Finishing (what `ms` adds after Unreal's part)
- **Textures**: the MetaHuman's own skin is generic. `ms mh-bake` bakes the seed's colour and normal onto the POSED
  MetaHuman mesh Unreal generated from the conformed DNA (same pose, so the rays land): head on UDIM 1001, body on 1002
  moved onto 0-1. Skin must not be glossy; the baked normal is OpenGL (+Y): tick Flip Green Channel on import.
- **Accessories**: each a part (`parts/Hair`, `parts/Horns`, `parts/Armour`) with its own seed or a mesh cut off the
  seed, rigged by `ms mh-attach` to the built MetaHuman's skeleton: a rigid piece 100% on one bone (head for hair and
  horns, spine_05 for a chest plate), a piece over the face or body with the MetaHuman mesh's own weights (`--bone
  transfer`). Exported in centimetres with no leaf bones, read back; dropped onto the MetaHuman Blueprint's Body.
- **Realism check**: skin and cloth matte, eyes visible (MetaHuman's own eyes unless the brief says otherwise), hands
  with fingers, feet flat on the floor, nothing poking through the body under the A-pose and under an idle animation.

## Not a MetaHuman
A non-humanoid creature, a statue, a mannequin: the old path - one static mesh, the height +Z, facing -Y, origin at the
floor between the feet, a capsule-like convex hull - and `ms rig` is not for it (it rigs weapons).
