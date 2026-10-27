# The seed sheet: what the pictures must be before anything is meshed

Written 2026-10-23 after the Proteus Mk II cloud test. Three seed models (Hi3D v3 multi-view, Tripo P2, Meshy 7.1) were
each given views cut from one generated concept sheet, and every build plateaued at 5-6.4 of 10. The sheet was the
reason as much as the models: its hero showed a broad round-bowed saucer, its top view a pointed arrowhead, and the
reviewers scored every render against the panel the mesher had not seen. The owner's rule since: **one picture is the
truth (the hero), every other view is derived from it and checked against it, and nothing is seeded until they agree.**

## The rules

1. **One truth.** The owner names the picture that is the design (`ref/ref_0.png`, the hero). Fix what is wrong in it
   FIRST (`ms picture --redraw --ref ref/ref_0.png --prompt "Edit this picture ... change ONLY ..."`), with the owner's
   words for what is wrong (the Mk II: "the windshield is messed up" = an extra pane jutting out of the rim on the left).
   Never fix a defect of the hero in a derived view instead.
2. **Derived, not drawn.** Every standard view comes from the hero in ONE call (`ms views --from ref/ref_0.png --which
   side,front,back,top`): one call keeps the object the same in every panel. A view drawn alone from a prompt is a
   different ship. `--fixes` names what the sheet must show that the hero hides (where the pods hang, how wide the
   hull is) in the hero's own terms ("exactly as the hero shows").
3. **Full size, one object per picture.** Never cut panels out of one sheet of eight: a 1536 px sheet gives 500 px
   panels, and the Mk II's pods, mounts and rivets were a few pixels each by the time a mesher saw them. Each view is
   its own picture (Nano Banana Pro returns ~1376 x 768 for a 16:9 hero, ~1024 per panel on a four-panel sheet).
   No labels, arrows, callouts or text inside a panel; a plain background.
4. **The hero's camera shows the planform.** A low three-quarter camera hides the outline the meshers get wrong
   (every single-image seed of the Mk II came back 25-55% too narrow). Ask for the camera 30-40 degrees above the
   object so the top of the hull reads; a weapon's hero is its side, level.
5. **Everything that exists is in every view where it would show.** Pods, fins, mounts, dome: the Mk II top view hid
   the pods and the front view hung them off the wing tips while the hero had them under the rear hull. Say it in
   `--fixes`; check it with your eyes on `ref_sheet.png`.
6. **The views must agree, by the numbers.** `ms refs <job> --check` (and `ms seed`, which refuses to spend on views
   that fail, `--unchecked` overrides) reads each orthographic view's extents and closes the three proportions:
   side gives H/L, front and back H/W, top W/L, and H/L must equal H/W x W/L within 12%. Front and back must read the
   same H/W; every view's chromaticity must be the hero's. `ref/consistency.json` keeps the readings and the
   L:W:H they imply. A failed check means one panel is of a different object: redraw THAT panel (`ms view --which
   <view> --from ref/ref_0.png --fixes "..."`), never the hero.
7. **The forward end points RIGHT in the side view** (the grid and the plan read it so). A side panel drawn bow-left is
   mirrored (`ms views --mirror`, or by hand; keep the drawn one in `ref/unused/`): for a symmetric vehicle the far
   side is the near side mirrored (`ms seed --mirror-far-side`).
8. **Give the planform to the mesher.** No seed model takes a top view except Meshy 7.1 multi-view (any four
   pictures): when the planform is the risk, send it `hero, side, front, top`. Hi3D multi-view takes left, front and
   back; its width comes from the front view, so the front view's width must be right.
9. **Look before paying.** `ms refs <job> --sheet --no-open` writes `ref_sheet.png` with every picture, the pixel
   warnings and the consistency line; Read it. Then the owner approves (`ms refs <job>`), then `ms grid`, then `ms seed`.

## What a seed sheet is not

- Not a design document: the rig key, the labelled bottom view with socket names and the HOTAS close-up of the Mk II's
  concept sheet are for people. Keep them in `ref/` for the plan (zones, the cockpit insert), never feed them to a mesher.
- Not a place to fix the mesher's bias: a model that discounts width is corrected after the seed (`ms fit`, the
  planform brushes), not by drawing the front view wider than the hero.
