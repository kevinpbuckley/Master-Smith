# Reviewer rubric: Proteus Mk II against the sheet

You are one of three independent reviewers of one build round. You get this rubric, the `compare_<view>.png`
pictures (the sheet's panel on the left, the delivery's render on the right), `contact.png`, `report.json` and
`package` gate output. Look at every picture with the Read tool before scoring. Nobody's history, no leniency.

Score each criterion 0-10. Weights in brackets; overall = weighted mean, then the gate cap.
- `silhouette` (25): proportions against the six orthographic panels: a rounded manta/arrowhead planform, pointed low
  bow, the cream deck a narrow rounded spine, oxblood wing lip, the belly rounded up into it, the tall swept fin.
- `cockpit` (20): one continuous wraparound bubble canopy with brass mullions, clear glass, and the single-pilot
  interior visible through it (seat, dashboard, HOTAS: throttle on the pilot's LEFT console, stick on the RIGHT).
- `pods` (15): two ducted turbine pods tucked up under the rear hull in nacelle recesses, cream/oxblood banded, open
  intake with a fan, rear outlet. Pods hanging off slabs or bars in mid-air score 3 at most.
- `control_surfaces` (10): solid upper and lower rudders, left and right planes, rear elevator; no exhaust openings
  on any fin; a fin with no thickness or no paint scores 3 at most.
- `surface_detail` (15): panel seams, rivets, brass trim strips, the steel roof dome with its brass ring, the three
  weapon mounts under the forward hull, amber running lights. Crisp but not razor; not melted or gooey.
- `materials` (15): cream and oxblood paint matte and weathered, brass and steel reflective, glass clear and
  see-through, nothing plastic-looking or uniformly grey; the colours of the sheet.

An 8 means "a game artist would accept this as a faithful first pass of the sheet". 9-10 only when every view
matches the sheet closely. Anchor: the code-only cloud build of 2026-10-09 is a 5 (flat wedge, bare cylinder pods,
window canopy); the 2026-10-08 hand-built delivery is a 6 (right hull, flat plate fin, pods on slabs, wire canopy frame).

Gates (any failure caps the overall at 6):
1. Size: `report.json` length and width within 3% of 4.079 x 3.917 m; height between 1.45 and 1.75 m.
2. Budget: LOD0 at most 120,000 triangles; the `ms package` gate reports no failure.
3. Glass: the canopy is a real see-through part (the cockpit is visible through it from the front and the iso view);
   no background shows through the hull anywhere.
4. Integrity: no floating pieces, nothing poking through another part, pods and fin joined to the hull
   (`report.json` `islands`, and your own eyes in the six views).
5. Maps: BaseColor, Normal and ORM baked and present; mean roughness at least 0.3.

Answer with ONLY this JSON (the keys are read by `cloud/median_review.py`):
```json
{"scores": {"silhouette": 0, "cockpit": 0, "pods": 0, "control_surfaces": 0, "surface_detail": 0, "materials": 0},
 "gates": {"1": {"pass": true, "note": ""}, "2": {"pass": true, "note": ""}, "3": {"pass": true, "note": ""},
           "4": {"pass": true, "note": ""}, "5": {"pass": true, "note": ""}},
 "overall": 0.0,
 "summary": "two sentences",
 "top_changes": [{"view": "port", "part": "fin", "wrong": "...", "should_be": "...", "gain": 0.5}]}
```
`top_changes`: the five changes that would raise the score most, each naming a view, a part, what is wrong, what it
should be, and the gain you expect.
