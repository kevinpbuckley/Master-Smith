---
reference_view: full body, facing the camera, standing fully upright (never hunched or crouched) in a relaxed A-pose with arms slightly away from the body, feet apart
second_view: seen directly from behind
mirror_as_third_view: false
forward_axis: up
origin: bottom
default_tris: 80000
default_size_m: 1.8
front_hint: the face and chest
---
# Characters and creatures

Outside Master Smith's hard-surface scope: `ms` seeds and finishes a character as one static mesh, with no rig
pipeline. One character, whole body in frame including the feet, plain white background, neutral A-pose, no weapon
held across the body, no cape hiding the silhouette, hands open. Draw the figure standing upright in that A-pose
even when the brief says hunched or crouching: the pose belongs to the animation (rigged in the engine), not the
mesh. Describe the outfit layer by layer and name the materials (leather, steel plate, denim, fur). Give the
character's height in metres.

Seed from the front view; a back view is only worth paying for when the outfit is very different behind
(a backpack, wings, a cape). The vendor mesh comes back as one fused shell with no skeleton.

Finishing: the height becomes +Z (up), the character faces -Y in Blender which exports as facing the
engine's forward, origin at the floor between the feet, real height in metres. Collision is a capsule-like
convex hull. Realism check: skin and cloth must not look glossy, eyes should be visible, hands should
have fingers, feet should be flat on the floor.
