"""Fossil Pyramid: a Dino Domain battle arena in the spirit of Icicle Pyramid.

    blender -b --factory-startup --python tools/custom_tracks/make_fossil_pyramid.py -- \
        --track-lab ~/src/DKR-R/tools/blender --assets ~/dkr-assets --out custom-tracks

A wide walled sand arena:
- a two-tier temple pyramid in the middle (ramps up to tier 1 from the east
  and west, up to the summit from the north and south);
- four raised orange-stone mesas in the corners, each with its own ramp;
- a lava moat outside the walls and low volcanic hills beyond, so the view
  stays open;
- palms, bushes and torches;
- weapon balloons on every level, and an AI node graph tagged the way the
  battle AI expects (balloon nodes, recovery nodes).

Every ramp runs straight into the tier it climbs, so travel round each ring
is never blocked. Rails and walls are solid blocks with caps, so no edge is a
single paper-thin face.

Geometry is original and textured with retail textures by id (no ROM bytes of
its own). Each face's texture is recorded as it is built and matched back
after Track Lab converts the mesh. Coordinates are Blender's (z up), in map
units.
"""
import argparse
import math
import os
import sys
import tempfile

import bmesh
import bpy
from mathutils import Vector
from mathutils.kdtree import KDTree

ARENA = 4400            # half-width of the walled floor
WALL, WALL_T = 380, 120 # arena wall height and thickness
CELL = 400
T1, T1_Z = 2000, 300    # tier 1 half-width and height
T2, T2_Z = 800, 600     # tier 2 (summit)
MESA, MESA_Z, MESA_AT = 500, 300, 3300   # corner mesas: half-width, height, centre offset
RAIL, RAIL_T = 110, 50
MOAT_IN, MOAT_OUT, MOAT_Z = ARENA + WALL_T, 5600, -160
HILLS_OUT, HILLS_Z = 8400, 1100

TEXTURES = {
    "floor": 26,          # Sand
    "dry": 142,           # Sand Dry
    "bones": 809,         # Fossil Bone
    "tier": 174,          # Temple Brick Tile
    "summit": 252,        # Temple Stone Dino
    "temple_wall": 172,   # Temple Brick
    "ramp": 34,           # Yellow Stone
    "mesa": 168,          # Orange Stone
    "mesa_wall": 188,     # Orange Stone Wall Hillside
    "arena_wall": 68,     # Mossy Rock
    "lava": 16,           # Lava (animated)
    "hills": 202,         # Volcano Wall
}
DECORATION = {"lava", "hills"}

# Ramps: (axis, centre, half_width, start, end, z_start, z_end). The ramp runs
# along `axis` from `start` (low) to `end` (high), centred on `centre` across.
RAMPS = [
    ("x", 0, 300, 3150, T1, 0, T1_Z),          # floor -> tier 1, east
    ("x", 0, 300, -3150, -T1, 0, T1_Z),        # floor -> tier 1, west
    ("y", 0, 300, 1750, T2, T1_Z, T2_Z),       # tier 1 -> summit, north
    ("y", 0, 300, -1750, -T2, T1_Z, T2_Z),     # tier 1 -> summit, south
]
for _sx in (1, -1):
    for _sy in (1, -1):
        # Each mesa's ramp climbs towards it from the pyramid side, along y.
        RAMPS.append(("y", _sx * MESA_AT, 220, _sy * (MESA_AT - MESA - 900), _sy * (MESA_AT - MESA),
                      0, MESA_Z))

# Battle AI percentages (header 0x2A..0x33), as Icicle Pyramid has them.
AI_PERCENTAGES = [85, 90, 85, 100, 100, 20, 100, 0, 0, 0]


def arguments():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--track-lab", required=True, help="DKR-R's tools/blender folder")
    parser.add_argument("--assets", required=True, help="Track Lab asset folder")
    parser.add_argument("--out", required=True, help="folder to write the .dkrmap into")
    parser.add_argument("--keep-blend", default="", help="also save the .blend here")
    return parser.parse_args(argv)


# ---- Geometry ----------------------------------------------------------------

class Builder:
    """Collects faces with a texture band each, so bands survive conversion."""

    def __init__(self):
        self.bm = bmesh.new()
        self.mesh = bpy.data.meshes.new("arena_source")
        self.slots = {}
        self.verts = {}
        self.bands = []   # (triangle centroid, normal, band) for both splits of every face

    def material(self, category):
        if category not in self.slots:
            material = bpy.data.materials.new(category)
            if category != "solid":
                material["dkr_category"] = category
            self.mesh.materials.append(material)
            self.slots[category] = len(self.mesh.materials) - 1
        return self.slots[category]

    def vert(self, x, y, z):
        key = (round(x), round(y), round(z))
        if key not in self.verts:
            self.verts[key] = self.bm.verts.new(key)
        return self.verts[key]

    def face(self, corners, facing, band):
        """`facing` sets the side collision and drawing use (both are one-sided)."""
        verts = []
        for corner in corners:
            vert = self.vert(*corner)
            if vert not in verts:
                verts.append(vert)
        if len(verts) < 3:
            return
        try:
            face = self.bm.faces.new(verts)
        except ValueError:  # the same face built twice (shared seams)
            return
        face.normal_update()
        if face.normal.dot(Vector(facing)) < 0:
            face.normal_flip()
        category = "solid"
        if band in DECORATION:
            category = "decoration"
        elif band == "barrier":
            category = "invisible walls"
        face.material_index = self.material(category)
        points = [v.co.copy() for v in face.verts]
        normal = face.normal.copy()
        for tri in ((0, 1, 2), (0, 2, 3), (0, 1, 3), (1, 2, 3)):
            if max(tri) < len(points):
                self.bands.append((sum((points[k] for k in tri), Vector()) / 3, normal, band))

    def grid(self, x0, x1, y0, y1, z, band_of, skip=None):
        for x in range(x0, x1, CELL):
            for y in range(y0, y1, CELL):
                xe, ye = min(x + CELL, x1), min(y + CELL, y1)
                cx, cy = (x + xe) / 2, (y + ye) / 2
                if skip and skip(cx, cy):
                    continue
                self.face([(x, y, z), (xe, y, z), (xe, ye, z), (x, ye, z)], (0, 0, 1), band_of(cx, cy))

    def box_sides(self, half_x, half_y, cx, cy, z0, z1, band, facing_out=True, step=CELL, openings=()):
        """Vertical walls round a rectangle, facing out (or in), left open
        across `openings`: (axis, side, lo, hi), as for rails. A ramp arrives
        through an opening; a wall behind it would catch karts at its top edge."""
        s = 1 if facing_out else -1
        for axis in ("x", "y"):
            for sign in (1, -1):
                span = half_y if axis == "x" else half_x
                pieces = [(-span, span)]
                for g_axis, g_side, lo, hi in openings:
                    if g_axis == axis and g_side == sign:
                        cut = []
                        for a, b in pieces:
                            if lo > a:
                                cut.append((a, min(b, lo)))
                            if hi < b:
                                cut.append((max(a, hi), b))
                        pieces = cut
                for a0, b0 in pieces:
                    a = a0
                    while a < b0:
                        b = min(a + step, b0)
                        if axis == "y":   # the edge at y = cy + sign * half_y, running along x
                            y = cy + sign * half_y
                            corners = [(cx + a, y, z0), (cx + b, y, z0), (cx + b, y, z1), (cx + a, y, z1)]
                            facing = (0, s * sign, 0)
                        else:
                            x = cx + sign * half_x
                            corners = [(x, cy + a, z0), (x, cy + b, z0), (x, cy + b, z1), (x, cy + a, z1)]
                            facing = (s * sign, 0, 0)
                        self.face(corners, facing, band)
                        a = b

    def block(self, x0, y0, x1, y1, z0, z1, band):
        """A solid box: four sides and a top cap."""
        self.face([(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)], (0, 0, 1), band)
        self.face([(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)], (0, -1, 0), band)
        self.face([(x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1)], (0, 1, 0), band)
        self.face([(x0, y0, z0), (x0, y1, z0), (x0, y1, z1), (x0, y0, z1)], (-1, 0, 0), band)
        self.face([(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)], (1, 0, 0), band)

    def rails(self, half, cx, cy, z, gaps, step=CELL):
        """Solid rails round a platform's rim, just inside it, except across
        `gaps`: (axis, side, lo, hi) - the edge at axis = side * half, open
        between lo and hi along it, where a ramp arrives."""
        for axis in ("x", "y"):
            for side in (1, -1):
                pieces = [(-half, half)]
                for g_axis, g_side, lo, hi in gaps:
                    if g_axis == axis and g_side == side:
                        cut = []
                        for a, b in pieces:
                            if lo > a:
                                cut.append((a, min(b, lo)))
                            if hi < b:
                                cut.append((max(a, hi), b))
                        pieces = cut
                for a, b in pieces:
                    start = a
                    while start < b:
                        end = min(start + step, b)
                        rim = side * half
                        inner = rim - side * RAIL_T
                        if axis == "x":   # edge at x = rim, running along y
                            x0, x1 = sorted((cx + rim, cx + inner))
                            self.block(x0, cy + start, x1, cy + end, z, z + RAIL, "temple_wall")
                        else:             # edge at y = rim, running along x
                            y0, y1 = sorted((cy + rim, cy + inner))
                            self.block(cx + start, y0, cx + end, y1, z, z + RAIL, "temple_wall")
                        start = end

    def ramp(self, axis, centre, half_width, start, end, z0, z1, pieces=4):
        def point(along, across, z):
            return (along, across, z) if axis == "x" else (across, along, z)

        def side_facing(sign):
            return (0, sign, 0) if axis == "x" else (sign, 0, 0)

        edges = (centre - half_width, centre + half_width)
        for k in range(pieces):
            a = start + (end - start) * k / pieces
            b = start + (end - start) * (k + 1) / pieces
            za = z0 + (z1 - z0) * k / pieces
            zb = z0 + (z1 - z0) * (k + 1) / pieces
            self.face([point(a, edges[0], za), point(b, edges[0], zb), point(b, edges[1], zb),
                       point(a, edges[1], za)], (0, 0, 1), "ramp")
            for across, sign in ((edges[0], -1), (edges[1], 1)):
                # The ramp's side, down to the level it starts from.
                self.face([point(a, across, z0), point(b, across, z0), point(b, across, zb),
                           point(a, across, za)], side_facing(sign), "temple_wall")
                # A solid rail along it, ending one piece short of the top so a
                # racer can turn as it arrives.
                if k == pieces - 1:
                    continue
                inner = across - sign * RAIL_T
                self.face([point(a, across, za + RAIL), point(b, across, zb + RAIL),
                           point(b, inner, zb + RAIL), point(a, inner, za + RAIL)], (0, 0, 1), "temple_wall")
                self.face([point(a, inner, za), point(b, inner, zb), point(b, inner, zb + RAIL),
                           point(a, inner, za + RAIL)], side_facing(-sign), "temple_wall")
                self.face([point(a, across, za), point(b, across, zb), point(b, across, zb + RAIL),
                           point(a, across, za + RAIL)], side_facing(sign), "temple_wall")

    def ring(self, inner, outer, z_in, z_out, band, step=CELL):
        for a in range(-inner, inner, step):
            b = min(a + step, inner)
            ao, bo = a * outer / inner, b * outer / inner
            for s in (1, -1):
                self.face([(a, s * inner, z_in), (b, s * inner, z_in), (bo, s * outer, z_out), (ao, s * outer, z_out)],
                          (0, 0, 1), band)
                self.face([(s * inner, a, z_in), (s * inner, b, z_in), (s * outer, bo, z_out), (s * outer, ao, z_out)],
                          (0, 0, 1), band)

    def finish(self):
        self.bm.to_mesh(self.mesh)
        self.bm.free()
        obj = bpy.data.objects.new("arena_source", self.mesh)
        bpy.context.scene.collection.objects.link(obj)
        return obj


def floor_band(x, y):
    cell = (int(math.floor(x / CELL)), int(math.floor(y / CELL)))
    if (cell[0] * 3 + cell[1] * 7) % 13 == 0:
        return "bones"
    if (cell[0] - cell[1]) % 6 == 0 or (cell[0] + cell[1]) % 9 == 0:
        return "dry"
    return "floor"


def on_mesa(x, y):
    return any(abs(x - sx * MESA_AT) < MESA and abs(y - sy * MESA_AT) < MESA
               for sx in (1, -1) for sy in (1, -1))


def build_arena():
    b = Builder()
    # Floor, minus the pyramid's and the mesas' footprints.
    b.grid(-ARENA, ARENA, -ARENA, ARENA, 0, floor_band,
           skip=lambda x, y: (abs(x) < T1 and abs(y) < T1) or on_mesa(x, y))
    # Pyramid.
    b.grid(-T1, T1, -T1, T1, T1_Z, lambda x, y: "tier", skip=lambda x, y: abs(x) < T2 and abs(y) < T2)
    b.grid(-T2, T2, -T2, T2, T2_Z, lambda x, y: "summit" if abs(x) < CELL and abs(y) < CELL else "tier")
    b.box_sides(T1, T1, 0, 0, 0, T1_Z, "temple_wall", openings=[("x", 1, -300, 300), ("x", -1, -300, 300)])
    b.box_sides(T2, T2, 0, 0, T1_Z, T2_Z, "temple_wall", openings=[("y", 1, -300, 300), ("y", -1, -300, 300)])
    # Corner mesas, railed except where their ramp arrives (the pyramid side).
    for sx in (1, -1):
        for sy in (1, -1):
            cx, cy = sx * MESA_AT, sy * MESA_AT
            b.grid(cx - MESA, cx + MESA, cy - MESA, cy + MESA, MESA_Z, lambda x, y: "mesa")
            b.box_sides(MESA, MESA, cx, cy, 0, MESA_Z, "mesa_wall", step=MESA // 2,
                        openings=[("y", -sy, -220, 220)])
            b.rails(MESA, cx, cy, MESA_Z, [("y", -sy, -220, 220)], step=MESA // 2)
    for ramp in RAMPS:
        b.ramp(*ramp)
    # Pyramid rims, railed except where ramps arrive.
    b.rails(T1, 0, 0, T1_Z, [("x", 1, -300, 300), ("x", -1, -300, 300)])
    b.rails(T2, 0, 0, T2_Z, [("y", 1, -300, 300), ("y", -1, -300, 300)])
    # Arena wall: a solid block all round, with an invisible barrier above it.
    # Built in 800-unit lengths: one face may span at most 32 texture repeats.
    outer = ARENA + WALL_T
    for a in range(-outer, outer, 800):
        e = min(a + 800, outer)
        b.block(a, ARENA, e, outer, MOAT_Z, WALL, "arena_wall")
        b.block(a, -outer, e, -ARENA, MOAT_Z, WALL, "arena_wall")
    for a in range(-ARENA, ARENA, 800):
        e = min(a + 800, ARENA)
        b.block(ARENA, a, outer, e, MOAT_Z, WALL, "arena_wall")
        b.block(-outer, a, -ARENA, e, MOAT_Z, WALL, "arena_wall")
    b.box_sides(ARENA, ARENA, 0, 0, WALL, WALL + 1200, "barrier", facing_out=False)
    # Outside: the lava moat, then low volcanic hills.
    b.ring(MOAT_IN, MOAT_OUT, MOAT_Z, MOAT_Z, "lava")
    b.ring(MOAT_OUT, HILLS_OUT, MOAT_Z, HILLS_Z, "hills")
    return b


def match_bands(builder, arena):
    """Give each converted triangle the band of the source face it came from."""
    tree = KDTree(len(builder.bands))
    for i, (centre, _normal, _band) in enumerate(builder.bands):
        tree.insert(centre, i)
    tree.balance()
    world = arena.matrix_world
    bands = {}
    for polygon in arena.data.polygons:
        centre = world @ polygon.center
        normal = (world.to_3x3() @ polygon.normal).normalized()
        best = None
        for _co, index, _distance in tree.find_n(centre, 8):
            _c, source_normal, band = builder.bands[index]
            if abs(source_normal.dot(normal)) > 0.9:
                best = band
                break
        bands.setdefault(best or "floor", []).append(polygon.index)
    return bands


# ---- Objects -----------------------------------------------------------------

BALLOON_NODE, RECOVERY_NODE, WAYPOINT = 1, 3, 0
R = 2900          # floor ring radius for the node graph
MESA_FOOT = MESA_AT - MESA - 1050

# AI nodes: id -> (x, y, z, elevation band, tag, neighbours). Links both ways.
# Elevation: 0 floor, 1 tier 1 and mesa tops (both at 300), 2 summit.
# Tags (racer.c racer_ai_challenge; objects.c func_8001CD28):
#   1 a weapon balloon sits here - CPU racers path to these to arm themselves
#   3 a recovery point - a racer knocked onto another level heads for the
#     nearest one on that level, so every level needs one
#   0 an ordinary waypoint
AI_NODES = {
    # Floor ring (anticlockwise from east), passing the ramp feet.
    0: (3500, 0, 0, 0, WAYPOINT, [1, 11, 12]),           # foot of the east ramp
    1: (R, 1500, 0, 0, RECOVERY_NODE, [0, 2]),
    2: (2400, 2400, 0, 0, WAYPOINT, [1, 3, 20]),          # by the NE mesa's ramp
    3: (0, R, 0, 0, BALLOON_NODE, [2, 4]),
    4: (-2400, 2400, 0, 0, WAYPOINT, [3, 5, 21]),         # by the NW mesa's ramp
    5: (-R, 1500, 0, 0, WAYPOINT, [4, 6]),
    6: (-3500, 0, 0, 0, WAYPOINT, [5, 7, 13]),            # foot of the west ramp
    7: (-R, -1500, 0, 0, RECOVERY_NODE, [6, 8]),
    8: (-2400, -2400, 0, 0, WAYPOINT, [7, 9, 22]),        # by the SW mesa's ramp
    9: (0, -R, 0, 0, BALLOON_NODE, [8, 10]),
    10: (2400, -2400, 0, 0, WAYPOINT, [9, 11, 23]),       # by the SE mesa's ramp
    11: (R, -1500, 0, 0, WAYPOINT, [10, 0]),
    # Tier 1.
    12: (1600, 0, T1_Z, 1, RECOVERY_NODE, [0, 14, 15]),   # top of the east ramp
    13: (-1600, 0, T1_Z, 1, RECOVERY_NODE, [6, 16, 17]),  # top of the west ramp
    14: (1600, 1600, T1_Z, 1, BALLOON_NODE, [12, 18]),
    15: (1600, -1600, T1_Z, 1, BALLOON_NODE, [12, 19]),
    16: (-1600, 1600, T1_Z, 1, BALLOON_NODE, [13, 18]),
    17: (-1600, -1600, T1_Z, 1, BALLOON_NODE, [13, 19]),
    18: (0, 1880, T1_Z, 1, WAYPOINT, [14, 16, 24]),       # foot of the north summit ramp
    19: (0, -1880, T1_Z, 1, WAYPOINT, [15, 17, 25]),      # foot of the south summit ramp
    # Mesa ramp feet on the floor, then the mesa tops.
    20: (MESA_AT, MESA_FOOT, 0, 0, WAYPOINT, [2, 26]),
    21: (-MESA_AT, MESA_FOOT, 0, 0, WAYPOINT, [4, 27]),
    22: (-MESA_AT, -MESA_FOOT, 0, 0, WAYPOINT, [8, 28]),
    23: (MESA_AT, -MESA_FOOT, 0, 0, WAYPOINT, [10, 29]),
    24: (0, 500, T2_Z, 2, WAYPOINT, [18, 30]),
    25: (0, -500, T2_Z, 2, WAYPOINT, [19, 30]),
    26: (MESA_AT, MESA_AT, MESA_Z, 1, BALLOON_NODE, [20]),
    27: (-MESA_AT, MESA_AT, MESA_Z, 1, BALLOON_NODE, [21]),
    28: (-MESA_AT, -MESA_AT, MESA_Z, 1, BALLOON_NODE, [22]),
    29: (MESA_AT, -MESA_AT, MESA_Z, 1, BALLOON_NODE, [23]),
    # Summit.
    30: (0, 0, T2_Z, 2, RECOVERY_NODE, [24, 25, 31, 32]),
    31: (450, 0, T2_Z, 2, BALLOON_NODE, [30]),
    32: (-450, 0, T2_Z, 2, BALLOON_NODE, [30]),
}
BALLOON_TYPES = {3: "MISSILE", 9: "MISSILE", 14: "MISSILE", 15: "TRAP", 16: "TRAP", 17: "MISSILE",
                 26: "MISSILE", 27: "SHIELD", 28: "MISSILE", 29: "SHIELD", 31: "MISSILE", 32: "MAGNET"}
EXTRA_BALLOONS = [(3700, 2400, 0, "MISSILE"), (-3700, -2400, 0, "MISSILE"),
                  (-3700, 2400, 0, "TRAP"), (3700, -2400, 0, "TRAP")]
STARTS = [(3700, 1200), (-3700, -1200), (1200, -3700), (-1200, 3700)]


def main():
    args = arguments()
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
    work = tempfile.mkdtemp(prefix="dkr-arena-")
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(work, "fossil-pyramid.blend"))

    builder = build_arena()
    source = builder.finish()
    bpy.context.view_layer.objects.active = source
    source.select_set(True)
    if bpy.ops.dkr.track_from_mesh_blank(keep_source=False, keep_textures=False) != {"FINISHED"}:
        raise SystemExit("track_from_mesh_blank failed")
    arena = geometry_ops.geometry_objects(bpy.context)[0]
    bpy.context.view_layer.objects.active = arena

    bands = match_bands(builder, arena)
    for band, faces in sorted(bands.items()):
        if band == "barrier":
            continue
        wanted = set(faces)
        for polygon in arena.data.polygons:
            polygon.select = polygon.index in wanted
        scene.dkr.texture_id = TEXTURES[band]
        scene.dkr.texture_surface = "0"
        scene.dkr.texture_mapping = "PROJECT"
        scene.dkr.texture_scale = 256.0
        if bpy.ops.dkr.apply_texture() != {"FINISHED"}:
            raise SystemExit("apply_texture failed for %s" % band)
    print("fossil_pyramid: faces " + ", ".join("%s=%d" % (k, len(v)) for k, v in sorted(bands.items())))

    scene.dkr.level_type = "CHALLENGE"
    scene.dkr.challenge_type = "BATTLE"
    scene.dkr.vehicles = {"VEHICLE_CAR"}
    scene.dkr.default_vehicle = "VEHICLE_CAR"
    bpy.ops.dkr.header_defaults()
    scene[key_for("/music")] = 34
    scene[key_for("/background/skybox/id")] = "ASSET_OBJECT_DOME6"
    scene.dkr.track_name = "Fossil Pyramid"
    scene.dkr.track_id = "fossil-pyramid"

    def place(object_id, x, y, z, slot, yaw=0.0, **fields):
        scene.dkr.slot = slot
        scene.cursor.location = (x, y, z)
        if bpy.ops.dkr.place_object(object_id=object_id) != {"FINISHED"}:
            raise SystemExit("place_object failed for %s" % object_id)
        obj = bpy.context.view_layer.objects.active
        obj.rotation_euler.z = yaw
        for key, value in fields.items():
            obj[key] = value
        return obj

    for index, (x, y) in enumerate(STARTS):
        # yaw 0 faces +Y; this turns a racer at (x, y) towards the middle.
        place("ASSET_OBJECT_SETUPPOINT", x, y, 20, "structure", math.atan2(x, -y),
              racerIndex=index, entranceID=0)
    for node, (x, y, z, elevation, tag, neighbours) in AI_NODES.items():
        for other in neighbours:
            assert node in AI_NODES[other][5], "AI link %d->%d is one-way" % (node, other)
        assert len(neighbours) <= 4, node
        assert (tag == BALLOON_NODE) == (node in BALLOON_TYPES), "balloon node %d" % node
        place("ASSET_OBJECT_AINODE", x, y, z + 10, "collectables", nodeID=node, unk8=tag,
              adjacent=(neighbours + [255, 255, 255, 255])[:4], elevation=elevation)
    for elevation in (0, 1, 2):
        assert any(n[3] == elevation and n[4] == RECOVERY_NODE for n in AI_NODES.values()), elevation
    balloons = [(AI_NODES[n][0], AI_NODES[n][1], AI_NODES[n][2], kind) for n, kind in BALLOON_TYPES.items()]
    for x, y, z, kind in balloons + EXTRA_BALLOONS:
        # Retail balloons float about 16 units up: low enough to drive through.
        place("ASSET_OBJECT_WEAPONBALLOON", x, y, z + 16, "collectables", balloonType="BALLOON_TYPE_" + kind)
    for sx in (1, -1):
        for sy in (1, -1):
            place("ASSET_OBJECT_BEACHTREE", sx * 4000, sy * 4000, 0, "structure", modelIndex=0, radius=82, solid=32)
            place("ASSET_OBJECT_BEACHTREE", sx * 4000, sy * 2000, 0, "structure", modelIndex=0, radius=82, solid=32)
            place("ASSET_OBJECT_PALMPLANT", sx * 2000, sy * 4000, 0, "structure", modelIndex=0, radius=40, solid=1)
            place("ASSET_OBJECT_BLUEBERRYBUSH", sx * 1000, sy * 4100, 0, "structure", modelIndex=0, radius=34, solid=1)
            place("ASSET_OBJECT_FLAMINGTORCH", sx * (T2 - 120), sy * (T2 - 120), T2_Z, "structure",
                  animSpeed=7, radius=255)
            place("ASSET_OBJECT_FLAMINGTORCH", sx * (T1 - 120), sy * (T1 - 120), T1_Z, "structure",
                  animSpeed=7, radius=255)
            place("ASSET_OBJECT_FLAMINGTORCH", sx * (MESA_AT + MESA - 120), sy * (MESA_AT + MESA - 120),
                  MESA_Z, "structure", animSpeed=7, radius=255)

    if args.keep_blend:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(args.keep_blend))
    out = os.path.abspath(os.path.expanduser(args.out))
    os.makedirs(out, exist_ok=True)
    result = bpy.ops.dkr.export_dkrmap(filepath=os.path.join(out, "fossil-pyramid"), validate_first=True)
    print("fossil_pyramid: %s -> %s" % (result, os.path.join(out, "fossil-pyramid.dkrmap")))
    if result != {"FINISHED"}:
        raise SystemExit(1)
    # Track Lab has no field for the battle AI percentages; set them in place.
    with open(os.path.join(out, "fossil-pyramid.dkrmap", "header.bin"), "r+b") as handle:
        handle.seek(0x2A)
        handle.write(bytes(AI_PERCENTAGES))


main()
