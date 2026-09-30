---
reference_view: three-quarter front-left view from slightly above, the whole vehicle visible, wheels or tracks on the ground
second_view: the direct left-side profile
mirror_as_third_view: false
forward_axis: long
origin: bottom
default_tris: 120000
default_size_m: 5.0
front_hint: the nose with the headlights, grille, windscreen or cockpit
glass_prompt: the windshield and the side windows of the vehicle
---
# Vehicles (cars, trucks, tanks, aircraft, helicopters, boats)

A three-quarter view tells the vendor about the front, the side and the roof at once; a pure profile
loses the front. Ask for one vehicle, plain white background, no people, no scenery, wheels or tracks
resting on the ground, rotors and wings fully visible. Name the livery and the finish: matte olive drab,
gloss red paint, bare riveted aluminium, rubber tyres, glass canopy.

Real machines have real proportions: name the type (M1 Abrams, AH-64, F-16, Ford F-150) and draw it from the
owner's photos or screenshots of the real thing - ask for them; nothing in `ms` looks one up, and a picture model
drawing from memory invents a generic cousin (the Havoc came back as a generic plane twice, Tonetta). Disambiguate
a name with its source ("Havoc gunship, G-Police"). For fantasy or sci-fi vehicles describe the silhouette in one
sentence before the details.

A multi-view seed takes an orthographic front, side and back; the far side is NOT the side view mirrored for a
vehicle (a fuel door, an exhaust or a hatch is one-sided) unless the vehicle is symmetric and you pass
`ms seed --mirror-far-side`.

Finishing: long axis becomes +X (forward), origin at the bottom centre so it sits on the ground, real
length in metres (a car 4.5 x 1.8 x 1.45 m on 0.65 m wheels 2.7 m apart; a main battle tank 8-10 including the gun;
an attack helicopter 14-18 fuselage, rotors overhanging; a fighter ~15). Wheels, tracks and rotors stay part of the
single static mesh - there is no rig pipeline in `ms`. Collision is a convex hull; large vehicles get a coarser hull.

Glass shows the cab: floor, two seats, a dashboard, a steering wheel, a door card each side (200-800 triangles,
matte 0.7-0.9, nothing through the body, built last). Lights are `emissive` inside `glass` (materials.md).

Realism check: windows read as glass, paint does not look like ceramic (military matte ~0.62, car clearcoat
0.28-0.35), tyres dark and matte, every wheel on the ground and round from the side, the vehicle one vehicle,
not two fused.
