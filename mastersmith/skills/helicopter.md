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

Never mix a three-quarter picture with a profile in one seed (both helicopters of the 2026-09-17 batch came back
with a second tail rotor at the nose when a profile was added to the three-quarter shot); an orthographic front,
side and back set for a multi-view seed is fine. Name the real type (AH-64D, UH-60M, Ka-52, AS350) and draw it from
the owner's photos (ask for them; nothing looks one up). Ask for the main rotor blades spread and fully visible, the
tail rotor in frame, plain white background, on the ground.

Glass: an attack helicopter has flat cockpit panels, a utility helicopter a windscreen plus cabin windows; both are
painted surfaces in the vendor mesh (dark, or pale grey with the sky in them: Tripo), picked by colour on the
outside skin and cut out into a real see-through part; holes in the frame get a glass shell. What the glass
shows is modelled: tandem seats, instrument panels with screens, sticks, a tub hiding the shell (200-800 triangles,
matte, built last, `ms cabin` for its box; a cockpit is about 0.9 m wide and 1.3-1.4 m tall inside). A cabin with
open doors is an open frame and gets panes only where a window frame is empty.

Finishing: nose along +X, origin at the bottom centre on the skids or wheels, real length in metres
including the tail (attack 14-18 fuselage with the rotor blades overhanging it, utility ~20, light civil ~11).
Static: rotors stay part of the mesh (spin them in the engine on its local Z (main) and Y (tail)); there is no rig
pipeline in `ms`. Paint ~0.55 roughness.

Realism check: exactly one main rotor and one tail rotor, tail boom straight, the wheels on one ground line, cockpit
glass reads as glass with the cockpit behind it, stub wings and pods only where the photograph has them.
