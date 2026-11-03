"""Product turntable: a 3D model (.glb/.gltf/.obj/.fbx/.stl) or a cut-out photo as a thin card, turning
on a soft studio set with a rim light in the accent colour.

data: model (path) | image (path, transparent PNG works best), turns (0.25..2), accent (#hex rim light),
      floor (disc|none), disc_color, tilt (degrees the camera looks down), y (0..1), width (0..1)
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402
import common as C  # noqa: E402

a = C.args()
d = a.data
sc = C.reset(a)
root = bpy.data.objects.new("Root", None)
sc.collection.objects.link(root)


def import_model(path):
    ext = os.path.splitext(path)[1].lower()
    before = set(bpy.data.objects)
    if ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=path)
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    elif ext == ".stl":
        bpy.ops.wm.stl_import(filepath=path)
    else:
        raise SystemExit(f"unsupported model format {ext}")
    new = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in new if o.type == "MESH"]
    if not meshes:
        raise SystemExit("the model has no meshes")
    for o in new:
        if o.parent is None:
            o.parent = root
    bpy.context.view_layer.update()
    pts = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


def image_card(path):
    img = bpy.data.images.load(path)
    w, h = img.size
    bpy.ops.mesh.primitive_plane_add(size=1)
    ob = bpy.context.view_layer.objects.active
    ob.scale = (w / max(w, h), h / max(w, h), 1)
    bpy.ops.object.transform_apply(scale=True)
    m = bpy.data.materials.new("Card")
    m.use_nodes = True
    nt = m.node_tree
    p = nt.nodes.get("Principled BSDF")
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    nt.links.new(tex.outputs["Color"], p.inputs["Base Color"])
    nt.links.new(tex.outputs["Alpha"], p.inputs["Alpha"])
    p.inputs["Roughness"].default_value = 0.4
    if hasattr(m, "surface_render_method"):
        m.surface_render_method = "DITHERED"
    ob.data.materials.append(m)
    sol = ob.modifiers.new("Thick", "SOLIDIFY")
    sol.thickness = 0.01
    ob.rotation_euler = (math.radians(90), 0, 0)
    ob.location.z = ob.dimensions.y / 2 if ob.dimensions.y else 0.5
    ob.parent = root
    bpy.context.view_layer.update()
    return Vector((-0.5, -0.01, 0)), Vector((0.5, 0.01, h / max(w, h)))


if d.get("model"):
    lo, hi = import_model(d["model"])
elif d.get("image"):
    lo, hi = image_card(d["image"])
else:
    raise SystemExit("give data.model or data.image")

size = max(hi - lo)
centre = (lo + hi) / 2
holder = bpy.data.objects.new("Holder", None)          # normalised: unit height, centred, sitting on z=0
sc.collection.objects.link(holder)
root.parent = holder
root.location = (-centre.x, -centre.y, -lo.z)
holder.scale = [1.0 / size] * 3

if d.get("floor", "disc") == "disc":
    bpy.ops.mesh.primitive_cylinder_add(radius=0.75, depth=0.03, vertices=96, location=(0, 0, -0.015))
    disc = bpy.context.view_layer.objects.active
    disc.data.materials.append(C.material("Disc", d.get("disc_color", "#1d1f26"), metallic=0.1, roughness=0.18))

tilt = math.radians(float(d.get("tilt", 14)))
dist = 4.2
cam = C.camera(location=(0, -dist * math.cos(tilt), 0.45 + dist * math.sin(tilt)), target=(0, 0, 0.45), lens=50)
vis_h = C.frustum_height(cam, dist)
fit = float(d.get("width", 0.7)) * min(vis_h * a.width / a.height, vis_h) / 1.0
holder.scale = [fit / size] * 3
cam.location.z += (float(d.get("y", 0.5)) - 0.5) * vis_h
C.studio_lights(scale=0.6, accent=d.get("accent", "#ffffff"))

n = sc.frame_end
turns = float(d.get("turns", 0.5))
holder.rotation_euler.z = 0.0
holder.keyframe_insert("rotation_euler", index=2, frame=1)
holder.rotation_euler.z = 2 * math.pi * turns
holder.keyframe_insert("rotation_euler", index=2, frame=n)
for fc in C.fcurves(holder.animation_data.action):
    for kp in fc.keyframe_points:
        kp.interpolation = "LINEAR" if turns >= 1 else "BEZIER"

C.render(a)
