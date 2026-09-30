---
reference_view: perfect side profile, camera level with the weapon, the muzzle pointing to the right of the picture
second_view: seen from the muzzle end looking straight down the barrel, camera far ahead of the muzzle and exactly level with it, strictly orthographic with no perspective and no foreshortening, the barrel a straight line pointing at the camera, the muzzle centred
mirror_as_third_view: true
forward_axis: long
origin: center
default_tris: 60000
default_size_m: 1.0
front_hint: the muzzle end of the barrel
glass_prompt: scope lens glass
---
# Weapons (rifles, pistols, launchers, melee)

The side profile carries almost all of a weapon's identity, so the reference picture is a clean product
shot: one weapon, full length from muzzle to stock, plain white background, no hands, no sling, no
background clutter, no perspective foreshortening. Name the real materials in the caption: anodised
aluminium, carbon fibre, blued steel, polymer, walnut. Say which parts are black and which are coloured.
A real model (M4A1, Glock 17) is drawn from the owner's photo when there is one, never from memory alone.

Seed the whole weapon at once (2026-09-29: one Hi3D v3 multi-view M4A1 scored 6.5, the same model part by part 4.5).
A muzzle view and the mirrored profile give the vendor the cross section it cannot guess from one side, so `hi3d-mv`
(side profile in the left slot, the muzzle view in front, the mirrored profile in right) is the recommendation; a
weapon's far side is its profile mirrored by default (`mirror_as_third_view`), but say so when the right side differs
(an ejection port, a charging handle on one side only).

Describe colours from the photo, part by part: a magazine or grip that shows the same grey as the body
IS grey, never "black steel" by habit. The review holds the model to the caption.

Finishing: the long axis becomes +X (forward), origin at the centre of the body, real length in metres
(a pistol ~0.2 m, a carbine 0.75-0.9 m, a rifle 0.9-1.1 m, a sniper rifle 1.1-1.3 m, a rocket launcher ~1.0 m;
a grip is a 30-35 mm cylinder, a bore 5.6-7.6 mm). Collision is a convex hull; a weapon is one static mesh with
Muzzle and grip sockets - there is no rig pipeline in `ms`.

Materials: satin gunmetal ~0.58 roughness on bare steel, ~0.75 on polymer; barrel, muzzle device, sights and bolt
are `metal` zones on a whole seed (materials.md).

Realism check: barrel, muzzle, sights and receiver on one axis from the front and the top; the muzzle round;
the scope glass reads as glass; metal has a low-to-mid roughness with variation. A wrong outline gets a
targeted fix first (`ms fit`, `ms brush`); a new picture or a new seed only when the shape is unsuitable.
