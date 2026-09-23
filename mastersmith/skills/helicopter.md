---
reference_view: three-quarter front-left view from slightly above, the whole helicopter visible including the tail rotor, skids or wheels on the ground, main rotor blades fully visible, all canopy glass and doors CLOSED with the cockpit seen through the glass
second_view: the direct left-side profile
mirror_as_third_view: false
forward_axis: long
origin: bottom
default_tris: 120000
default_size_m: 17.0
front_hint: the nose with the cockpit windscreen, sensor turret or chin gun
glass_prompt: cockpit windscreen, cockpit windows and cabin windows
---
# Helicopters (attack, utility, transport, civil)

Seed from ONE clean three-quarter picture; never add a second view (both helicopters of the 2026-09-17
batch came back with a second tail rotor at the nose when a profile was added to the three-quarter shot).
Name the real type (AH-64D, UH-60M, Ka-52, AS350) so a photograph is looked up. Ask for the main rotor
blades spread and fully visible, the tail rotor in frame, plain white background, on the ground.

Glass: an attack helicopter has flat cockpit panels, a utility helicopter a windscreen plus cabin windows;
both are solid painted surfaces in the vendor mesh and become the glass slot. A cabin with open doors is
an open frame and gets panes built only where a window frame is empty.

Finishing: nose along +X, origin at the bottom centre on the skids or wheels, real length in metres
including the tail (attack 17, utility 20, light civil 11). No rig: rotors stay static here; spin them in
the engine on the mesh's local Z (main) and Y (tail) if needed, or ask for a rigged version.

Realism check: exactly one main rotor and one tail rotor, tail boom straight, cockpit glass reads as
glass, stub wings and pods only where the photograph has them.
