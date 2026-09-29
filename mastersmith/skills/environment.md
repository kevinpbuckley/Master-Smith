---
reference_view: three-quarter view from slightly above, the whole structure visible, on flat ground
second_view: the direct front elevation
mirror_as_third_view: false
forward_axis: long
origin: bottom
default_tris: 80000
default_size_m: 4.0
front_hint: the main entrance or facade
glass_prompt: window glass
---
# Environment pieces (buildings, walls, bunkers, ruins, rocks, kit pieces)

One structure, plain white background, three-quarter view so the roof and two facades show. Name the
construction materials (sandbags, concrete, corrugated steel, stone, timber) and the footprint in
metres. A single building or ruin seeds well; a whole street does not - split it into pieces and build
each as its own asset. For traversable interiors, keep authored scale, pivots and passage openings: the generic
finish recentres, scales and generates convex collision, so handle such a mesh in the engine when those would break
level placement.

Finishing: origin at the bottom centre on the ground plane, longest horizontal axis along +X, real
footprint in metres. Collision is a convex hull, which is coarse for hollow buildings - use complex-as-simple
collision in the engine to walk inside. A window pane gets an interior wall or floor set a little way back, so the
glass has depth.

Realism check: stone and concrete matte (0.80-0.95; ~0.8 overall), windows read as openings or glass, markings are
paint, and the structure sits flat.
