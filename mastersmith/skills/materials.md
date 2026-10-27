---
name: materials
---

# Materials: what each finish is, and what to write in the plan

A real hard-surface object is never one material. Give every part a `finish`, and every area of a part that is a
different material a `zone`. The assembler turns the finish into a surface: a CC0 set for its structure, the
planned colour, wear on the edges, dirt in the cavities. Numbers here are what the plan should carry. Albedo stays
inside 0.03-0.90 (sRGB ~#303030 to #f2f2f2 for a grey); roughness inside 0.3-0.92 unless the row says otherwise.

| finish | when | color | metal | roughness | notes |
|---|---|---|---|---|---|
| `metal` (bare steel, dark) | barrels, bolts, muzzle devices, pins, springs, rails on military weapons | #1e1e1e–#3a3a3a (parkerised / blued), near-neutral | true | 0.45–0.6 (satin gunmetal ~0.58) | parkerised set: matte, fine grain, worn edges lighter and smoother |
| `metal` (bare steel, light) | machined parts, stainless, tools, exposed slides | #6a6a6a–#9a9a9a | true | 0.3–0.4 | brushed set; the brushing runs along the part's length |
| `metal` + "aluminium"/"anodised" in `what` | handguards, receivers, rail mounts, optics bodies | #2a2a2a–#555555 | true | 0.35–0.45 | anodised look: brushed aluminium set, slightly satin |
| `metal` chrome | only where the real part is polished (trim, a chromed bumper) | #b0b0b0–#d0d0d0 | true | 0.10–0.25 | never a default: chrome by habit reads as a toy |
| `painted` military matte | vehicle hulls, military aircraft and helicopters, olive / tan / grey camouflage, powder-coated furniture | the paint's colour | false | ~0.62 (0.55–0.7) | a Humvee at 0.35 read glossy plastic (Tonetta, 2026-09); aircraft paint ~0.5, helicopter ~0.55 |
| `painted` gloss | car clearcoat, civil aircraft livery | the paint's colour | false | 0.28–0.35 | the only glossy paint; never on military kit |
| `polymer` | stocks, grips, magazines, handguard shells, trigger guards | #3a3a3a–#6a6a6a (grey/black) or the picture's colour | false | 0.55–0.75 (dielectric weapon parts ~0.75) | moulded grain; satin, never shiny |
| `rubber` | butt pads, grip panels, tyres, cable boots | #141414–#262626 | false | 0.85–0.95 | dead matte, stippled; does not polish on edges |
| `glass` | lenses, windows, canopies, lamp covers | the tint (table below) | false | 0.05–0.15 | a zone cut out as its own see-through part; no wear, no normal map |
| `wood` | furniture on old rifles, crates, handles | the picture's colour | false | 0.65–0.85 | no CC0 set wired yet (ambientCG has free wood sets): the mesher's texture is kept |
| `fabric` | slings, seats, canvas covers | the picture's colour | false | 0.75–0.95 | no CC0 set wired yet |
| `concrete` / stone | bunkers, walls, bases | the picture's colour | false | 0.80–0.95 | environment pieces ~0.8 overall |
| `emissive` | lamps, screens, engine glow, indicators | the light's colour | false | — | a zone with `"strength"` 6–12 (1–2 reads as a bright surface, not a light); baked into T_<Name>_E |

By category, when nothing else is known: weapon satin gunmetal ~0.58 with dielectric parts ~0.75; military vehicle
paint ~0.62; aircraft paint ~0.5; helicopter ~0.55; prop ~0.7; environment ~0.8.

## Glass
A glass zone is not painted dark: its faces are picked out of the seed and cut into a real see-through part (below).
Glass is alpha ~0.3 (below 0.2 the pane vanishes, above 0.7 it is paint), specular ~0.45 (at 0.8 on a grey tint the
panes mirrored the backdrop and read as opaque light grey, Anvil 2026-09), roughness 0.05, no normal or bump map,
blended, seen from both sides. Never set alpha on the seed's own material (the whole asset goes transparent).

| glass | tint (linear) | alpha | roughness |
|---|---|---|---|
| cockpit canopy, windshield | 0.02, 0.03, 0.04 | 0.30 | 0.05 |
| tinted or armoured glass | 0.01, 0.02, 0.02 | 0.55 | 0.08 |
| lamp glass, lantern chimney | 0.06, 0.05, 0.04 | 0.25 | 0.10 |
| frosted pane | the tint | 0.60 | 0.45 |
| visor, goggles | 0.05, 0.03, 0.01 | 0.45 | 0.05 |

A glass zone whose material sets `"alpha"` gets a pane of its own from that table: its colour as the tint, its alpha
(clamped 0.2-0.7) and its roughness (the Kestrel's canopy: `#060808`, 0.62, 0.08 - dark enough not to see inside,
owner 2026-10-04); without it every pane is the canopy default. An opaque island the pick encloses on every side
(a highlight painted across a pane) is taken as glass (`enclosed` in the report).

Whatever the glass shows has to exist (a canopy over an empty shell shows the hull's back faces): see the cockpit
contents in the aircraft, helicopter and vehicle skills. A lamp is an emissive core inside a glass shell; the glass is
never the emissive part.

## Markings are paint, not geometry
Does it change the silhouette or cast a shadow? Two noes: paint. Stencils, numbers, stripes, roundels and painted
vents are never modelled. A swappable decal is one flat quad named `Decal_<what>`, offset at most 1 mm from the
surface. A marking on a whole-object seed lives in its kept texture; recolour a region through a zone, never by
painting pixels on the atlas's irregular UV islands. A painted word that the mesher blurred, mirrored or embossed
(Tripo's POLICE came back as raised "TNALT") gets a `lettering` box in the plan (AGENTS.md): the picture's word is
printed whole on both sides, reading the right way round, over a flattened panel.

## The seed's own texture (a whole-object seed keeps it)
The one-part plan of `ms seed` keeps the vendor's texture (`keep_texture`): its camouflage, markings and its own
material split stay; zones take their planned materials over it. The assembler still corrects what vendors get wrong:
a kept texture whose mean roughness is under 0.40 is lifted to 0.35 + 0.65r (Tripo seeds measured 0.17–0.27: glaze);
wear and grain scale with the asset's length (a rifle's grime was invisible on a 14 m aircraft); the bake margin
grows with the atlas (max(4, size/128) px) and the gutters are dilated so mipmaps do not bleed dark or gloss into the
seams.

## Rules

1. **Metal true only for bare metal.** A painted truck panel is `painted`; a black polymer receiver is `polymer`.
   Metal true on a coated part reads as chrome or graphite.
2. **Zones carry the second material.** A polymer stock with a rubber butt pad: the stock is `polymer`, the pad a
   zone with `finish: rubber`. A scope: the body `metal` (aluminium), the lens a `glass` zone. Bare-steel controls
   (bolt handle, selector, pins) on a polymer body are `metal` zones. On a whole-object seed every region that is not
   the seed's texture is a zone: barrel and sights `metal`, canopy `glass`, tyres `rubber`, lights `emissive`.
3. **Colours come from the picture** (`ms plan` samples them per part); the finish decides how they render. Do not
   lighten a black steel part to make it "read": the material pass lifts metals to a real reflectance itself.
4. **Weapons**: barrel, muzzle device, bolt, charging handle, selector, trigger, sights, rails = `metal` (dark);
   receiver/stock/grip/handguard/magazine = `polymer` on modern rifles, `metal` (dark) on stamped-steel ones,
   `wood` on old ones; grip panels and pads = `rubber`; optics glass = `glass`.
5. **Vehicles**: body shell, doors, hood, bumpers = `painted` (military matte, or gloss for a car), trim and grilles =
   `metal`, tyres = `rubber` zones, windows = `glass` zones, seats = `fabric`, head and tail lights = `emissive` inside
   `glass`.
6. **Check the six views**: steel must look dark and reflective with lighter worn edges; rubber flat; polymer
   satin with visible grain; paint smooth with dirt in the seams. One graphite-looking material everywhere is a
   fail, and so is a metal that looks like chrome. Name "bumpy relief" (fine wrinkles or hammered relief on a glossy
   surface) and a painted hull under 0.35 mean roughness (reads plastic or glaze) as defects.
