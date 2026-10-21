"""Generate a brand-new race track from a closed spline, headless, via Track Lab.

    blender -b --factory-startup --python tools/custom_tracks/make_track.py -- \
        --track-lab ~/src/DKR-R/tools/blender --assets ~/dkr-assets \
        --layout tools/custom_tracks/layouts/canyon-loop.json --out custom-tracks

The land is a heightfield: every terrain vertex takes its height from its
distance to the road, so the road runs along a valley floor with wide grass
run-off, rolling hills beyond and rocky cliffs at the edge of the world.
Because the height comes from the distance to the NEAREST part of the road,
infields between two stretches of road stay clean where offset strips would
fold over themselves. The road is a separate ribbon laid just above the
terrain, so its edges are crisp.

The layout file is JSON:

    {
      "name": "Canyon Loop", "id": "canyon-loop", "laps": 3, "scale": 0.5,
      "points": [[x, y, z], ...],      # closed loop, Blender axes (z up), map units
      "road": 1000, "runoff": 450,     # road width; flat grass each side of it
      "hills": 420, "cliff": 900,      # rolling hills, then the cliff at the edge
      "crests": [[0.84, 200, 900]],    # jump crests: [lap fraction, height, length]
      "textures": {...}, "music": 31, "skybox": "ASSET_OBJECT_DOME13",
      "checkpoints": 28, "zippers": [...], "balloons": [[fraction, type], ...],
      "bananas": [...], "scenery": 1300   # spacing of trees/bushes along the run-off
    }

Lap positions are fractions of the lap from the start line. Geometry is
original and textured with RETAIL textures by id, so the package ships no ROM
bytes; Track Lab does the model layout and the object-map/header encoding.
"""
import argparse
import json
import math
import os
import sys
import tempfile

import bmesh
import bpy
from mathutils import Vector
from mathutils.kdtree import KDTree

DEFAULTS = {
    "laps": 3, "scale": 1.0, "road": 1000, "runoff": 450, "hills": 420, "cliff": 900,
    "crests": [], "cell": 400, "margin": 2600,
    "textures": {"road": 816, "runoff": 65, "hill": 65, "slope": 167, "cliff": 35},
    "music": 31, "skybox": "ASSET_OBJECT_DOME13", "checkpoints": 28,
    "zippers": [], "balloons": [], "bananas": [], "scenery": 1300,
}
SURFACES = {"road": "0", "runoff": "1", "hill": "1", "slope": "4", "cliff": "4"}


def arguments():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--track-lab", required=True, help="DKR-R's tools/blender folder")
    parser.add_argument("--assets", required=True, help="Track Lab asset folder")
    parser.add_argument("--layout", required=True, help="layout JSON")
    parser.add_argument("--out", required=True, help="folder to write the .dkrmap into")
    parser.add_argument("--keep-blend", default="", help="also save the .blend here")
    return parser.parse_args(argv)


def smoothstep(edge0, edge1, x):
    t = min(1.0, max(0.0, (x - edge0) / (edge1 - edge0)))
    return t * t * (3 - 2 * t)


# ---- Centreline --------------------------------------------------------------

def catmull_rom_closed(points, per_span=32):
    out = []
    n = len(points)
    for i in range(n):
        p0, p1, p2, p3 = (points[(i + k - 1) % n] for k in range(4))
        for step in range(per_span):
            t = step / per_span
            t2, t3 = t * t, t * t * t
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2
                              + (-p0 + 3 * p1 - 3 * p2 + p3) * t3))
    return out


def resample_closed(points, spacing):
    lengths = [0.0]
    for i in range(len(points)):
        lengths.append(lengths[-1] + (points[(i + 1) % len(points)] - points[i]).length)
    total = lengths[-1]
    count = max(32, int(round(total / spacing)))
    samples, j = [], 0
    for k in range(count):
        target = total * k / count
        while lengths[j + 1] < target:
            j += 1
        a, b = points[j], points[(j + 1) % len(points)]
        span = lengths[j + 1] - lengths[j]
        samples.append(a.lerp(b, (target - lengths[j]) / span if span else 0.0))
    return samples, total


class Centreline:
    def __init__(self, samples, total):
        self.p = samples
        self.n = len(samples)
        self.total = total
        self.tangent = []
        for i in range(self.n):
            t = self.p[(i + 1) % self.n] - self.p[i - 1]
            t.z = 0.0
            self.tangent.append(t.normalized())
        self.tree = KDTree(self.n)
        for i, p in enumerate(self.p):
            self.tree.insert(Vector((p.x, p.y, 0.0)), i)
        self.tree.balance()

    def index_at(self, fraction):
        return int(round((fraction % 1.0) * self.n)) % self.n

    def frame(self, fraction, lateral=0.0):
        i = self.index_at(fraction)
        t = self.tangent[i]
        side = Vector((t.y, -t.x, 0.0))
        return self.p[i] + side * lateral, t

    def nearest(self, x, y):
        _, i, d = self.tree.find(Vector((x, y, 0.0)))
        return i, d

    def curvature_radius(self, i):
        a, b, c = self.p[i - 1].xy, self.p[i].xy, self.p[(i + 1) % self.n].xy
        ab, bc, ca = (b - a).length, (c - b).length, (a - c).length
        area2 = abs((b - a).x * (c - a).y - (b - a).y * (c - a).x)
        return float("inf") if area2 < 1e-6 else ab * bc * ca / (2 * area2)

    @staticmethod
    def yaw(t):
        # Track Lab: yaw 0 faces Blender +Y; rotation_euler.z = atan2(-tx, ty).
        return math.atan2(-t.x, t.y)


def ease_tight_curves(samples, minimum, spacing):
    """Locally smooth the spline wherever its radius is below `minimum`, then
    resample it evenly. Smoothing only widens a bend, so hand-tuning control
    points to fit a wide road becomes unnecessary for all but extreme layouts."""
    def radius(points, i):
        a, b, c = points[i - 1].xy, points[i].xy, points[(i + 1) % len(points)].xy
        area2 = abs((b - a).x * (c - a).y - (b - a).y * (c - a).x)
        return float("inf") if area2 < 1e-6 else (b - a).length * (c - b).length * (a - c).length / (2 * area2)

    points = [p.copy() for p in samples]
    n = len(points)
    for _ in range(400):
        tight = [i for i in range(n) if radius(points, i) < minimum]
        if not tight:
            break
        moved = set()
        for i in tight:
            for k in range(-3, 4):
                moved.add((i + k) % n)
        smoothed = [p.copy() for p in points]
        for i in moved:
            mid = (points[i - 1] + points[(i + 1) % n]) / 2
            smoothed[i] = points[i].lerp(mid, 0.5)
        points = smoothed
    return resample_closed(points, spacing)


def apply_crests(line, crests):
    """Raise the road into jump crests: a long climb and a short drop."""
    for fraction, height, length in crests:
        centre = line.index_at(fraction)
        span = max(2, int(length / (line.total / line.n)))
        for k in range(-span, span // 3 + 1):
            i = (centre + k) % line.n
            if k <= 0:
                lift = height * (1 - (k / span) ** 2)
            else:
                lift = height * (1 - k / (span / 3))
            line.p[i] = line.p[i] + Vector((0, 0, max(0.0, lift)))


def check_layout(line, spec):
    half = spec["road"] / 2
    where = min(range(line.n), key=line.curvature_radius)
    tightest = line.curvature_radius(where)
    if tightest < half * 1.6:
        p = line.p[where] / spec["scale"]
        raise SystemExit("a curve is too tight for a %d-wide road (radius %.0f at %.0f%% of the lap, "
                         "near layout point (%.0f, %.0f)); spread the points there or raise 'scale'"
                         % (spec["road"], tightest, 100.0 * where / line.n, p.x, p.y))
    clear = half + spec["runoff"]
    window = int(math.ceil(3 * clear / (line.total / line.n)))
    for i, p in enumerate(line.p):
        for _, j, distance in line.tree.find_range(Vector((p.x, p.y, 0.0)), 2 * clear + 200):
            if min((i - j) % line.n, (j - i) % line.n) > window:
                raise SystemExit("two stretches of road come within %.0f units near samples %d/%d; "
                                 "their run-off would overlap" % (distance, i, j))
    return tightest


# ---- Geometry ----------------------------------------------------------------

def terrain_height(line, spec, x, y):
    i, d = line.nearest(x, y)
    # The lowest road height within about a grid cell of here, less a margin:
    # terrain is interpolated straight across each 400-unit cell, so taking
    # the minimum keeps it under the road ribbon even where the road dips.
    reach = int(math.ceil(spec["cell"] * 1.5 / (line.total / line.n)))
    base = min(line.p[(i + k) % line.n].z for k in range(-reach, reach + 1)) - 30.0
    flat = spec["road"] / 2 + spec["runoff"]
    t = d - flat
    if t <= 0:
        return base, d
    roll = 0.5 + 0.5 * math.sin(x * 0.00061 + 1.3) * math.cos(y * 0.00047 + 0.4)
    hills = spec["hills"] * smoothstep(0, 1300, t) * (0.55 + 0.45 * roll)
    cliff = spec["cliff"] * smoothstep(1500, 1900, t)
    return base + hills + cliff, d


def runoff_widths(line, spec):
    """Per sample, how far the run-off reaches on each side. On the inside of
    a bend it is held inside the bend's radius (and eased along the road) so
    the ribbon can never fold over itself there."""
    full = spec["road"] / 2 + spec["runoff"]
    left, right = [], []
    for i in range(line.n):
        a, b = line.tangent[i - 1], line.tangent[(i + 1) % line.n]
        turn = a.x * b.y - a.y * b.x  # > 0 turns left, so the left side is inside
        limit = min(full, 0.85 * line.curvature_radius(i))
        left.append(limit if turn > 0 else full)
        right.append(limit if turn < 0 else full)
    def ease(values):
        span = 6
        return [min(values[(i + k) % line.n] for k in range(-span, span + 1)) for i in range(line.n)]
    return ease(left), ease(right)


def build_mesh(line, spec):
    bm = bmesh.new()
    mesh = bpy.data.meshes.new("track_source")
    material = bpy.data.materials.new("track")
    mesh.materials.append(material)

    # Road ribbon, five lines across: run-off edge, road edge, centre, road
    # edge, run-off edge. The run-off is on the ribbon too, so the grass a kart
    # runs onto is flush with the road.
    half = spec["road"] / 2
    left, right = runoff_widths(line, spec)
    rows = []
    for i in range(line.n):
        t = line.tangent[i]
        side = Vector((t.y, -t.x, 0.0))
        lateral = (-max(left[i], half + 40), -half, 0.0, half, max(right[i], half + 40))
        rows.append([bm.verts.new(line.p[i] + side * l) for l in lateral])
    for i in range(line.n):
        a, b = rows[i], rows[(i + 1) % line.n]
        for k in range(4):
            face = bm.faces.new((a[k], a[k + 1], b[k + 1], b[k]))
            face.normal_update()
            if face.normal.z < 0:
                face.normal_flip()

    # Terrain: a grid over the track's surroundings, cells beyond reach dropped.
    xs = [p.x for p in line.p]
    ys = [p.y for p in line.p]
    cell, margin = spec["cell"], spec["margin"]
    x0 = math.floor((min(xs) - margin) / cell) * cell
    y0 = math.floor((min(ys) - margin) / cell) * cell
    nx = int(math.ceil((max(xs) + margin - x0) / cell))
    ny = int(math.ceil((max(ys) + margin - y0) / cell))
    grid = {}
    for gx in range(nx + 1):
        for gy in range(ny + 1):
            x, y = x0 + gx * cell, y0 + gy * cell
            z, d = terrain_height(line, spec, x, y)
            grid[gx, gy] = (Vector((x, y, z)), d)
    verts = {}

    def vert(key):
        if key not in verts:
            verts[key] = bm.verts.new(grid[key][0])
        return verts[key]

    for gx in range(nx):
        for gy in range(ny):
            keys = [(gx, gy), (gx + 1, gy), (gx + 1, gy + 1), (gx, gy + 1)]
            face = bm.faces.new([vert(k) for k in keys])
            face.normal_update()
            if face.normal.z < 0:
                face.normal_flip()
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new("track_source", mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def classify(line, spec, polygon, world):
    centre = world @ polygon.center
    normal = (world.to_3x3() @ polygon.normal).normalized()
    i, d = line.nearest(centre.x, centre.y)
    on_ribbon = centre.z > line.p[i].z - 12  # the terrain under it is 30+ lower
    if on_ribbon and d < spec["road"] / 2:
        return "road"
    if on_ribbon and d < spec["road"] / 2 + spec["runoff"] + 5:
        return "runoff"
    if normal.z > 0.8:
        return "hill"
    return "slope" if normal.z > 0.55 else "cliff"


# ---- Main --------------------------------------------------------------------

def main():
    args = arguments()
    with open(args.layout, encoding="utf-8") as handle:
        spec = json.load(handle)
    for key, value in DEFAULTS.items():
        spec.setdefault(key, value)

    sys.path.insert(0, os.path.abspath(os.path.expanduser(args.track_lab)))
    import track_lab  # noqa: PLC0415
    from track_lab import prefs  # noqa: PLC0415
    from track_lab.operators import geometry as geometry_ops  # noqa: PLC0415
    from track_lab.operators.header import key_for  # noqa: PLC0415

    track_lab.register()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.dkr.asset_root = os.path.abspath(os.path.expanduser(args.assets))
    if prefs.resolve(bpy.context) is None:
        raise SystemExit("no Track Lab assets at %s" % args.assets)
    work = tempfile.mkdtemp(prefix="dkr-track-")
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(work, spec["id"] + ".blend"))

    control = [Vector((x * spec["scale"], y * spec["scale"], z)) for x, y, z in spec["points"]]
    samples, total = resample_closed(catmull_rom_closed(control), 140.0)
    samples, total = ease_tight_curves(samples, spec["road"] / 2 * 1.7, 140.0)
    line = Centreline(samples, total)
    apply_crests(line, spec["crests"])
    tightest = check_layout(line, spec)
    print("make_track: lap %.0f units, %d samples, tightest curve radius %.0f" % (total, line.n, tightest))

    source = build_mesh(line, spec)
    bpy.context.view_layer.objects.active = source
    source.select_set(True)
    if bpy.ops.dkr.track_from_mesh_blank(keep_source=False, keep_textures=False) != {"FINISHED"}:
        raise SystemExit("track_from_mesh_blank failed")
    track = geometry_ops.geometry_objects(bpy.context)[0]
    bpy.context.view_layer.objects.active = track

    bands = {}
    for polygon in track.data.polygons:
        bands.setdefault(classify(line, spec, polygon, track.matrix_world), []).append(polygon.index)
    for band, faces in sorted(bands.items()):
        wanted = set(faces)
        for polygon in track.data.polygons:
            polygon.select = polygon.index in wanted
        scene.dkr.texture_id = int(spec["textures"][band])
        scene.dkr.texture_surface = SURFACES[band]
        scene.dkr.texture_mapping = "PROJECT"
        scene.dkr.texture_scale = 320.0
        if bpy.ops.dkr.apply_texture() != {"FINISHED"}:
            raise SystemExit("apply_texture failed for %s" % band)
    print("make_track: faces " + ", ".join("%s=%d" % (k, len(v)) for k, v in sorted(bands.items())))

    scene.dkr.level_type = "RACE"
    scene.dkr.laps = int(spec["laps"])
    bpy.ops.dkr.header_defaults()
    scene[key_for("/music")] = int(spec["music"])
    scene[key_for("/background/skybox/id")] = spec["skybox"]
    scene.dkr.track_name = spec["name"]
    scene.dkr.track_id = spec["id"]

    def ground(x, y):
        return terrain_height(line, spec, x, y)[0] + 30.0

    def place(object_id, position, yaw, slot, up=0.0, **fields):
        scene.dkr.slot = slot
        scene.cursor.location = (position.x, position.y, position.z + up)
        if bpy.ops.dkr.place_object(object_id=object_id) != {"FINISHED"}:
            raise SystemExit("place_object failed for %s" % object_id)
        obj = bpy.context.view_layer.objects.active
        obj.rotation_euler.z = yaw
        for key, value in fields.items():
            obj[key] = value
        return obj

    grid_position, grid_tangent = line.frame(-300.0 / total)
    scene.cursor.location = grid_position + Vector((0, 0, 20))
    scene.cursor.rotation_euler = (0.0, 0.0, Centreline.yaw(grid_tangent))
    if bpy.ops.dkr.generate_start_grid(entrance=0, spacing=1.3, replace=True, drop=True) != {"FINISHED"}:
        raise SystemExit("generate_start_grid failed")
    count = int(spec["checkpoints"])
    for k in range(count):
        position, tangent = line.frame((k + 1) / count)
        place("ASSET_OBJECT_CHECKPOINT", position, Centreline.yaw(tangent), "structure", 40.0,
              index=k, scale=int(min(255, spec["road"] / 6)))
    for fraction in spec["zippers"]:
        for lateral in (-spec["road"] * 0.22, spec["road"] * 0.22):
            position, tangent = line.frame(fraction, lateral)
            place("ASSET_OBJECT_GROUNDZIPPER", position, Centreline.yaw(tangent), "structure", 4.0)
    for fraction, kind in spec["balloons"]:
        for lateral in (-0.32, -0.11, 0.11, 0.32):
            position, tangent = line.frame(fraction, spec["road"] * lateral)
            place("ASSET_OBJECT_WEAPONBALLOON", position, 0.0, "collectables", 16.0,
                  balloonType="BALLOON_TYPE_" + kind)
    for fraction in spec["bananas"]:
        for step in range(6):
            position, _ = line.frame(fraction + step * 80.0 / total, (step - 2.5) * spec["road"] * 0.12)
            place("ASSET_OBJECT_COIN", position, 0.0, "collectables", 30.0)
    # Trees and bushes just beyond the run-off, alternating sides.
    kinds = ["ASSET_OBJECT_BEACHTREE", "ASSET_OBJECT_BLUEBERRYBUSH", "ASSET_OBJECT_PALMPLANT"]
    fields = {"ASSET_OBJECT_BEACHTREE": {"modelIndex": 0, "radius": 82, "solid": 32},
              "ASSET_OBJECT_BLUEBERRYBUSH": {"modelIndex": 0, "radius": 34, "solid": 1},
              "ASSET_OBJECT_PALMPLANT": {"modelIndex": 0, "radius": 40, "solid": 1}}
    steps = int(total / spec["scenery"])
    for k in range(steps):
        fraction = (k + 0.5) / steps
        side = 1 if k % 2 else -1
        offset = side * (spec["road"] / 2 + spec["runoff"] + 220)
        position, _ = line.frame(fraction, offset)
        i, d = line.nearest(position.x, position.y)
        if d < spec["road"] / 2 + spec["runoff"]:  # another stretch of road is closer
            continue
        position.z = ground(position.x, position.y)
        kind = kinds[k % len(kinds)]
        place(kind, position, (k * 1.7) % (2 * math.pi), "structure", **fields[kind])

    if args.keep_blend:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(args.keep_blend))
    out = os.path.abspath(os.path.expanduser(args.out))
    os.makedirs(out, exist_ok=True)
    result = bpy.ops.dkr.export_dkrmap(filepath=os.path.join(out, spec["id"]), validate_first=True)
    print("make_track: %s -> %s" % (result, os.path.join(out, spec["id"] + ".dkrmap")))
    if result != {"FINISHED"}:
        raise SystemExit(1)


main()
