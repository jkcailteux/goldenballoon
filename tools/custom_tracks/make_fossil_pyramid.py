"""Fossil Pyramid: a Dino Domain battle arena in the spirit of Icicle Pyramid.

    blender -b --factory-startup --python tools/custom_tracks/make_fossil_pyramid.py -- \
        --track-lab ~/src/DKR-R/tools/blender --assets ~/dkr-assets --out custom-tracks

A walled sand arena with a two-tier temple pyramid in the middle, ramps up
each tier, a lava moat and volcano cliffs beyond the walls, Dino Domain
scenery, missile balloons on every level and an AI node graph so the CPU
racers chase you up the pyramid. Original geometry, textured with retail
textures by id (no ROM bytes of its own); Track Lab does the model layout and
the object-map and header encoding.

Coordinates are Blender's (z up), in map units; Track Lab converts them.
"""
import argparse
import math
import os
import sys
import tempfile

import bmesh
import bpy
from mathutils import Vector

ARENA = 2800      # half-width of the walled floor
WALL = 450        # visible arena wall height
CELL = 400        # floor/tier tiling (keeps faces small for UVs and segments)
T1, T1_Z = 1200, 250   # tier 1 half-width and top height
T2, T2_Z = 800, 500    # tier 2 (top platform)
MOAT_OUT, MOAT_Z = 3600, 150
CLIFF_OUT, CLIFF_Z = 4600, 1700

TEXTURES = {
    "floor": 26,          # Sand
    "tracks": 142,        # Sand Dry (Dinosaur Tracks, 966, is a see-through decal: alone it reads as lava)
    "bones": 809,         # Fossil Bone
    "tier": 174,          # Temple Brick Tile
    "summit": 252,        # Temple Stone Dino
    "temple_wall": 172,   # Temple Brick
    "ramp": 34,           # Yellow Stone
    "arena_wall": 68,     # Mossy Rock
    "lava": 16,           # Lava (animated)
    "cliff": 202,         # Volcano Wall
}

RAIL = 120        # low rails on ramp sides and tier edges
# Ramps: (x0, x1, y_low, y_high, z_low, z_high, landing). A ramp rises from
# y_low towards y_high and is level for its last `landing` units, so the step
# across onto the platform beside it is flush.
RAMPS = [
    (-200, 200, 2100, T1, 0, T1_Z, 0),         # floor -> tier 1, north face
    (-200, 200, -2100, -T1, 0, T1_Z, 0),       # floor -> tier 1, south face
    (T2, T1, -600, 400, T1_Z, T2_Z, 200),      # tier 1 -> top, along the east side
    (-T1, -T2, 600, -400, T1_Z, T2_Z, 200),    # tier 1 -> top, along the west side
]
# Battle AI percentages (header 0x2A..0x33), as Icicle Pyramid has them: how
# often a CPU racer goes for balloons, chases, and attacks.
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
    def __init__(self):
        self.bm = bmesh.new()
        self.mesh = bpy.data.meshes.new("arena_source")
        self.slots = {}
        self.verts = {}

    def material(self, category):
        if category not in self.slots:
            material = bpy.data.materials.new(category)
            if category in ("decoration", "invisible walls"):
                material["dkr_category"] = category
            self.mesh.materials.append(material)
            self.slots[category] = len(self.mesh.materials) - 1
        return self.slots[category]

    def vert(self, x, y, z):
        key = (round(x), round(y), round(z))
        if key not in self.verts:
            self.verts[key] = self.bm.verts.new(key)
        return self.verts[key]

    def quad(self, corners, facing, category="solid"):
        """A face whose normal points along `facing` (collision is one-sided)."""
        verts = []
        for corner in corners:  # a ramp's lowest side piece collapses to a triangle
            vert = self.vert(*corner)
            if vert not in verts:
                verts.append(vert)
        if len(verts) < 3:
            return None
        face = self.bm.faces.new(verts)
        face.normal_update()
        if face.normal.dot(Vector(facing)) < 0:
            face.normal_flip()
        face.material_index = self.material(category)
        return face

    def floor_grid(self, x0, x1, y0, y1, z, skip=None):
        x = x0
        while x < x1:
            y = y0
            while y < y1:
                if not (skip and skip(x + CELL / 2, y + CELL / 2)):
                    self.quad([(x, y, z), (x + CELL, y, z), (x + CELL, y + CELL, z), (x, y + CELL, z)],
                              (0, 0, 1))
                y += CELL
            x += CELL

    def box_walls(self, half, z0, z1, facing_out, category="solid", step=CELL):
        sign = 1 if facing_out else -1
        for a in range(-half, half, step):
            b = a + step
            self.quad([(a, half, z0), (b, half, z0), (b, half, z1), (a, half, z1)], (0, sign, 0), category)
            self.quad([(a, -half, z0), (b, -half, z0), (b, -half, z1), (a, -half, z1)], (0, -sign, 0), category)
            self.quad([(half, a, z0), (half, b, z0), (half, b, z1), (half, a, z1)], (sign, 0, 0), category)
            self.quad([(-half, a, z0), (-half, b, z0), (-half, b, z1), (-half, a, z1)], (-sign, 0, 0), category)

    def ring(self, inner, outer, z_in, z_out, category, step=CELL):
        """A sloped band between two squares (moat and cliffs)."""
        for a in range(-inner, inner, step):
            b = a + step
            ao, bo = a * outer / inner, b * outer / inner
            for s in (1, -1):
                self.quad([(a, s * inner, z_in), (b, s * inner, z_in), (bo, s * outer, z_out), (ao, s * outer, z_out)],
                          (0, 0, 1), category)
                self.quad([(s * inner, a, z_in), (s * inner, b, z_in), (s * outer, bo, z_out), (s * outer, ao, z_out)],
                          (0, 0, 1), category)

    def ramp(self, x0, x1, y_low, y_high, z_low, z_high, landing, pieces=4):
        direction = 1 if y_high > y_low else -1
        y_top = y_high - direction * landing
        stations = [(y_low + (y_top - y_low) * k / pieces, z_low + (z_high - z_low) * k / pieces)
                    for k in range(pieces + 1)]
        if landing:
            stations.append((y_high, z_high))
        upper = z_low > 0
        for piece, ((ya, za), (yb, zb)) in enumerate(zip(stations, stations[1:])):
            # A floor ramp's rails stop one piece short of the tier, so a racer
            # arriving at the top can already turn towards a corner of the tier.
            last_floor_piece = not upper and piece == len(stations) - 2
            self.quad([(x0, ya, za), (x1, ya, za), (x1, yb, zb), (x0, yb, zb)], (0, 0, 1))
            for x, out in ((x0, -1), (x1, 1)):
                # Sides, down to the level the ramp starts from...
                self.quad([(x, ya, z_low), (x, yb, z_low), (x, yb, zb), (x, ya, za)], (out, 0, 0))
                # ...and a rail above the surface, facing the ramp. An upper ramp
                # runs along the top tier's wall on its inner side and is crossed
                # onto that tier from its landing, so it is railed outside only.
                inner = abs(x) == T2
                if not (upper and inner) and not last_floor_piece:
                    self.quad([(x, ya, za), (x, yb, zb), (x, yb, zb + RAIL), (x, ya, za + RAIL)], (-out, 0, 0))
        if upper:  # an upper ramp ends in a drop: close it, and rail the landing's end
            self.quad([(x0, y_high, z_low), (x1, y_high, z_low), (x1, y_high, z_high), (x0, y_high, z_high)],
                      (0, direction, 0))
            self.quad([(x0, y_high, z_high), (x1, y_high, z_high), (x1, y_high, z_high + RAIL),
                       (x0, y_high, z_high + RAIL)], (0, -direction, 0))

    def edge_rails(self, half, z, gaps):
        """Rails round a tier's edge, facing inward, except where `gaps` says
        (axis, side, lo, hi): a ramp arrives there."""
        for a in range(-half, half, CELL // 4):
            b = a + CELL // 4
            for axis in ("x", "y"):
                for side in (1, -1):
                    mid = (a + b) / 2
                    if any(g_axis == axis and g_side == side and lo <= mid <= hi
                           for g_axis, g_side, lo, hi in gaps):
                        continue
                    if axis == "y":  # the edge at y = side * half, running along x
                        corners = [(a, side * half, z), (b, side * half, z),
                                   (b, side * half, z + RAIL), (a, side * half, z + RAIL)]
                        facing = (0, -side, 0)
                    else:
                        corners = [(side * half, a, z), (side * half, b, z),
                                   (side * half, b, z + RAIL), (side * half, a, z + RAIL)]
                        facing = (-side, 0, 0)
                    self.quad(corners, facing)

    def finish(self):
        self.bm.to_mesh(self.mesh)
        self.bm.free()
        obj = bpy.data.objects.new("arena_source", self.mesh)
        bpy.context.scene.collection.objects.link(obj)
        return obj


def build_arena():
    b = Builder()
    b.floor_grid(-ARENA, ARENA, -ARENA, ARENA, 0, skip=lambda x, y: abs(x) < T1 and abs(y) < T1)
    b.floor_grid(-T1, T1, -T1, T1, T1_Z, skip=lambda x, y: abs(x) < T2 and abs(y) < T2)
    b.floor_grid(-T2, T2, -T2, T2, T2_Z)
    b.box_walls(T1, 0, T1_Z, facing_out=True)
    b.box_walls(T2, T1_Z, T2_Z, facing_out=True)
    b.box_walls(ARENA, 0, WALL, facing_out=False)
    b.box_walls(ARENA, WALL, WALL + 1100, facing_out=False, category="invisible walls")
    for ramp in RAMPS:
        b.ramp(*ramp)
    # Tier 1: open where the floor ramps arrive (north and south, |x| <= 200)
    # and along the east/west rings, where the upper ramps sit against the edge.
    b.edge_rails(T1, T1_Z, [("y", 1, -450, 450), ("y", -1, -450, 450),
                            ("x", 1, -600, 400), ("x", -1, -400, 600)])
    # The top: open only where the upper ramps' landings meet it.
    b.edge_rails(T2, T2_Z, [("x", 1, 200, 400), ("x", -1, -400, -200)])
    b.ring(ARENA, MOAT_OUT, MOAT_Z, MOAT_Z, "decoration")
    b.ring(MOAT_OUT, CLIFF_OUT, MOAT_Z, CLIFF_Z, "decoration")
    # The arena wall's outer face, down to the lava, so the moat has a bank.
    b.box_walls(ARENA, MOAT_Z, WALL, facing_out=True, category="decoration")
    return b.finish()


def band_of(centre, normal):
    x, y, z = centre
    edge = max(abs(x), abs(y))
    if edge > ARENA + 5:
        return "cliff" if z > MOAT_Z + 5 or abs(normal.z) < 0.9 else "lava"
    if abs(normal.z) < 0.5:
        if edge > ARENA - 5:
            if z > WALL + 5:
                return "barrier"
            return "arena_wall" if normal.dot(Vector((-x, -y, 0))) > 0 else "cliff"
        return "temple_wall"
    for x0, x1, y_low, y_high, z_low, z_high, _landing in RAMPS:
        lo, hi = sorted((y_low, y_high))
        if min(x0, x1) - 1 <= x <= max(x0, x1) + 1 and lo - 1 <= y <= hi + 1 and z > z_low + 1:
            return "ramp"
    if z > T2_Z - 5:
        return "summit" if abs(x) < CELL and abs(y) < CELL else "tier"
    if z > T1_Z - 5:
        return "tier"
    cell = (int(math.floor(x / CELL)), int(math.floor(y / CELL)))
    if (cell[0] - cell[1]) % 5 == 0:
        return "tracks"
    if (cell[0] * 3 + cell[1] * 7) % 11 == 0:
        return "bones"
    return "floor"


# ---- Objects -----------------------------------------------------------------

# AI nodes: id -> (x, y, z, elevation band, tag, neighbours). Links are listed
# both ways. The tag is the node's role for the battle AI (racer.c,
# racer_ai_challenge; objects.c, func_8001CD28), as Icicle Pyramid uses them:
#   1  a weapon balloon sits here: CPU racers path to these to arm themselves
#   3  a recovery point: a racer knocked onto another level heads for the
#      nearest one on that level, so every level needs at least one
#   0  an ordinary waypoint
BALLOON_NODE, RECOVERY_NODE, WAYPOINT = 1, 3, 0
AI_NODES = {
    0: (0, 2400, 0, 0, WAYPOINT, [1, 7, 8]),        # floor N (foot of the north ramp)
    1: (1900, 1900, 0, 0, BALLOON_NODE, [0, 2]),
    2: (2050, 0, 0, 0, RECOVERY_NODE, [1, 3]),
    3: (1900, -1900, 0, 0, BALLOON_NODE, [2, 4]),
    4: (0, -2400, 0, 0, WAYPOINT, [3, 5, 11]),      # floor S (foot of the south ramp)
    5: (-1900, -1900, 0, 0, BALLOON_NODE, [4, 6]),
    6: (-2050, 0, 0, 0, RECOVERY_NODE, [5, 7]),
    7: (-1900, 1900, 0, 0, BALLOON_NODE, [6, 0]),
    8: (0, 1000, T1_Z, 1, RECOVERY_NODE, [0, 9, 13]),   # tier 1 N (top of the north ramp)
    9: (1000, 1000, T1_Z, 1, BALLOON_NODE, [8]),        # tier 1 NE corner
    10: (1000, -1000, T1_Z, 1, WAYPOINT, [11, 14]),     # tier 1 SE (foot of the east ramp)
    11: (0, -1000, T1_Z, 1, RECOVERY_NODE, [4, 10, 12]),  # tier 1 S (top of the south ramp)
    12: (-1000, -1000, T1_Z, 1, BALLOON_NODE, [11]),    # tier 1 SW corner
    13: (-1000, 1000, T1_Z, 1, WAYPOINT, [8, 15]),      # tier 1 NW (foot of the west ramp)
    14: (1000, 300, T2_Z, 2, WAYPOINT, [10, 16]),       # east ramp's landing
    15: (-1000, -300, T2_Z, 2, WAYPOINT, [13, 17]),     # west ramp's landing
    16: (500, 300, T2_Z, 2, WAYPOINT, [14, 18, 19]),
    17: (-500, -300, T2_Z, 2, WAYPOINT, [15, 18, 20]),
    18: (0, 0, T2_Z, 2, RECOVERY_NODE, [16, 17, 19, 20]),   # summit
    19: (0, 500, T2_Z, 2, BALLOON_NODE, [16, 18]),
    20: (0, -500, T2_Z, 2, BALLOON_NODE, [17, 18]),
}

# Every balloon node gets a balloon on it; these are extras with no node.
BALLOON_TYPES = {1: "MISSILE", 3: "MISSILE", 5: "MISSILE", 7: "MISSILE",
                 9: "MISSILE", 12: "MISSILE", 19: "MISSILE", 20: "SHIELD"}
EXTRA_BALLOONS = [  # (x, y, z, type)
    (2300, 0, 0, "TRAP"), (-2300, 0, 0, "TRAP"), (1600, 1200, 0, "MISSILE"),
    (-1600, -1200, 0, "MISSILE"), (0, 1000, T1_Z, "SHIELD"), (0, 0, T2_Z, "MAGNET"),
]

STARTS = [(2200, 1500), (-2200, -1500), (1500, -2200), (-1500, 2200)]


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

    source = build_arena()
    bpy.context.view_layer.objects.active = source
    source.select_set(True)
    if bpy.ops.dkr.track_from_mesh_blank(keep_source=False, keep_textures=False) != {"FINISHED"}:
        raise SystemExit("track_from_mesh_blank failed")
    arena = geometry_ops.geometry_objects(bpy.context)[0]
    bpy.context.view_layer.objects.active = arena

    bands = {}
    world = arena.matrix_world
    for polygon in arena.data.polygons:
        centre = world @ polygon.center
        normal = (world.to_3x3() @ polygon.normal).normalized()
        bands.setdefault(band_of(centre, normal), []).append(polygon.index)
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

    # Header: a battle, cars only, Fire Mountain's sky and the battle theme.
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

    def face_centre(x, y):
        return math.atan2(x, -y)  # yaw 0 faces +Y; this turns a racer at (x, y) to the origin

    for index, (x, y) in enumerate(STARTS):
        place("ASSET_OBJECT_SETUPPOINT", x, y, 20, "structure", face_centre(x, y),
              racerIndex=index, entranceID=0)
    for node, (x, y, z, elevation, tag, neighbours) in AI_NODES.items():
        for other in neighbours:
            assert node in AI_NODES[other][5], "AI link %d->%d is one-way" % (node, other)
        assert (tag == BALLOON_NODE) == (node in BALLOON_TYPES), "balloon node %d" % node
        place("ASSET_OBJECT_AINODE", x, y, z + 10, "collectables", nodeID=node, unk8=tag,
              adjacent=(neighbours + [255, 255, 255, 255])[:4], elevation=elevation)
    for elevation in (0, 1, 2):
        assert any(n[3] == elevation and n[4] == RECOVERY_NODE for n in AI_NODES.values()), elevation
    balloons = [(AI_NODES[n][0], AI_NODES[n][1], AI_NODES[n][2], kind) for n, kind in BALLOON_TYPES.items()]
    for x, y, z, kind in balloons + EXTRA_BALLOONS:
        # Retail balloons float about 16 units up: low enough to drive through.
        place("ASSET_OBJECT_WEAPONBALLOON", x, y, z + 16, "collectables",
              balloonType="BALLOON_TYPE_" + kind)
    for sx in (1, -1):
        for sy in (1, -1):
            place("ASSET_OBJECT_BEACHTREE", sx * 2500, sy * 2500, 0, "structure",
                  modelIndex=0, radius=82, solid=32)
            place("ASSET_OBJECT_FLAMINGTORCH", sx * (T2 - 60), sy * (T2 - 60), T2_Z, "structure",
                  animSpeed=7, radius=255)
            place("ASSET_OBJECT_FLAMINGTORCH", sx * (T1 - 60), sy * (T1 - 60), T1_Z, "structure",
                  animSpeed=7, radius=255)
            for along in (-1300, 1300):
                place("ASSET_OBJECT_BLUEBERRYBUSH", sx * 2600, along, 0, "structure",
                      modelIndex=0, radius=34, solid=1)

    if args.keep_blend:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(args.keep_blend))
    out = os.path.abspath(os.path.expanduser(args.out))
    os.makedirs(out, exist_ok=True)
    result = bpy.ops.dkr.export_dkrmap(filepath=os.path.join(out, "fossil-pyramid"), validate_first=True)
    print("fossil_pyramid: %s -> %s" % (result, os.path.join(out, "fossil-pyramid.dkrmap")))
    if result != {"FINISHED"}:
        raise SystemExit(1)
    # Track Lab has no field for the battle AI percentages; set them in place.
    header_path = os.path.join(out, "fossil-pyramid.dkrmap", "header.bin")
    with open(header_path, "r+b") as handle:
        handle.seek(0x2A)
        handle.write(bytes(AI_PERCENTAGES))


main()
