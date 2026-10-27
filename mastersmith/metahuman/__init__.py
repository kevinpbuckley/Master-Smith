"""MetaHuman handoff: what Master Smith knows about Unreal 5.8's "custom mesh to MetaHuman" without the editor.

The templates in templates/ were exported from UE 5.8.3 through the editor's Python on 2026-10-04 (the editor is
not part of a build): the body identity template SKM_Body (the MetaHuman A-pose, 1.31 m to the neck seam, UDIM 1002),
the face archetype SKM_Face (UDIM 1001, 15 material slots), the head static-mesh template SM_MH_Head, every bone of
both skeletons in component space (*.skeleton.json), template.json measured by blender/mh_template.py, and the
silhouettes the conform tool overlays a seed on. template.py reads them."""
