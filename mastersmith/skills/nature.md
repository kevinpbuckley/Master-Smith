---
reference_view: three-quarter view from slightly above, the whole object visible, resting on the ground or, for a fish, swimming level
second_view: the direct front view
mirror_as_third_view: false
forward_axis: long
origin: bottom
default_tris: 8000
default_size_m: 1.0
front_hint: the head, the open end or the side facing the viewer
---
# Nature (rocks, coral, sponges, seaweed, kelp, grass, shells, fish, driftwood)

One living or natural object, plain white background, its real size in metres as its LONGEST side, whichever way that
runs (a 4.4 m kelp stands taller than it is long). Name the species or rock and its real colours; a fish is drawn
nose to the RIGHT, fins extended, straight swimming pose; a rooted plant upright with its holdfast at the bottom.

A nature brief is finished without any of the machined-part passes, which each damaged a Training Pool pilot
(2026-10-02): no sharpening, no baked bevel, no smart metal or polymer material, no cast-surface grain. `assemble`
switches them off itself and scales the object as one so its longest side is the brief's size. Pivot: `--origin
bottom` for anything resting on the seabed, `--origin centre` for a fish.

Budgets are foliage budgets, because hundreds of instances are placed: grass and seaweed 1-4k triangles, kelp 4-6k,
coral and sponge 2-8k, shells 1-2k, a fish 4-8k, a large rock 8-16k. A Tripo seed is ~150k and split at every UV
seam; `assemble` welds the seams before it decimates (unwelded, the 8k coral came out with 5,600 open edges, 2026-10-03).
Thin leaves and fins are the hard part: Read `preview_views.png` for holes, black patches on blades and fins that have
gone missing before calling it good. Roughness ~0.7 (a fish's wet skin 0.5); nothing metallic.
