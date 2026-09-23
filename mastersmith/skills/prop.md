---
reference_view: three-quarter view from slightly above, the whole object visible, resting on the ground
second_view: the direct front view
mirror_as_third_view: false
forward_axis: long
origin: bottom
default_tris: 30000
default_size_m: 1.0
front_hint: the side with the controls, opening or label
---
# Props (crates, barrels, furniture, tools, containers, machinery, plants)

One object, plain white background, three-quarter view so the top and two sides show, real materials
named in the caption (weathered oak, rusted steel, painted plastic, canvas). Say the real size in metres;
a wooden crate is 0.6, an oil drum 0.9, a workbench 1.8.

A simple box or cylinder still comes back better textured from the vendor than from a procedural
material, so props seed like everything else. Multiview is rarely worth paying for on a prop unless one
side differs a lot (a control panel, a poster on one face).

Finishing: origin at the bottom centre so the prop sits on the floor, longest horizontal axis along +X,
real size in metres, convex hull collision. Realism check: wood should read as wood grain not lacquer,
metal edges may show wear, and the object should be one object, not a cluster.
