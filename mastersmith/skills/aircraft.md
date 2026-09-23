---
reference_view: three-quarter front-left view from slightly above, the whole aircraft visible, landing gear down, resting on the ground, the canopy CLOSED with the cockpit seen through the glass
second_view: the direct left-side profile
mirror_as_third_view: false
forward_axis: long
origin: bottom
default_tris: 120000
default_size_m: 15.0
front_hint: the nose with the radome, cockpit canopy and air intakes
glass_prompt: cockpit canopy glass and cockpit windows
---
# Aircraft (fighters, bombers, transports, drones, airliners)

Seed from ONE clean three-quarter picture with the gear down and the aircraft on the ground: a second view
is not added for aircraft (a three-quarter picture and a profile are not 90 degrees apart and the vendor
answers the mismatch with duplicated tails). Name the real type (F-16C, A-10C, C-130J) so a photograph is
looked up and the proportions come from the real thing. Ask for plain white background, no people, no
ground equipment, wings and tail fully in frame, weapons on the pylons only when the brief names them.

The canopy is the glass: on a fighter it is one solid painted surface in the vendor mesh and becomes the
glass slot (dark smoked glass is correct for a modern canopy); an open cockpit gets a pane built into the
frame. Cockpit interiors are not modelled - a game asset shows a tinted canopy, not a pilot's seat.

Finishing: nose along +X, origin at the bottom centre between the gear so it sits on the runway, real
length in metres (fighter 15, attack helicopter 17, airliner 40 to 70). No rig: gear, flaps and control
surfaces stay static in this pipeline; animate in the engine.

Realism check: one nose, one tail, wings symmetric, the canopy reads as glass, panel lines and stencils
follow the photograph, no melted intakes or fused missiles.
