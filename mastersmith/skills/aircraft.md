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

Never mix a three-quarter picture with a profile in one seed: they are not 90 degrees apart and the vendor answers
with duplicated tails. A single-image seed gets ONE clean three-quarter picture, gear down, on the ground; a
multi-view seed gets an orthographic front, side and back set, which is fine. Name the real type (F-16C, A-10C,
C-130J) and draw it from the owner's photos of the real thing (ask for them; nothing looks one up). Plain white
background, no people, no ground equipment, wings and tail fully in frame, weapons on the pylons only when the brief
names them.

The canopy is the glass: in the vendor mesh it is a painted dark surface; its faces are picked by colour and cut out
into a real see-through part (a `glass` zone, materials.md). Glass that is see-through shows the cockpit, so the
cockpit is modelled when the canopy is: a dark tub that hides the shell's inside, a seat, an instrument panel with
a couple of raised screens, a stick and a HUD frame, a pilot only if the brief has one (200-800 triangles, matte
0.7-0.9, nothing through the hull, built last, `ms cabin` for its box). Sizes: a cockpit is about 0.9 m wide and
1.3-1.4 m tall inside; a canopy 1.5-2.5 m long.

Finishing: nose along +X, origin at the bottom centre between the gear so it sits on the runway, real
length in metres (fighter ~15, airliner 40 to 70). Static: gear, flaps and control surfaces stay as seeded; there is
no rig pipeline in `ms`. Paint ~0.5 roughness.

Realism check: one nose, one tail, wings symmetric (proved from the top), the canopy reads as glass with the cockpit
behind it, panel lines and stencils follow the photograph (as paint), no melted intakes or fused missiles.
