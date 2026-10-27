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

**Wind masks** (2026-10-03): every nature asset carries them in its vertex colour (FBX only - a glTF viewer would
multiply them into the base colour): R the distance ALONG the surface from the holdfast (0 root, 1 farthest tip),
G blade flutter on the thin parts, B a random phase per blade. The engine's plant material bends by R (a slow wave
running up the stalk) and flaps each blade by G along its own normal at phase B. Height alone made a swept kelp's level
blades move as one rigid block, and UE's SimpleGrassWind moves a vertex a few centimetres - visible on a grass card,
nothing on a 2-8 m kelp (owner: "a bit too rigid", then "not moving"). `report.json` `wind_masks` gives the blade count;
check a plant by rendering the attribute (`WindMask`) as colour: black holdfast, grading along the stipe, each blade
its own hue. True Pivot Painter 2 needs the blades cut apart - only worth it for a hero plant.

**Registration**: a lattice (a sea fan, kelp, branching coral) is compared by its envelope, so it registers upright
(the sea fan was rolled onto its side at IoU 0.20). `ms seed` tries the four upright turns only; a seed that comes back
turned in its own frame (the workboat sat 35 degrees askew) needs `ms register <job> Body` - the default `--from
quarter` sweeps the yaw along the long axis. Read `preview_views.png` from the top for it.

**In a level**: read as game dressing, not specimens - corals and sponges at 1.5-3x real size, shells 1.3-2x, kelp at
its height; plants and shells never collide, rocks keep their convex hull, an arch or a hull you can pass through
takes complex-as-simple collision. Set every object down on the ground itself (a trace against the landscape only),
sunk by a share of its height (rocks ~18%, wrecks ~15%, plants 3-5%) and tilted to the slope by a share (rocks follow
it, plants stay nearly upright); a model fitted into another model's old placement floated where that one had stood on
something else. Meadows are clumps (three tufts within half a metre, clumps ~1.6 m apart), not an even sprinkle.
