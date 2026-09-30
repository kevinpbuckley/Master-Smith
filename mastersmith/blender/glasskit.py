"""The glass and cockpit passes shared by assemble.py and cabin.py (inside Blender): picking a glass zone's faces
off the seed's texture, closing the holes in a canopy frame with a shell, cutting the glass out, lining the walls seen
through it, and finding the seed's own cockpit contents so an interior part can replace them. Moved out of
assemble.py on 2026-09-29 so `ms cabin` measures the well the assembler will leave."""
import bmesh
import bpy
import numpy as np
from mathutils import Vector

import blib


def base_image(m):
    """The colour image upstream of a material's base colour (a seed's texture), or None."""
    if not m or not m.node_tree:
        return None
    b = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    todo = [b.inputs["Base Color"].links[0].from_node] if b is not None and b.inputs["Base Color"].is_linked else []
    seen = set()
    while todo:
        n = todo.pop()
        if n.name in seen:
            continue
        seen.add(n.name)
        if n.type == "TEX_IMAGE" and n.image is not None and n.image.size[0]:
            return n.image
        todo.extend(l.from_node for i in n.inputs for l in i.links)
    return None


def face_rgb(o):
    """Each polygon's seed texture colour, the base-colour image at the polygon's UV centre -> (n, 3) or None.
    Values are the image's stored colour (sRGB), as the glass predicates expect."""
    me = o.data
    img = next((base_image(m) for m in me.materials if base_image(m) is not None), None)
    if img is None or not me.uv_layers.active:
        return None
    w, h = img.size
    px = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(px)
    px = px.reshape(h, w, 4)
    n = len(me.polygons)
    uv = np.empty(len(me.loops) * 2, np.float32)
    me.uv_layers.active.data.foreach_get("uv", uv)
    uv = uv.reshape(-1, 2)
    start = np.empty(n, np.int64)
    total = np.empty(n, np.int64)
    me.polygons.foreach_get("loop_start", start)
    me.polygons.foreach_get("loop_total", total)
    c = np.add.reduceat(uv, start, axis=0) / total[:, None]
    c = c % 1.0
    return px[np.minimum((c[:, 1] * h).astype(int), h - 1), np.minimum((c[:, 0] * w).astype(int), w - 1), :3]


def face_pairs(me, weld):
    """Faces that share an edge, the vertices welded by position first (a GLB seed is split at every UV seam, so its
    own edges stop at the seams) -> (face_a, face_b, edge face counts)."""
    nv = len(me.vertices)
    co = np.empty(nv * 3, np.float64)
    me.vertices.foreach_get("co", co)
    _, vid = np.unique(np.round(co.reshape(-1, 3) / max(weld, 1e-9)).astype(np.int64), axis=0, return_inverse=True)
    vid = vid.ravel()
    n = len(me.polygons)
    lv = np.empty(len(me.loops), np.int64)
    me.loops.foreach_get("vertex_index", lv)
    start = np.empty(n, np.int64)
    total = np.empty(n, np.int64)
    me.polygons.foreach_get("loop_start", start)
    me.polygons.foreach_get("loop_total", total)
    nxt = np.arange(len(lv)) + 1
    nxt[start + total - 1] = start
    a, b = vid[lv], vid[lv[nxt]]
    key = np.minimum(a, b) * (int(vid.max()) + 1) + np.maximum(a, b)
    face = np.repeat(np.arange(n), total)
    order = np.argsort(key, kind="stable")
    ks, fs = key[order], face[order]
    same = ks[1:] == ks[:-1]
    _, counts = np.unique(ks, return_counts=True)
    fa, fb = fs[:-1][same], fs[1:][same]
    return np.concatenate([fa, fb]), np.concatenate([fb, fa]), counts


def components(n, fa, fb, mask=None):
    """Connected faces (union-find over the edge pairs, only faces in `mask`) -> a root id per face."""
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    sel = (mask[fa] & mask[fb]) if mask is not None else np.ones(len(fa), bool)
    for x, y in zip(fa[sel].tolist(), fb[sel].tolist()):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry
    return np.array([find(i) for i in range(n)])


def mesh_tree(o, extra=None):
    """A ray tree of the part's faces, and of `extra` (vertices, triangles) - panes not yet in the mesh.
    -> (tree, polygon index per tree triangle; -1 for the extra ones)"""
    from mathutils.bvhtree import BVHTree
    me = o.data
    me.calc_loop_triangles()
    co = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    tri = np.empty(len(me.loop_triangles) * 3, np.int32)
    me.loop_triangles.foreach_get("vertices", tri)
    tri = tri.reshape(-1, 3)
    poly = np.empty(len(me.loop_triangles), np.int64)
    me.loop_triangles.foreach_get("polygon_index", poly)
    if extra is not None and len(extra[1]):
        tri = np.concatenate([tri, np.asarray(extra[1]) + len(co)])
        co = np.concatenate([co, np.asarray(extra[0], np.float32)])
        poly = np.concatenate([poly, np.full(len(extra[1]), -1, np.int64)])
    return BVHTree.FromPolygons([Vector(v) for v in co], tri.tolist()), poly


def escapes(tree, c, nrm, eps, through=None, need=1):
    """A ray from `c` along the normal (or tilted up, or outwards to its side) leaves the model without a hit - or
    its first hit is a polygon in `through` (a pane that is glass itself) - in at least `need` of the three
    directions. `tree` is a mesh_tree."""
    tree, poly = tree
    side = Vector((0.0, 0.5 if c.y >= 0 else -0.5, 0.0))
    got = 0
    for d in (nrm, (nrm + Vector((0.0, 0.0, 0.5))).normalized(), (nrm + side).normalized()):
        if d.length == 0:
            continue
        hit = tree.ray_cast(c + d * eps, d)
        if hit[0] is None or (through is not None and poly[hit[2]] >= 0 and through[poly[hit[2]]]):
            got += 1
            if got >= need:
                return True
    return False


def exterior_faces(tree, cand, centres, normals, diag, need=1):
    """Of the candidate faces, the ones on the outside skin: their rays escape. The seats, panels and tub INSIDE a
    canopy are painted as dark as its glass and sit in its box; their rays hit the canopy - or the panes `fill_panes`
    closed its open windows with, which is why the tree carries them - so they stay opaque (owner, 2026-09-29: "we
    also rendered the inside of the cockpit as glass")."""
    out = np.zeros(len(centres), bool)
    eps = diag * 1e-4
    for i in np.nonzero(cand)[0]:
        out[i] = escapes(tree, Vector(centres[i]), Vector(normals[i]), eps, need=need)
    return out


def canopy_hull(o, box_faces, diag, edge=1 / 120.0):
    """The convex hull of the zone's faces, cut into triangles no longer than `edge` of the diagonal, normals out:
    the canopy's outer envelope (a canopy is convex; its frame and panes lie on the hull, the cockpit deep inside).
    -> bmesh or None"""
    me = o.data
    co = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    lv = np.empty(len(me.loops), np.int64)
    me.loops.foreach_get("vertex_index", lv)
    total = np.empty(len(me.polygons), np.int64)
    me.polygons.foreach_get("loop_total", total)
    vi = np.unique(lv[box_faces[np.repeat(np.arange(len(me.polygons)), total)]])
    if len(vi) < 8:
        return None
    bm = bmesh.new()
    res = bmesh.ops.convex_hull(bm, input=[bm.verts.new(co[i]) for i in vi])
    loose = {g for g in res["geom_interior"] + res["geom_unused"] if isinstance(g, bmesh.types.BMVert)}
    bmesh.ops.delete(bm, geom=list(loose), context="VERTS")
    if not bm.faces:
        bm.free()
        return None
    mid = Vector(co[vi].mean(axis=0))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    if sum((f.calc_center_median() - mid).dot(f.normal) for f in bm.faces) < 0:
        bmesh.ops.reverse_faces(bm, faces=bm.faces[:])
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    target = diag * edge
    for _ in range(14):
        long = [e for e in bm.edges if e.calc_length() > target]
        if not long:
            break
        bmesh.ops.subdivide_edges(bm, edges=long, cuts=1, use_grid_fill=True)
        bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bm.normal_update()
    return bm


def glass_shell(hull, tree, diag, inset=0.002, min_patch=30):
    """Glass over the holes that go straight through a canopy (the Tripo Havoc, 2026-09-29: the rear of its canopy
    frame was open, so the sky showed through the cockpit and nothing reflected). The hull is set `inset` (of the
    diagonal) inside the frame; a face is kept where a ray outward leaves the model and a ray inward meets nothing or
    the back of a face (the inside of the far wall) - not the roof, the frame, the seed's own panes or the nose. One
    ring more tucks the edges under the frame; patches under `min_patch` faces go. -> (vertices, triangles) or None"""
    bm = hull.copy()
    for v in bm.verts:
        v.co -= v.normal * (inset * diag)
    bm.normal_update()
    bm.faces.ensure_lookup_table()
    faces = list(bm.faces)
    eps = diag * 1e-4
    keep = np.zeros(len(faces), bool)
    tucked = np.zeros(len(faces), bool)
    rays = tree[0]
    for i, f in enumerate(faces):
        n = f.normal
        if n.z < -0.3:
            continue
        c = f.calc_center_median()
        if not escapes(tree, c, n, eps):
            out = rays.ray_cast(c + n * eps, n)
            tucked[i] = out[0] is not None and out[3] < 4 * inset * diag
            continue
        hit = rays.ray_cast(c - n * eps, -n)
        keep[i] = hit[0] is None or hit[1].dot(-n) > 0
    ring = np.zeros(len(faces), bool)
    for i in np.nonzero(keep)[0]:
        for e in faces[i].edges:
            for g in e.link_faces:
                ring[g.index] = True
    keep |= ring & tucked
    # a hole is a patch; slivers along panel lines on the nose are dents the hull bridges, not holes
    seen = np.zeros(len(faces), bool)
    for i in np.nonzero(keep)[0]:
        if seen[i]:
            continue
        patch, todo = [], [i]
        seen[i] = True
        while todo:
            j = todo.pop()
            patch.append(j)
            for e in faces[j].edges:
                for g in e.link_faces:
                    if keep[g.index] and not seen[g.index]:
                        seen[g.index] = True
                        todo.append(g.index)
        if len(patch) < min_patch:
            keep[patch] = False
    bmesh.ops.delete(bm, geom=[f for i, f in enumerate(faces) if not keep[i]], context="FACES")
    if not bm.faces:
        bm.free()
        return None
    bm.verts.ensure_lookup_table()
    verts = np.array([tuple(v.co) for v in bm.verts], np.float32)
    tris = np.array([[v.index for v in f.verts] for f in bm.faces], np.int32)
    bm.free()
    return verts, tris


def pane_object(o, panes, name):
    """The filled panes as an object beside the part, in its frame, with an empty UV layer for the join."""
    me = bpy.data.meshes.new(name)
    me.from_pydata(panes[0].tolist(), [], panes[1].tolist())
    me.uv_layers.new(name=o.data.uv_layers.active.name if o.data.uv_layers.active else "UVMap")
    me.update()
    g = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(g)
    g.matrix_world = o.matrix_world.copy()
    return g


def glass_paint(rgb, mode):
    """The faces painted like glass in one style -> (pick, near). "dark": near-black or deep blue-grey; "pale": a
    light, unsaturated grey (a pane painted with the sky in it: the Tripo Havoc, 2026-09-29, where the dark faces were
    the roof, the frame and the cockpit behind the panes); "lit": pale, or a warm glow (lit windows)."""
    mx, mn = rgb.max(axis=1), rgb.min(axis=1)
    sat = (mx - mn) / np.maximum(mx, 1e-6)
    r, b = rgb[:, 0], rgb[:, 2]
    if mode == "lit":
        return (mx >= 0.30) | ((r - b >= 0.05) & (mx >= 0.08)), (mx >= 0.22) | ((r - b >= 0.03) & (mx >= 0.06))
    if mode == "pale":
        return (mx >= 0.36) & (sat <= 0.10), (mx >= 0.30) & (sat <= 0.14)
    return (mx <= 0.22) & (sat <= 0.35), mx <= 0.35


def pick_glass(o, z, mode, keep=8, min_run=40, fill=True):
    """A glass zone's faces picked the way Tonetta's forge picks them (glass/SKILL.md, 2026-09-29): inside the zone's
    box (grown a little), the faces whose seed texture is painted like glass (`glass_paint`; "auto" takes the style
    with more of the outside skin), grown one ring into near-glass faces across seams, runs under `min_run` faces
    dropped, holes closed, the `keep` largest patches kept. A box or normal test alone ships the canopy speckled
    (the G-Police Havoc windshield, 2026-09-09). Only faces on the outside skin are glass, and holes straight through
    the canopy are closed with a shell (`fill`). -> (face mask, stats, panes or None)"""
    me = o.data
    n = len(me.polygons)
    centres = np.empty(n * 3, np.float32)
    me.polygons.foreach_get("center", centres)
    centres = centres.reshape(-1, 3)
    normals = np.empty(n * 3, np.float32)
    me.polygons.foreach_get("normal", normals)
    normals = normals.reshape(-1, 3)
    area = np.empty(n, np.float32)
    me.polygons.foreach_get("area", area)
    lo_o, hi_o = blib.dims(o)
    diag = (hi_o - lo_o).length
    lo, hi = np.array(z["box_min"]) - 0.02 * diag, np.array(z["box_max"]) + 0.02 * diag
    inbox = np.all((centres >= lo) & (centres <= hi), axis=1)
    fa, fb, _ = face_pairs(me, diag * 1e-5)
    rgb = face_rgb(o) if mode != "box" else None
    tree = mesh_tree(o)
    styles = {}
    if rgb is None:
        pick, near = inbox.copy(), inbox.copy()
        mode = "box"
        outside = exterior_faces(tree, pick | near, centres, normals, diag)
    else:
        # only the outside skin is glass: the cockpit's seats and panels under it are not (2026-09-29)
        for style in (("dark", "pale") if mode == "auto" else (mode,)):
            pk, nr = glass_paint(rgb, style)
            pk, nr = pk & inbox, nr & inbox
            out = exterior_faces(tree, pk | nr, centres, normals, diag)
            styles[style] = (pk, nr, out, float(area[pk & out].sum()))
        mode = max(styles, key=lambda k: styles[k][3])
        pick, near, outside, _a = styles[mode]
    panes = None
    if fill:
        # the canopy's envelope is the hull of its outer glass-painted skin (not the whole box: the navy nose passes
        # the dark test too); the shell closes the holes that go straight through it
        hull = canopy_hull(o, pick & outside, diag)
        if hull is not None:
            panes = glass_shell(hull, tree, diag)
            hull.free()
    if panes is not None:
        # what is seen through the closed holes is inside
        outside = exterior_faces(mesh_tree(o, panes), pick | near, centres, normals, diag)
    interior = int(((pick | near) & ~outside).sum())
    glassy = pick | near                         # before the outside test: a pane's inner skin is among these
    pick &= outside
    near &= outside
    grown = pick.copy()
    grown[fb[pick[fa] & near[fb]]] = True
    roots = components(n, fa, fb, grown)
    ids, counts = np.unique(roots[grown], return_counts=True)
    grown &= ~np.isin(roots, ids[counts < min_run])
    for _ in range(2):                                   # close holes: a face with two picked neighbours joins
        hits = np.bincount(fa[grown[fb]], minlength=n)
        grown |= (hits >= 2) & inbox
    roots = components(n, fa, fb, grown)
    ids, counts = np.unique(roots[grown], return_counts=True)
    mask = grown & np.isin(roots, ids[np.argsort(-counts)[:keep]]) if len(ids) else grown
    kept = np.sort(counts)[::-1][:keep] if len(ids) else np.array([0])
    # a pane modelled with a thickness has an inner skin just behind it, whatever it is painted: glass too. Left
    # opaque, the Havoc's inner skins were lined dark and read as black panels in every window (2026-09-29). Behind
    # (set back a few mm, facing the same way or the other) and near it - not the frame, which lies flush with it
    inner = 0
    if mask.any():
        from mathutils.bvhtree import BVHTree
        me.calc_loop_triangles()
        vco = [v.co.copy() for v in me.vertices]
        gt = BVHTree.FromPolygons(vco, [list(t.vertices) for t in me.loop_triangles if mask[t.polygon_index]])
        for i in np.nonzero(inbox & ~outside & ~mask)[0]:
            loc, gn, _gi, dist = gt.find_nearest(Vector(centres[i]), 0.004 * diag)
            if loc is None or abs(Vector(normals[i]).dot(gn)) < 0.7:
                continue
            if (loc - Vector(centres[i])).dot(gn) > 0.0002 * diag:
                mask[i] = True
                inner += 1
    faces = int(mask.sum())
    share = float(kept[0]) / max(faces, 1)
    # speckle is many islands, or kept patches holding little of the pick (a framed canopy is several panes, so the
    # largest one's share says nothing; the seats seen through it are dropped islands, so 60% is enough; 2026-09-29)
    coverage = faces / float(max(int(grown.sum()), 1))
    # Tonetta's count check: a canopy is 300-3,000 faces on a 50k-face seed (0.6-6%); far more means the pick took
    # the paint around it or what is behind it
    part_share = faces / float(max(n, 1))
    return mask, {"mode": mode, "styles_m2": {k: round(v[3], 2) for k, v in styles.items()}, "faces": faces, "islands": int(min(len(ids), keep)), "islands_found": int(len(ids)),
                  "largest_share": round(share, 3), "coverage": round(coverage, 3),
                  "dropped": np.sort(counts)[::-1][keep:keep + 6].tolist() if len(ids) else [], "interior_left_opaque": interior - inner,
                  "inner_skin": inner,
                  "share_of_part": round(part_share, 4), "pane_faces": int(len(panes[1])) if panes is not None else 0,
                  "ok": bool((faces < 40 or (coverage >= 0.6 and len(ids) <= 40)) and part_share <= 0.08)}, panes


def cut_out(o, mask, name):
    """The faces in `mask` moved out of `o` into an object of their own (UVs kept). -> the new object"""
    g = o.copy()
    g.data = o.data.copy()
    bpy.context.collection.objects.link(g)
    g.name = name
    for ob, keep in ((g, mask), (o, ~mask)):
        bm = bmesh.new()
        bm.from_mesh(ob.data)
        bm.faces.ensure_lookup_table()
        bmesh.ops.delete(bm, geom=[f for f in bm.faces if not keep[f.index]], context="FACES")
        bm.to_mesh(ob.data)
        bm.free()
        ob.data.validate()
        ob.data.update()
    return g


def line_interior(o, glass_objs, lo, hi, diag, thick=0.0015, name="Liner"):
    """An inside for a cockpit seen through glass (owner, 2026-09-29: the Havoc's reversed SECURITY): a mesher's
    cockpit walls are one skin thick, so through the canopy the eye met the BACK of the far side's outer panels, their
    lettering and Tripo's embossed "TNALT" mirrored. The body's faces in the box (`lo`..`hi`) whose back can be seen
    through the glass - a ray from just behind the face, straight in, tilted up, or towards the glass, meets glass
    first - get a copy `thick` (of the diagonal) further in, facing into the cockpit: a dark matte lining, its own
    material outside the atlas (sharing the skin's UVs would bake over the skin). -> (object or None, faces lined)"""
    from mathutils.bvhtree import BVHTree
    me = o.data
    me.calc_loop_triangles()
    co = np.empty(len(me.vertices) * 3, np.float64)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    tri = np.empty(len(me.loop_triangles) * 3, np.int64)
    me.loop_triangles.foreach_get("vertices", tri)
    tri = tri.reshape(-1, 3)
    verts, polys, is_glass = [Vector(v) for v in co], tri.tolist(), [False] * len(tri)
    gsum, gcount = Vector(), 0
    for g in glass_objs:
        gm = g.data
        gm.calc_loop_triangles()
        mw = g.matrix_world
        base = len(verts)
        verts += [mw @ v.co for v in gm.vertices]
        polys += [[base + i for i in t.vertices] for t in gm.loop_triangles]
        is_glass += [True] * len(gm.loop_triangles)
        for v in gm.vertices:
            gsum += mw @ v.co
            gcount += 1
    if not gcount:
        return None, 0
    gc = gsum / gcount
    tree = BVHTree.FromPolygons(verts, polys)
    n = len(me.polygons)
    centres = np.empty(n * 3, np.float32)
    me.polygons.foreach_get("center", centres)
    centres = centres.reshape(-1, 3)
    normals = np.empty(n * 3, np.float32)
    me.polygons.foreach_get("normal", normals)
    normals = normals.reshape(-1, 3)
    cand = np.nonzero(np.all((centres >= np.asarray(lo)) & (centres <= np.asarray(hi)), axis=1))[0]
    eps = diag * 1e-4
    lined = np.zeros(n, bool)
    for i in cand:
        c, nr = Vector(centres[i]), Vector(normals[i])
        start = c - nr * eps
        for d in (-nr, (-nr + Vector((0, 0, 0.7))).normalized(), (gc - start).normalized()):
            if d.length == 0 or d.dot(nr) > 0.2:
                continue
            hit = tree.ray_cast(start, d)
            if hit[0] is not None and is_glass[hit[2]]:
                lined[i] = True
                break
    if lined.sum() < 20:
        return None, int(lined.sum())
    # the lining shares welded vertices, pushed in along their area-weighted normals, so it has no cracks
    weld = max(diag * 1e-5, 1e-9)
    _, gid = np.unique(np.round(co / weld).astype(np.int64), axis=0, return_inverse=True)
    gid = gid.ravel()
    sel_tris = tri[lined[np.asarray([t.polygon_index for t in me.loop_triangles])]]
    cross = np.cross(co[sel_tris[:, 1]] - co[sel_tris[:, 0]], co[sel_tris[:, 2]] - co[sel_tris[:, 0]])
    acc = np.zeros((gid.max() + 1, 3))
    for k in range(3):
        np.add.at(acc, gid[sel_tris[:, k]], cross)
    acc /= np.maximum(np.linalg.norm(acc, axis=1, keepdims=True), 1e-12)
    groups, faces = {}, []
    for t in sel_tris:
        ids = []
        for vi in t[::-1]:                       # reversed winding: the lining faces into the cockpit
            gk = int(gid[vi])
            if gk not in groups:
                groups[gk] = len(groups)
            ids.append(groups[gk])
        faces.append(ids)
    pos = np.zeros((len(groups), 3))
    for gk, j in groups.items():
        first = np.nonzero(gid == gk)[0][0]
        pos[j] = co[first] - acc[gk] * (thick * diag)
    lm = bpy.data.meshes.new(name)
    lm.from_pydata(pos.tolist(), [], faces)
    lm.uv_layers.new(name=me.uv_layers.active.name if me.uv_layers.active else "UVMap")
    lm.update()
    for poly in lm.polygons:
        poly.use_smooth = True
    lo_obj = bpy.data.objects.new(name, lm)
    bpy.context.collection.objects.link(lo_obj)
    lo_obj.matrix_world = o.matrix_world.copy()
    return lo_obj, int(lined.sum())


def interior_material(name, colour=(0.018, 0.02, 0.024), rough=0.8):
    """The cockpit lining: dark grey, matte (the skills' cockpit: matte 0.7-0.9), no texture."""
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    b = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    b.inputs["Base Color"].default_value = (*colour, 1.0)
    b.inputs["Metallic"].default_value = 0.0
    b.inputs["Roughness"].default_value = rough
    return m


def glass_material(name, tint=(0.02, 0.03, 0.04), alpha=0.3, rough=0.05):
    """See-through glass that reads in every viewer (Tonetta's glass skill, 2026-09-29): alpha 0.3 (below 0.2 the pane
    vanishes, above 0.7 it is paint), specular 0.45 (0.8 on grey mirrored the backdrop and read as opaque grey), no
    normal map, blended, both sides drawn."""
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    b = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    b.inputs["Base Color"].default_value = (*tint, 1.0)
    b.inputs["Metallic"].default_value = 0.0
    b.inputs["Roughness"].default_value = rough
    b.inputs["Alpha"].default_value = alpha
    if "Specular IOR Level" in b.inputs:
        b.inputs["Specular IOR Level"].default_value = 0.45
    for l in list(b.inputs["Normal"].links):
        m.node_tree.links.remove(l)
    m.surface_render_method = "BLENDED"
    m.use_backface_culling = False
    m["ms_glass"] = True
    return m


def delete_faces(o, mask):
    """The faces in `mask` removed from `o` (its other faces, UVs and normals kept)."""
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bm.faces.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if mask[f.index]], context="FACES")
    bm.to_mesh(o.data)
    bm.free()
    o.data.validate()
    o.data.update()


def cockpit_contents(o, zones, boxes):
    """The seed's own cockpit, to be replaced by an interior part (owner, 2026-09-29: Tripo meshed the Havoc's
    cockpit closed around a vague seat and console, so no insert could go in): the faces inside an interior part's
    box whose rays all hit the model with the canopy closed - its glass faces in place and the holes in its frame
    shelled. The outer skin, the frame's outer faces and the glass stay; the seat, the consoles, the floor and the
    walls' inner layers go. `zones` are the glass zones ({box_min, box_max, pick}), `boxes` (lo, hi) pairs.
    -> (face mask, stats)"""
    me = o.data
    n = len(me.polygons)
    centres = np.empty(n * 3, np.float32)
    me.polygons.foreach_get("center", centres)
    centres = centres.reshape(-1, 3)
    normals = np.empty(n * 3, np.float32)
    me.polygons.foreach_get("normal", normals)
    normals = normals.reshape(-1, 3)
    lo_o, hi_o = blib.dims(o)
    diag = (hi_o - lo_o).length
    inside = np.zeros(n, bool)
    for lo, hi in boxes:
        inside |= np.all((centres >= np.asarray(lo)) & (centres <= np.asarray(hi)), axis=1)
    if not inside.any():
        return inside, {"faces": 0}
    verts, tris = [], []
    for z in zones:
        _m, _s, panes = pick_glass(o, z, z.get("pick") or "auto")
        if panes is not None:
            tris.append(np.asarray(panes[1]) + sum(len(v) for v in verts))
            verts.append(np.asarray(panes[0]))
    extra = (np.concatenate(verts), np.concatenate(tris)) if verts else None
    # the outer skin sees out in two of its three directions; a console whose one ray slipped out of the hollow nose
    # through a gun port does not (2026-09-29)
    outside = exterior_faces(mesh_tree(o, extra), inside, centres, normals, diag, need=2)
    mask = inside & ~outside
    return mask, {"faces": int(mask.sum()), "kept_skin": int((inside & outside).sum()), "shell_faces": int(len(extra[1])) if extra else 0}
