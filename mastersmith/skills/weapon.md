---
reference_view: perfect left-side profile, camera level with the weapon, muzzle pointing right
second_view: seen from the muzzle end looking straight down the barrel, camera far ahead of the muzzle and exactly level with it, strictly orthographic with no perspective and no foreshortening, the barrel a straight line pointing at the camera, the muzzle centred
mirror_as_third_view: true
forward_axis: long
origin: center
default_tris: 60000
default_size_m: 1.0
front_hint: the muzzle end of the barrel
glass_prompt: scope lens glass
reproject: true
repair_cylinders: [{"phrase": "the thin round metal barrel tube sticking out at the front of the gun", "current": "dark metal"}]
part_seeds: [{"phrase": "the detachable magazine of the gun", "name": "Magazine"}, {"phrase": "the optic or scope mounted on top of the gun", "name": "Optic"}]
material_families: [{"phrase": "the steel slide, barrel, receiver and muzzle of the gun", "current": "dark metal", "metal": true, "finish": "satin", "roughness": 0.68}, {"phrase": "the black plastic pistol grip, buttstock and handguard of the rifle", "current": "black polymer", "metal": false, "finish": "matte"}, {"phrase": "the rubber grip panels of the gun", "current": "black rubber", "metal": false, "finish": "matte", "roughness": 0.9}, {"phrase": "the forged iron or steel blade or axe head", "current": "dark metal", "metal": true, "finish": "satin", "roughness": 0.72, "only_if": ["sword", "axe", "blade", "knife", "dagger", "katana", "machete", "spear", "halberd", "mace", "hammer"]}]
---
# Weapons (rifles, pistols, launchers, melee)

The side profile carries almost all of a weapon's identity, so the reference picture is a clean product
shot: one weapon, full length from muzzle to stock, plain white background, no hands, no sling, no
background clutter, no perspective foreshortening. Name the real materials in the caption: anodised
aluminium, carbon fibre, blued steel, polymer, walnut. Say which parts are black and which are coloured.

Seed with detailed geometry and HD textures: standard geometry melts scopes, bipods and iron sights
into soft plastic. A second view down the barrel and a mirrored profile give the vendor the cross
section it cannot guess from one side.

Finishing: the long axis becomes +X (forward), origin at the centre of the body, real length in metres
(a rifle 1.0 to 1.3 m, a pistol 0.2 m, a rocket launcher 1.0 m). Collision is a convex hull; a weapon
never needs quads or a skeleton unless the customer asks for a rigged reload.

Realism check: the scope glass should read as glass, metal parts should have a low-to-mid roughness
with variation, and the silhouette must match the picture - a wrong silhouette means a new picture,
not a Blender repair.
