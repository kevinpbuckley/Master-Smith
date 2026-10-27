"""Exact parts as signed distance functions (issue #12). A barrel is `cylinder(r, L) - cylinder(bore, L)`, a rail is a
box with `repeat`ed slots subtracted, a moulded blend is `smooth_union(a, b, k)`: the shape is text, the edges are
as sharp as written, round is round, and no topology can break. Units are metres; `mm(x)` converts.

    def part(kit, L, W, H):                          # the part's box, metres, centred at the origin
        body = kit.cylinder(W / 2, L, axis="x")
        return body - kit.cylinder(kit.mm(5.56) / 2, L * 1.1, axis="x")

`mesh(sdf, lo, hi, voxel)` samples the field on a grid and runs marching cubes (scikit-image) -> (verts, faces);
`write_glb` saves it (trimesh). Every function below takes and returns an SDF; an SDF is called with points (n, 3)
and answers distances (n,), negative inside."""
import numpy as np


def mm(x):
    return float(x) / 1000.0


class SDF:
    def __init__(self, f):
        self.f = f

    def __call__(self, p):
        return self.f(np.asarray(p, dtype=np.float64).reshape(-1, 3))

    # set operations as operators
    def __or__(self, other):
        return union(self, other)

    def __and__(self, other):
        return intersect(self, other)

    def __sub__(self, other):
        return subtract(self, other)

    # transforms
    def translate(self, v):
        v = np.asarray(v, dtype=np.float64)
        return SDF(lambda p: self.f(p - v))

    def rotate(self, axis, degrees):
        """About the origin; axis "x" | "y" | "z" or a vector."""
        a = {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}.get(axis, axis)
        a = np.asarray(a, dtype=np.float64)
        a /= max(np.linalg.norm(a), 1e-12)
        t = np.radians(degrees)
        K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
        R = np.eye(3) + np.sin(t) * K + (1 - np.cos(t)) * (K @ K)
        Rinv = R.T
        return SDF(lambda p: self.f(p @ Rinv.T))

    def scale(self, s):
        """Uniform scale (a non-uniform scale is not a distance any more; stretch the primitives instead)."""
        s = float(s)
        return SDF(lambda p: self.f(p / s) * s)

    def mirror(self, axis="y"):
        """The shape and its mirror image across the plane through the origin."""
        i = "xyz".index(axis)

        def f(p):
            q = p.copy()
            q[:, i] = np.abs(q[:, i])
            return self.f(q)
        return SDF(f)

    def shell(self, thickness):
        """Hollow: the surface as a skin of `thickness`."""
        return SDF(lambda p: np.abs(self.f(p)) - thickness / 2.0)

    def round(self, r):
        """Round every edge by `r` (grows the shape by r; shrink the primitive by r to keep the size)."""
        return SDF(lambda p: self.f(p) - r)

    def elongate(self, h):
        """Stretch the shape by inserting a flat section of half-lengths h (3-vector) at its middle."""
        h = np.asarray(h, dtype=np.float64)
        return SDF(lambda p: self.f(p - np.clip(p, -h, h)))

    def repeat(self, pitch, count):
        """Copies along the axes: pitch (3-vector, 0 = no repeat on that axis), count (3-vector of copies, odd or
        even; the copies are centred on the origin)."""
        pitch = np.asarray(pitch, dtype=np.float64)
        count = np.asarray(count, dtype=np.float64)
        lo, hi = -(count - 1) / 2.0, (count - 1) / 2.0

        def f(p):
            q = p.copy()
            for i in range(3):
                if pitch[i] > 0 and count[i] > 1:
                    k = np.clip(np.round(q[:, i] / pitch[i]), lo[i], hi[i])
                    q[:, i] = q[:, i] - k * pitch[i]
            return self.f(q)
        return SDF(f)


# ---------------------------------------------------------------- primitives (centred at the origin)
def _axes(axis):
    i = "xyz".index(axis)
    others = [j for j in range(3) if j != i]
    return i, others


def sphere(r):
    return SDF(lambda p: np.linalg.norm(p, axis=1) - r)


def box(size):
    """size = (Lx, Ly, Lz) full lengths."""
    h = np.asarray(size, dtype=np.float64) / 2.0

    def f(p):
        q = np.abs(p) - h
        return np.linalg.norm(np.maximum(q, 0), axis=1) + np.minimum(q.max(axis=1), 0)
    return SDF(f)


def rounded_box(size, r):
    h = np.asarray(size, dtype=np.float64) / 2.0 - r
    return box(h * 2).round(r)


def cylinder(r, length, axis="x"):
    i, others = _axes(axis)

    def f(p):
        d = np.stack([np.linalg.norm(p[:, others], axis=1) - r, np.abs(p[:, i]) - length / 2.0], axis=1)
        return np.linalg.norm(np.maximum(d, 0), axis=1) + np.minimum(d.max(axis=1), 0)
    return SDF(f)


def cone(r0, r1, length, axis="x"):
    """A truncated cone: radius r0 at the -axis end, r1 at the +axis end."""
    i, others = _axes(axis)
    hl = length / 2.0

    def f(p):
        t = np.clip((p[:, i] + hl) / max(length, 1e-12), 0, 1)
        r = r0 + (r1 - r0) * t
        radial = np.linalg.norm(p[:, others], axis=1) - r
        # the slant makes the radial distance a little short; scale by the cone's half-angle cosine
        cos_a = length / np.hypot(length, r1 - r0)
        d = np.stack([radial * cos_a, np.abs(p[:, i]) - hl], axis=1)
        return np.linalg.norm(np.maximum(d, 0), axis=1) + np.minimum(d.max(axis=1), 0)
    return SDF(f)


def capsule(a, b, r):
    a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    ab = b - a

    def f(p):
        t = np.clip(((p - a) @ ab) / max(ab @ ab, 1e-12), 0, 1)
        return np.linalg.norm(p - (a + t[:, None] * ab), axis=1) - r
    return SDF(f)


def torus(R, r, axis="z"):
    i, others = _axes(axis)

    def f(p):
        q = np.stack([np.linalg.norm(p[:, others], axis=1) - R, p[:, i]], axis=1)
        return np.linalg.norm(q, axis=1) - r
    return SDF(f)


def plane(normal, offset=0.0):
    """The half-space below the plane n.p = offset (inside where n.p < offset)."""
    n = np.asarray(normal, dtype=np.float64)
    n /= max(np.linalg.norm(n), 1e-12)
    return SDF(lambda p: p @ n - offset)


def wedge(size, axis="z", across="y", taper=0.5):
    """A box whose +`axis` end is narrowed to `taper` of its full width measured `across` (a stock's comb, a ramp)."""
    i, _others = _axes(axis)
    j = "xyz".index(across)
    h = np.asarray(size, dtype=np.float64) / 2.0

    def f(p):
        t = np.clip((p[:, i] + h[i]) / max(size[i], 1e-12), 0, 1)
        wj = h[j] * (1 - (1 - taper) * t)
        q = np.abs(p) - h
        q[:, j] = np.abs(p[:, j]) - wj
        return np.linalg.norm(np.maximum(q, 0), axis=1) + np.minimum(q.max(axis=1), 0)
    return SDF(f)


# ---------------------------------------------------------------- operators
def union(*shapes):
    return SDF(lambda p: np.min(np.stack([s(p) for s in shapes]), axis=0))


def intersect(*shapes):
    return SDF(lambda p: np.max(np.stack([s(p) for s in shapes]), axis=0))


def subtract(a, b):
    return SDF(lambda p: np.maximum(a(p), -b(p)))


def _smin(a, b, k):
    h = np.clip(0.5 + 0.5 * (b - a) / max(k, 1e-12), 0, 1)
    return b + (a - b) * h - k * h * (1 - h)


def smooth_union(a, b, k):
    """Union with the joint blended over `k` metres: a moulded fillet."""
    return SDF(lambda p: _smin(a(p), b(p), k))


def smooth_subtract(a, b, k):
    return SDF(lambda p: -_smin(-a(p), b(p), k))


def smooth_intersect(a, b, k):
    return SDF(lambda p: -_smin(-a(p), -b(p), k))



# ---------------------------------------------------------------- hull-building primitives (2026-10-25, the Mk II's exact hull)
def custom(f):
    """Any function of points (n, 3) -> distances (n,) as a kit shape; `kit.np` is numpy for writing one."""
    return SDF(f)


def polygon2d(points):
    """The signed distance in a plane to a closed polygon (vertices (u, v), any winding; negative inside). The
    standard edge-distance-and-winding form (Inigo Quilez), exact everywhere."""
    v = np.asarray(points, dtype=np.float64)
    n = len(v)
    assert n >= 3

    def f(q):
        d = np.sum((q - v[0]) ** 2, axis=1)
        s = np.ones(len(q))
        for i in range(n):
            j = (i + 1) % n
            e = v[j] - v[i]
            w = q - v[i]
            t = np.clip((w @ e) / max(float(e @ e), 1e-18), 0, 1)
            b = w - np.outer(t, e)
            d = np.minimum(d, np.sum(b * b, axis=1))
            c1 = q[:, 1] >= v[i][1]
            c2 = q[:, 1] < v[j][1]
            c3 = e[0] * w[:, 1] > e[1] * w[:, 0]
            flip = (c1 & c2 & c3) | (~c1 & ~c2 & ~c3)
            s = np.where(flip, -s, s)
        return s * np.sqrt(d)
    return f


def prism(points, length, axis="z"):
    """A polygon (vertices in the plane across `axis`: (x, y) for "z", (x, z) for "y", (y, z) for "x") extruded
    +-length/2 along the axis: a planform, a fin, a bracket."""
    i, others = _axes(axis)
    g = polygon2d(points)
    h = float(length) / 2.0

    def f(p):
        d2 = g(p[:, others])
        dz = np.abs(p[:, i]) - h
        return np.sqrt(np.maximum(d2, 0) ** 2 + np.maximum(dz, 0) ** 2) + np.minimum(np.maximum(d2, dz), 0)
    return SDF(f)


def ellipsoid(radii):
    """An ellipsoid of semi-axes `radii` (3-vector); the distance is the usual close bound, exact on the axes."""
    r = np.asarray(radii, dtype=np.float64)

    def f(p):
        k0 = np.linalg.norm(p / r, axis=1)
        k1 = np.linalg.norm(p / (r * r), axis=1)
        return np.where(k0 < 1e-9, -float(r.min()), k0 * (k0 - 1.0) / np.maximum(k1, 1e-12))   # the bound is 0 at the centre
    return SDF(f)


def plane_through(a, b, c):
    """The half-space on the far side of the plane through three points, inside opposite the normal (a, b, c counter-
    clockwise seen from outside)."""
    a, b, c = (np.asarray(v, dtype=np.float64) for v in (a, b, c))
    n = np.cross(b - a, c - a)
    n /= max(np.linalg.norm(n), 1e-12)
    return SDF(lambda p: (p - a) @ n)


def facet_normals(pitches, yaws, top=True):
    """Unit directions on a (pitch, yaw) grid in degrees (pitch 0 = sideways, 90 = up; yaw 0 = +x), the straight-up
    one added with `top`: the panes of a greenhouse canopy."""
    out = [np.array([0.0, 0.0, 1.0])] if top else []
    for pt in pitches:
        for yw in yaws:
            a, b = np.radians(pt), np.radians(yw)
            out.append(np.array([np.cos(a) * np.cos(b), np.cos(a) * np.sin(b), np.sin(a)]))
    return out


def faceted(radii, normals):
    """The polyhedron circumscribing an ellipsoid: the intersection of its tangent planes with the given outward unit
    normals (a faceted canopy whose panes are flat, each tangent where the ellipsoid faces that way)."""
    r = np.asarray(radii, dtype=np.float64)
    N = np.array([np.asarray(n, dtype=np.float64) / max(np.linalg.norm(n), 1e-12) for n in normals])
    H = np.linalg.norm(N * r, axis=1)          # n.p = |diag(r) n| is the tangent plane with outward normal n
    return SDF(lambda p: np.max(p @ N.T - H, axis=1))


def faceted_edges(radii, normals, width):
    """The region within `width` of two of those tangent planes at once: the creases between the panes, which a
    frame bar follows when this is intersected with the polyhedron's shell (`faceted(...).shell(t)`)."""
    r = np.asarray(radii, dtype=np.float64)
    N = np.array([np.asarray(n, dtype=np.float64) / max(np.linalg.norm(n), 1e-12) for n in normals])
    H = np.linalg.norm(N * r, axis=1)

    def f(p):
        d = p @ N.T - H
        second = np.partition(d, -2, axis=1)[:, -2]
        return -second - float(width)
    return SDF(f)


def faceted_edge_lines(radii, normals, merge=1e-3):
    """The edge segments of `faceted(radii, normals)`: the polyhedron's vertices are the facets of the dual hull of
    the plane points n/h, its edges the dual's edges. -> [(a, b), ...] 3-vectors (coincident vertices merged)."""
    from scipy.spatial import ConvexHull
    r = np.asarray(radii, dtype=np.float64)
    N = np.array([np.asarray(n, dtype=np.float64) / max(np.linalg.norm(n), 1e-12) for n in normals])
    H = np.linalg.norm(N * r, axis=1)
    # an open polyhedron (a canopy with no panes below the sill) is closed by a far plane opposite its mean normal;
    # the edges that reach it are not creases and are dropped
    n_close = len(N)
    mean = N.mean(axis=0)
    if np.linalg.norm(mean) > 1e-6:
        N = np.vstack([N, -mean / np.linalg.norm(mean)])
        H = np.append(H, 20.0 * float(r.max()))
    hull = ConvexHull(N / H[:, None])
    verts, closing = [], []
    for tri in hull.simplices:                      # three planes meet at a polyhedron vertex
        A, b = N[tri], H[tri]
        closing.append(bool(np.any(tri >= n_close)))
        try:
            verts.append(np.linalg.solve(A, b))
        except np.linalg.LinAlgError:
            verts.append(np.full(3, np.nan))
    verts = np.array(verts)
    edges = {}
    for fi, nb in enumerate(hull.neighbors):
        for fj in nb:
            if fj < 0 or fj < fi or closing[fi] or closing[fj]:
                continue
            if not np.all(np.isfinite(verts[fi])) or not np.all(np.isfinite(verts[fj])):
                continue
            a, b = verts[fi], verts[fj]
            if np.linalg.norm(a - b) < merge:
                continue
            key = tuple(np.round(np.concatenate([np.minimum(a, b), np.maximum(a, b)]) / merge).astype(int))
            edges[key] = (a, b)
    return list(edges.values())


def faceted_bars(radii, normals, r):
    """Round bars of radius `r` along every crease of the faceted ellipsoid: a canopy's mullions, constant in width
    (the two-plane band of `faceted_edges` widened at shallow creases and filled every corner, 2026-10-25)."""
    segs = faceted_edge_lines(radii, normals)
    A = np.array([a for a, _b in segs])
    B = np.array([b for _a, b in segs])
    AB = B - A
    L2 = np.maximum(np.sum(AB * AB, axis=1), 1e-18)

    def f(p):
        best = np.full(len(p), np.inf)
        for i in range(len(A)):
            w = p - A[i]
            t = np.clip((w @ AB[i]) / L2[i], 0, 1)
            d = np.linalg.norm(w - np.outer(t, AB[i]), axis=1)
            best = np.minimum(best, d)
        return best - float(r)
    return SDF(f)


class MeshPart:
    """A part given as its own triangles instead of a field (2026-10-25, hard r2): a thin plate a voxel grid cannot
    hold - the Mk II's 2 mm steel rim edge came out of marching cubes as crumpled foil, and a smooth canopy bubble's
    mullions as a cage. `ms sdf` writes it as it is: no marching cubes, no decimation, no planar dissolve."""

    def __init__(self, verts, faces, smooth=None):
        # 2026-10-26 (hard r17): `smooth` (degrees) is the angle the import shades smooth under; None keeps the import's
        # 6 degrees for a script's own triangles (a curved glass bubble of fine flat panes wants 30: one curved pane
        # between its bars, as the Mk II's hero canopy, not a crease at every facet)
        self.smooth = None if smooth is None else float(smooth)
        self.verts = np.asarray(verts, dtype=np.float64).reshape(-1, 3)
        self.faces = np.asarray(faces, dtype=np.int64).reshape(-1, 3)
        if not len(self.faces) or self.faces.min() < 0 or self.faces.max() >= len(self.verts):
            raise ValueError("a mesh part needs faces indexing its vertices")
        v = self.verts[self.faces]                     # collapsed faces (an outline's tip, a bubble's pole) dropped
        area = 0.5 * np.linalg.norm(np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0]), axis=1)
        self.faces = self.faces[area > 1e-12]


def mesh_part(verts, faces, smooth=None):
    """Triangles (verts (n, 3) metres in the part's frame, faces (m, 3)) as a part: see MeshPart (`smooth`: the
    shading angle in degrees, the import's 6 when None)."""
    return MeshPart(verts, faces, smooth)


def lerp_profile(stations):
    """A piecewise-linear function of one coordinate from (t, value) stations, held flat beyond the ends: a deck
    line, a keel line, a half-width along the length."""
    st = np.asarray(stations, dtype=np.float64)
    order = np.argsort(st[:, 0])
    xs, ys = st[order, 0], st[order, 1]
    return lambda t: np.interp(t, xs, ys)

KIT = {name: obj for name, obj in globals().items()
       if name in ("mm", "sphere", "box", "rounded_box", "cylinder", "cone", "capsule", "torus", "plane", "wedge",
                   "union", "intersect", "subtract", "smooth_union", "smooth_subtract", "smooth_intersect",
                   "custom", "polygon2d", "prism", "ellipsoid", "plane_through", "facet_normals", "faceted",
                   "faceted_edges", "faceted_edge_lines", "faceted_bars", "lerp_profile", "mesh_part")}
KIT["np"] = np


class Kit:
    """The namespace a part script gets: `kit.cylinder(...)`, `kit.mm(5)`, ..."""

    def __init__(self):
        for k, v in KIT.items():
            setattr(self, k, v)


# ---------------------------------------------------------------- meshing
def mesh(sdf, lo, hi, voxel, chunk=2_000_000):
    """Marching cubes over the box [lo, hi] at `voxel` metres. -> (verts (n,3) float64 in metres, faces (m,3) int)"""
    from skimage import measure
    lo, hi = np.asarray(lo, dtype=np.float64), np.asarray(hi, dtype=np.float64)
    lo, hi = lo - 2 * voxel, hi + 2 * voxel                 # a margin so the surface closes at the box
    axes = [np.arange(lo[i], hi[i] + voxel, voxel) for i in range(3)]
    gx, gy, gz = np.meshgrid(*axes, indexing="ij")
    pts = np.stack([gx.ravel(), gy.ravel(), gz.ravel()], axis=1)
    vals = np.empty(len(pts))
    for i in range(0, len(pts), chunk):
        vals[i:i + chunk] = sdf(pts[i:i + chunk])
    vol = vals.reshape(gx.shape)
    if vol.min() > 0 or vol.max() < 0:
        raise ValueError("the field has no surface inside the box (all %s)" % ("outside" if vol.min() > 0 else "inside"))
    verts, faces, _normals, _values = measure.marching_cubes(vol, level=0.0, spacing=(voxel, voxel, voxel))
    verts = verts + lo
    faces = faces.astype(np.int64)                           # skimage's winding faces outward for a field negative inside
    return verts, faces


def to_gltf_axes(verts):
    """Z-up asset-frame points -> glTF's Y-up frame, (x, y, z) -> (x, z, -y), so Blender's importer turns them back
    unchanged. Written as-is the importer swapped Y and Z: a two-pod band part came in 2.6 m tall (cloud test A, 2026-10-22)."""
    v = np.asarray(verts, dtype=np.float64)
    return np.stack([v[:, 0], v[:, 2], -v[:, 1]], axis=1)


def auto_voxel(L, W, H, budget=8_000_000):
    """The default voxel (metres): 1/320 of the longest side, 0.15-1 mm, but never a grid over `budget` points. The 1 mm
    cap alone asked a 1.5 m pod part for ~650 M points and the run was OOM-killed (cloud test A, 2026-10-22); 60 M
    points took over 30 minutes on a 1.3 m cockpit tub, most of it Blender's planar dissolve (cloud test B, 2026-10-23)."""
    v = min(max(max(L, W, H) / 320.0, 0.00015), 0.001)
    floor = ((L + 4 * v) * (W + 4 * v) * (H + 4 * v) / float(budget)) ** (1.0 / 3.0)
    return max(v, floor)


def decimate(verts, faces, target=200_000):
    """Marching cubes over a hull-sized part gives 600k+ slivers and Blender's planar dissolve of them ran past 12
    minutes (the Mk II's 8 mm hull, 2026-10-25): a quadric collapse to `target` keeps the planes and creases and the
    dissolve then takes seconds. -> (verts, faces), unchanged under the target or without fast_simplification."""
    faces = np.asarray(faces, dtype=np.int64)
    if len(faces) <= target:
        return verts, faces
    try:
        import fast_simplification
    except ImportError:
        return verts, faces
    v, f = fast_simplification.simplify(np.asarray(verts, dtype=np.float64), faces, target_count=int(target), agg=5)
    return np.asarray(v, dtype=np.float64), np.asarray(f, dtype=np.int64)


def write_glb(verts, faces, path, target=200_000):
    import trimesh
    verts, faces = decimate(verts, faces, target)
    m = trimesh.Trimesh(vertices=to_gltf_axes(verts), faces=np.asarray(faces, dtype=np.int64), process=True)
    m.export(path)
    return path


def run_part_script(source, L, W, H):
    """Run a part script (`def part(kit, L, W, H)` returning an SDF or a `kit.mesh_part`) in a namespace that holds
    only the kit."""
    ns = {"__builtins__": {"range": range, "len": len, "min": min, "max": max, "abs": abs, "float": float, "int": int,
                           "round": round, "list": list, "tuple": tuple, "zip": zip, "enumerate": enumerate,
                           "reversed": reversed, "sorted": sorted, "sum": sum}}
    exec(compile(source, "part.py", "exec"), ns)
    if "part" not in ns:
        raise ValueError("the script defines no `part(kit, L, W, H)`")
    out = ns["part"](Kit(), float(L), float(W), float(H))
    if not isinstance(out, (SDF, MeshPart)):
        raise ValueError("part() must return a kit shape or kit.mesh_part(verts, faces)")
    return out
