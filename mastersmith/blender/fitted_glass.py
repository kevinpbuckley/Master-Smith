"""Select only the thin skin near explicitly fitted panes, leaving frames and cockpit contents intact."""
import numpy as np


def surface_mask(centres, normals, vertices, triangles, tolerance, bounds=None):
    """Match face centres to a pane's triangle interiors and a limited depth on either side."""
    centres, normals = np.asarray(centres), np.asarray(normals)
    vertices, triangles = np.asarray(vertices, dtype=float), np.asarray(triangles, dtype=int)
    if tolerance <= 0 or not np.isfinite(tolerance):
        raise ValueError('fitted pane tolerance must be positive and finite')
    if not np.isfinite(vertices).all():
        raise ValueError('fitted pane vertices must be finite')
    mask = np.zeros(len(centres), dtype=bool)
    for ids in triangles:
        a, b, c = vertices[ids]
        u, v = b - a, c - a
        normal = np.cross(u, v)
        length = np.linalg.norm(normal)
        if length < 1e-10:
            raise ValueError('fitted pane contains a degenerate triangle')
        normal /= length
        delta = centres - a
        distance = delta @ normal
        uu, uv, vv = u @ u, u @ v, v @ v
        du, dv = delta @ u, delta @ v
        denominator = uu * vv - uv * uv
        s = (vv * du - uv * dv) / denominator
        t = (uu * dv - uv * du) / denominator
        mask |= ((abs(distance) <= tolerance) & (s >= -1e-6) & (t >= -1e-6)
                 & (s + t <= 1 + 1e-6) & (abs(normals @ normal) >= 0.45))
    if bounds is not None:
        mask &= np.all((centres >= np.asarray(bounds[0])) & (centres <= np.asarray(bounds[1])), axis=1)
    return mask
