"""Opt-in shading repair for continuous organic surfaces; no topology or winding edits."""
import numpy as np


def corner_normal_splits(mesh, threshold_degrees=1.0):
    """Count corners differing from the first corner at their shared vertex.

    This is a diagnostic, not a defect verdict: hard-surface creases are legitimate.
    Coincident but disconnected vertices are deliberately not welded or averaged.
    """
    if not len(mesh.loops):
        return {"split_corners": 0, "max_split_degrees": 0.0}
    vertices = np.empty(len(mesh.loops), np.int32)
    mesh.loops.foreach_get("vertex_index", vertices)
    normals = np.empty(len(mesh.loops) * 3, np.float32)
    mesh.corner_normals.foreach_get("vector", normals)
    normals = normals.reshape(-1, 3)
    _, first, inverse = np.unique(vertices, return_index=True, return_inverse=True)
    reference = normals[first[inverse]]
    lengths = np.linalg.norm(normals, axis=1) * np.linalg.norm(reference, axis=1)
    valid = lengths > 1e-8
    dots = np.sum(normals[valid] * reference[valid], axis=1) / lengths[valid]
    angles = np.degrees(np.arccos(np.clip(dots, -1.0, 1.0)))
    return {"split_corners": int(np.count_nonzero(angles > threshold_degrees)),
            "max_split_degrees": round(float(angles.max()), 3) if len(angles) else 0.0}


def mark_hard_edges(obj, angle_degrees):
    """Hard-surface shading: smooth faces, with the edges whose faces meet at more than `angle_degrees` marked sharp,
    so flat panels stay flat and creases stay crisp instead of one smooth fan melting across them (the "gooey" bullpup,
    2026-09-26: every polygon smooth, no sharp edge anywhere). Only manifold edges are judged; nothing is moved,
    welded or re-wound. Run it BEFORE the tangent-normal bake so the bake and the delivery share one basis."""
    import bmesh
    import math
    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    limit = math.radians(float(angle_degrees))
    for face in bm.faces:
        face.smooth = True
    sharp = 0
    for edge in bm.edges:
        hard = edge.is_manifold and edge.calc_face_angle(0.0) > limit
        edge.smooth = not hard
        sharp += int(hard)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return {"object": obj.name, "angle": float(angle_degrees), "sharp_edges": sharp, "edges": len(mesh.edges)}


def smooth_organic_normals(obj):
    """Use only on explicitly selected organic geometry without intentional hard edges.

    Same normal at every face corner of a shared vertex, including separate normal
    fans at non-manifold joins. No remesh, welding, displacement or face reversal.
    Applying this after a tangent-normal bake would change its shading basis.
    """
    mesh = obj.data
    before = corner_normal_splits(mesh)
    sharp_edges = sum(edge.use_edge_sharp for edge in mesh.edges)
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    for edge in mesh.edges:
        edge.use_edge_sharp = False
    mesh.update()
    mesh.normals_split_custom_set_from_vertices([tuple(vertex.normal) for vertex in mesh.vertices])
    mesh.update()
    return {"object": obj.name, "before": before, "sharp_edges_cleared": sharp_edges,
            "operation": "shared_vertex_normals", "positions_changed": False,
            "topology_changed": False, "uvs_changed": False, "winding_changed": False}
