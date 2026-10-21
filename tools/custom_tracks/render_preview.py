"""Render overview images of a generated track's geometry, for checking edges.

    blender -b <track>.blend --python tools/custom_tracks/render_preview.py -- OUT_PREFIX

Writes OUT_PREFIX-top.png (orthographic, straight down) and OUT_PREFIX-ne/nw/se/sw.png
(perspective from each corner, high up), lit flat with textures, from the track
object Track Lab built. Map objects (balloons, checkpoints) are hidden.
"""
import math
import sys

import bpy
from mathutils import Vector

prefix = sys.argv[sys.argv.index("--") + 1]
scene = bpy.context.scene
track = next(o for o in scene.objects if o.type == "MESH" and o.get("dkr_geometry"))
for obj in scene.objects:
    obj.hide_render = obj is not track

corners = [track.matrix_world @ Vector(c) for c in track.bound_box]
low = Vector([min(c[i] for c in corners) for i in range(3)])
high = Vector([max(c[i] for c in corners) for i in range(3)])
centre = (low + high) / 2
size = max(high.x - low.x, high.y - low.y)

scene.render.engine = "BLENDER_WORKBENCH"
scene.display.shading.light = "STUDIO"
scene.display.shading.color_type = "TEXTURE"
scene.display.shading.show_cavity = True
scene.render.resolution_x = 1280
scene.render.resolution_y = 960
scene.render.film_transparent = False
scene.world = scene.world or bpy.data.worlds.new("preview")

camera_data = bpy.data.cameras.new("preview")
camera = bpy.data.objects.new("preview", camera_data)
scene.collection.objects.link(camera)
scene.camera = camera
camera_data.clip_end = size * 10


def shoot(name):
    scene.render.filepath = "%s-%s.png" % (prefix, name)
    bpy.ops.render.render(write_still=True)


camera_data.type = "ORTHO"
camera_data.ortho_scale = size * 1.05
camera.location = (centre.x, centre.y, high.z + size)
camera.rotation_euler = (0.0, 0.0, 0.0)
shoot("top")

camera_data.type = "PERSP"
camera_data.lens = 28
for name, (sx, sy) in {"ne": (1, 1), "nw": (-1, 1), "se": (1, -1), "sw": (-1, -1)}.items():
    eye = centre + Vector((sx * size * 0.55, sy * size * 0.55, size * 0.38))
    camera.location = eye
    direction = centre - eye
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    shoot(name)
print("render_preview: wrote %s-{top,ne,nw,se,sw}.png" % prefix)
