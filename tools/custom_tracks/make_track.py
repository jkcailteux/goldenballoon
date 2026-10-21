"""Generate a brand-new race track from a closed spline, headless, via Track Lab.

    blender -b --factory-startup --python tools/custom_tracks/make_track.py -- \
        --track-lab ~/src/DKR-R/tools/blender --assets ~/dkr-assets \
        --layout tools/custom_tracks/layouts/canyon-loop.json --out custom-tracks

The layout file is JSON:

    {
      "name": "Canyon Loop", "id": "canyon-loop", "laps": 3,
      "scale": 0.55,                       # multiplies every control point's x/y
      "points": [[x, y, z], ...],          # closed loop, Blender axes (z up), map units
      "road": 600, "verge": 220, "wall": 320, "apron": 1400,
      "textures": {"road": 749, "verge": 65, "wall": 29, "apron": 65},
      "music": 31, "skybox": "ASSET_OBJECT_DOME13",
      "checkpoints": 20, "zippers": [0.12, 0.62],
      "balloons": [[0.25, "BALLOON_TYPE_BOOST"], [0.55, "BALLOON_TYPE_MISSILE"]],
      "bananas": [0.08, 0.35, 0.7]
    }

Positions along the lap ("zippers", "balloons", "bananas") are fractions of the
lap from the start line. The geometry is original: a road strip with grass
verges, walls and decorative canyon slopes, textured with RETAIL textures by
id, so the package ships no ROM bytes of its own. Track Lab does the level
model layout (segments, BSP, visibility, collision) and the object-map and
header encoding.
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


# ---- Centreline --------------------------------------------------------------

def catmull_rom_closed(points, per_span=24):
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
    """Even arc-length samples around a closed polyline."""
    lengths = [0.0]
    for i in range(len(points)):
        lengths.append(lengths[-1] + (points[(i + 1) % len(points)] - points[i]).length)
    total = lengths[-1]
    count = max(16, int(round(total / spacing)))
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

    def index_at(self, fraction):
        return int(round((fraction % 1.0) * self.n)) % self.n

    def frame(self, fraction, lateral=0.0, up=0.0):
        i = self.index_at(fraction)
        t = self.tangent[i]
        side = Vector((t.y, -t.x, 0.0))  # right-hand side when facing along t
        return self.p[i] + side * lateral + Vector((0, 0, up)), t

    @staticmethod
    def yaw(t):
        # Track Lab: yaw 0 faces Blender +Y; rotation_euler.z = atan2(-tx, ty).
        return math.atan2(-t.x, t.y)


def check_clearance(line, half_width):
    """Refuse layouts whose corridor would overlap itself."""
    tree = KDTree(line.n)
    for i, p in enumerate(line.p):
        tree.insert(Vector((p.x, p.y, 0.0)), i)
    tree.balance()
    window = int(math.ceil(2.5 * half_width / (line.total / line.n)))
    for i, p in enumerate(line.p):
        for _, j, distance in tree.find_range(Vector((p.x, p.y, 0.0)), 2 * half_width + 100):
            gap = min((i - j) % line.n, (j - i) % line.n)
            if gap > window:
                raise SystemExit("layout overlaps itself near sample %d/%d (%.0f units apart); "
                                 "spread the points or raise 'scale'" % (i, j, distance))


# ---- Geometry ----------------------------------------------------------------

def build_mesh(line, spec):
    road, verge, wall, apron = spec["road"] / 2, spec["verge"], spec["wall"], spec["apron"]
    edge = road + verge
    # Cross-section, left to right: (lateral, height above road, material).
    profile = [(-edge - apron, wall + 260), (-edge, wall), (-edge, 0.0), (-road, 0.0),
               (-road / 2, 0.0), (0.0, 0.0), (road / 2, 0.0), (road, 0.0),
               (edge, 0.0), (edge, wall), (edge + apron, wall + 260)]
    kinds = ["apron", "wall", "verge", "road", "road", "road", "road", "verge", "wall", "apron"]
    mesh = bpy.data.meshes.new("track_source")
    bm = bmesh.new()
    rings = []
    for i in range(line.n):
        t = line.tangent[i]
        side = Vector((t.y, -t.x, 0.0))
        rings.append([bm.verts.new(line.p[i] + side * lateral + Vector((0, 0, height)))
                      for lateral, height in profile])
    # An invisible barrier above each visible wall, so a hop or a boost can never
    # carry a kart over it onto the decorative slopes (which have no collision).
    barrier = []
    for i in range(line.n):
        t = line.tangent[i]
        side = Vector((t.y, -t.x, 0.0))
        barrier.append([bm.verts.new(line.p[i] + side * lateral + Vector((0, 0, wall + 900)))
                        for lateral in (-edge, edge)])
    materials = {}
    for name in ("road", "verge", "wall", "apron", "barrier"):
        material = bpy.data.materials.new(name)
        if name == "apron":
            material["dkr_category"] = "decoration"  # drawn, never collided with
        if name == "barrier":
            material["dkr_category"] = "invisible walls"  # collided with, never drawn
        mesh.materials.append(material)
        materials[name] = len(mesh.materials) - 1
    faces = []
    for i in range(line.n):
        j = (i + 1) % line.n
        a, b = rings[i], rings[j]
        for k, kind in enumerate(kinds):
            face = bm.faces.new((a[k], a[k + 1], b[k + 1], b[k]))
            face.material_index = materials[kind]
            faces.append((face, kind, i))
        for column, k in ((0, 1), (1, 9)):  # wall tops: profile points 1 and 9
            face = bm.faces.new((a[k], barrier[i][column], barrier[j][column], b[k]))
            face.material_index = materials["barrier"]
            faces.append((face, "barrier", i))
    bm.normal_update()
    # Collision is one-sided: floors must face up and walls must face the road,
    # or a kart drives straight through the wall from the road side.
    for face, kind, i in faces:
        if kind in ("road", "verge"):
            if face.normal.z < 0:
                face.normal_flip()
        elif kind in ("wall", "barrier"):
            toward = line.p[i] - face.calc_center_median()
            toward.z = 0.0
            if face.normal.dot(toward) < 0:
                face.normal_flip()
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new("track_source", mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def classify(line, spec, polygon, world):
    """Which band a converted face belongs to, from where it sits."""
    centre = world @ polygon.center
    normal = (world.to_3x3() @ polygon.normal).normalized()
    nearest = min(range(line.n), key=lambda i: (line.p[i].xy - centre.xy).length_squared)
    lateral = (line.p[nearest].xy - centre.xy).length
    if lateral > spec["road"] / 2 + spec["verge"] + 1:
        return "apron"
    if abs(normal.z) < 0.5:
        # Above the visible wall top is the invisible barrier: leave it untextured.
        return "barrier" if centre.z > line.p[nearest].z + spec["wall"] + 20 else "wall"
    return "road" if lateral <= spec["road"] / 2 + 1 else "verge"


# ---- Main --------------------------------------------------------------------

def main():
    args = arguments()
    with open(args.layout, encoding="utf-8") as handle:
        spec = json.load(handle)
    defaults = {"laps": 3, "scale": 1.0, "road": 600, "verge": 220, "wall": 320, "apron": 1400,
                "textures": {"road": 749, "verge": 65, "wall": 29, "apron": 65},
                "music": 31, "skybox": "ASSET_OBJECT_DOME13", "checkpoints": 20,
                "zippers": [], "balloons": [], "bananas": []}
    for key, value in defaults.items():
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
    samples, total = resample_closed(catmull_rom_closed(control), 110.0)
    line = Centreline(samples, total)
    half = spec["road"] / 2 + spec["verge"]
    check_clearance(line, half)
    print("make_track: lap length %.0f units, %d samples" % (total, line.n))

    # Geometry -> Track Lab level model (segments, BSP, collision).
    source = build_mesh(line, spec)
    bpy.context.view_layer.objects.active = source
    source.select_set(True)
    result = bpy.ops.dkr.track_from_mesh_blank(keep_source=False, keep_textures=False)
    if result != {"FINISHED"}:
        raise SystemExit("track_from_mesh_blank failed: %s" % result)
    track = geometry_ops.geometry_objects(bpy.context)[0]
    bpy.context.view_layer.objects.active = track

    surfaces = {"road": "0", "verge": "1", "wall": "0", "apron": "1"}
    bands = {}
    for polygon in track.data.polygons:
        bands.setdefault(classify(line, spec, polygon, track.matrix_world), []).append(polygon.index)
    for band, faces in bands.items():
        if band == "barrier":
            continue
        wanted = set(faces)
        for polygon in track.data.polygons:
            polygon.select = polygon.index in wanted
        scene.dkr.texture_id = int(spec["textures"][band])
        scene.dkr.texture_surface = surfaces[band]
        scene.dkr.texture_mapping = "PROJECT"
        scene.dkr.texture_scale = 256.0
        if bpy.ops.dkr.apply_texture() != {"FINISHED"}:
            raise SystemExit("apply_texture failed for %s" % band)
    print("make_track: faces " + ", ".join("%s=%d" % (k, len(v)) for k, v in sorted(bands.items())))

    # Header.
    scene.dkr.level_type = "RACE"
    scene.dkr.laps = int(spec["laps"])
    bpy.ops.dkr.header_defaults()
    scene[key_for("/music")] = int(spec["music"])
    scene[key_for("/background/skybox/id")] = spec["skybox"]
    scene.dkr.track_name = spec["name"]
    scene.dkr.track_id = spec["id"]

    def place(object_id, fraction, slot, lateral=0.0, up=0.0, **fields):
        position, tangent = line.frame(fraction, lateral, up)
        scene.dkr.slot = slot
        scene.cursor.location = position
        if bpy.ops.dkr.place_object(object_id=object_id) != {"FINISHED"}:
            raise SystemExit("place_object failed for %s" % object_id)
        obj = bpy.context.view_layer.objects.active
        obj.rotation_euler.z = Centreline.yaw(tangent)
        for key, value in fields.items():
            obj[key] = value
        return obj

    # Start grid just behind the line; checkpoint N-1 sits on the line itself.
    grid_position, grid_tangent = line.frame(-250.0 / total, up=20.0)
    scene.cursor.location = grid_position
    scene.cursor.rotation_euler = (0.0, 0.0, Centreline.yaw(grid_tangent))
    if bpy.ops.dkr.generate_start_grid(entrance=0, spacing=1.0, replace=True, drop=True) != {"FINISHED"}:
        raise SystemExit("generate_start_grid failed")
    count = int(spec["checkpoints"])
    for k in range(count):
        place("ASSET_OBJECT_CHECKPOINT", (k + 1) / count, "structure", up=40.0,
              index=k, scale=100)
    for fraction in spec["zippers"]:
        place("ASSET_OBJECT_GROUNDZIPPER", fraction, "structure", up=4.0)
    for fraction, kind in spec["balloons"]:
        for lateral in (-spec["road"] * 0.3, 0.0, spec["road"] * 0.3):
            place("ASSET_OBJECT_WEAPONBALLOON", fraction, "collectables", lateral, 60.0,
                  balloonType=kind)
    for fraction in spec["bananas"]:
        for step in range(5):
            place("ASSET_OBJECT_COIN", fraction + step * 60.0 / total, "collectables",
                  (step - 2) * spec["road"] * 0.12, 30.0)

    if args.keep_blend:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(args.keep_blend))
    out = os.path.abspath(os.path.expanduser(args.out))
    os.makedirs(out, exist_ok=True)
    result = bpy.ops.dkr.export_dkrmap(filepath=os.path.join(out, spec["id"]), validate_first=True)
    print("make_track: %s -> %s" % (result, os.path.join(out, spec["id"] + ".dkrmap")))
    if result != {"FINISHED"}:
        raise SystemExit(1)


main()
