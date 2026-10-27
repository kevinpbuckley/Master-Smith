# Reviewer rubric: Proteus Mk II, the exact-geometry build (hard rounds, 2026-10-25)

You are one of three independent reviewers of one build round of `out/ProteusMkIIHard`. The truth is the hero
picture `ref/ref_0.png` (the owner directed it: a mean fighting ship that "could fly and move through water", NOT an
airplane) and the derived views `ref/ref_side.png`, `ref/ref_front.png`, `ref/ref_back.png`, `ref/ref_top.png`.
The owner's verdict on the previous build (the mesher's seed, `out/ProteusMkII/delivery`, kept as the anchor):
"the ship looks like garbage, soft clay and the glass is horrible". Earlier asks, all still standing: razor bare-metal
edges on the rim and the fin, flat crisp panels, no dome, the fin built into the hull with a hinge LINE and only its
trailing third swinging, a wide square stern, the rim out past the pods, "it shouldn't add anything" the hero does
not show. Look at EVERY picture with the Read tool before scoring: `delivery/preview_views.png` (six sides),
`preview_iso.png`, `preview_front.png`, `preview_side.png`, `preview_detail_front.png`, `preview_detail_rear.png`,
any `delivery/closeups/*.png` the modeler made, and `delivery/report.json`. Nobody's history, no leniency, and no
credit for effort: score what the pictures show.

Score each criterion 0-10. Weights in brackets; overall = weighted mean, then the gate cap.
- `silhouette` (25): the hero's proportions from every side: one wide flat wedge hull, sharp pointed bow, the thin
  blade rim running right round the planform, a wide square stern, the chined upper hull with its flat deck, the
  swept fin on the stern centreline, the belly a shallow V with the two pods tucked under the rim. Length:width:height
  of the views 1 : 0.54 : 0.25.
- `cockpit` (20): one clean faceted greenhouse canopy of flat glass panes with brass mullions on every crease, a sill
  bar where it meets the hull, flush with the deck at its rear, clear see-through glass with the single-pilot interior
  (seat, dash, consoles) visible through it from the front and the iso view. No ragged cut edges, no dark shards, no
  gap between the glass and the hull, no second skin inside.
- `pods` (10): two ducted engine pods under the rear hull inboard of the rim on short pylons, open intake with a lip,
  tapered outlet; joined to the hull, not floating.
- `control_surfaces` (10): the fin a solid swept plate with a razor leading edge and a visible hinge line for its
  trailing-third rudder; the two stern flap stubs on the rim line; nothing else added.
- `surface_detail` (15): crisp hard-surface edges and flat panels everywhere (chines, deck edges, rim, fin): NOT
  clay, NOT melted, NOT lumpy. Panel lines, markings and trim read from the hero's livery where they belong (they are
  paint, baked from the seed; blurred or displaced paint, a smear across an edge, or a bald patch is a defect).
- `materials` (20): cream and oxblood paint matte and weathered as in the hero, bare metal on the rim's edge and the
  fin's leading edge, brass mullions, glass clear and see-through, the pods' dark steel; nothing plastic-looking or
  uniformly grey; nothing chrome.

An 8 means "the owner would put this in the game as it is". 9-10 only when every view matches the hero closely.
Anchors: the owner's "garbage, soft clay" round 16 (`out/ProteusMkII/rounds/16/preview_views.png`,
`out/ProteusMkII/delivery/rig/captures/r16/iso.png`) is a 4; a crisp hull with the right lines but bald, misplaced
or smeared paint is a 6; the hero's lines, crisp, with its livery in place and a clean glass canopy is an 8.

Gates (any failure caps the overall at 6):
1. Size: `report.json` `dimensions_m` length within 3% of 4.079 m, width within 5% of 2.192 m, height 0.95-1.10 m.
2. Budget: LOD0 at most 120,000 triangles; `report.json` `gate.ok` true.
3. Glass: the canopy is a real see-through part (the cockpit visible through it from the front and the iso view);
   no background shows through the hull anywhere.
4. Integrity: no floating pieces, nothing poking through another part, the canopy and frame seated on the hull, pods
   and fin joined to the hull (`report.json` `islands`, and your own eyes in the six views).
5. Maps: BaseColor, Normal and ORM baked and present; `roughness_mean` at least 0.3.

Answer with the structured output you are asked for: the six scores, the five gates with a note each, the overall
(weighted mean, capped at 6 when a gate fails), a two-sentence summary, and `top_changes`: the five changes that
would raise the score most, each naming a view, a part, what is wrong, what it should be, and the gain you expect.
Be concrete and geometric ("the rim's edge is 3 cm thick in the front view; it should taper to under 1 cm", "the
canopy's rear pane stands 8 cm proud of the deck"), because the modeler is an SDF script and can only act on numbers.
