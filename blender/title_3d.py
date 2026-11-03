"""Real extruded, bevelled 3D title (Latin scripts; Bangla goes to the Three.js title_3d, which shapes text).

data: text, subtitle, font (file in .cache/fonts or a path), color, side (extrusion colour), depth (0.05..0.6),
      bevel (0..0.05), metallic (0..1), roughness, intro (rise|flip|spin|zoom), idle (sway|none),
      outro (true|false), glint (true|false), y (0..1 vertical centre), width (0..1 of the frame)
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy  # noqa: E402
import common as C  # noqa: E402

a = C.args()
d = a.data
text = str(d.get("text") or "TITLE")
if C.has_bangla(text) or C.has_bangla(d.get("subtitle", "")):
    raise SystemExit("Blender text objects do not shape Bangla: use the Three.js template title_3d instead.")

sc = C.reset(a)
color = d.get("color", "#ffffff")
side = d.get("side") or C.shade(color, 0.45)
front = C.material("Front", color, metallic=float(d.get("metallic", 0.2)), roughness=float(d.get("roughness", 0.3)))
sides = C.material("Side", side, metallic=float(d.get("metallic", 0.2)) + 0.3, roughness=0.25)


def make_text(body, size, depth, bevel, font):
    cu = bpy.data.curves.new("T", "FONT")
    cu.body = body
    cu.align_x, cu.align_y = "CENTER", "CENTER"
    cu.size = size
    cu.extrude = depth
    cu.bevel_depth = bevel
    cu.bevel_resolution = 4
    cu.resolution_u = 8
    if font:
        cu.font = bpy.data.fonts.load(font)
    ob = bpy.data.objects.new("T", cu)
    sc.collection.objects.link(ob)
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    bpy.ops.object.convert(target="MESH")
    ob = bpy.context.view_layer.objects.active
    ob.data.materials.append(front)
    ob.data.materials.append(sides)
    C.split_materials_by_normal(ob)
    ob.rotation_euler = (math.radians(90), 0, 0)          # stand up: front faces -Y (towards the camera)
    bpy.ops.object.select_all(action="DESELECT")
    return ob


font = C.font_path(d)
depth = float(d.get("depth", 0.25))
title = make_text(text, 1.0, depth, float(d.get("bevel", 0.02)), font)
parts = [title]
if d.get("subtitle"):
    sub = make_text(str(d["subtitle"]), 0.32, depth * 0.4, 0.006, C.font_path(d, "Poppins-SemiBold.ttf"))
    sub.location.z = -0.85
    parts.append(sub)

root = bpy.data.objects.new("Root", None)
sc.collection.objects.link(root)
for p in parts:
    p.parent = root

cam = C.camera(location=(0, -12, 0), target=(0, 0, 0), lens=50)
bpy.context.view_layer.update()
width = max(p.dimensions.x for p in parts)
vis_h = C.frustum_height(cam, 12)
vis_w = vis_h * a.width / a.height
target_w = float(d.get("width", 0.82)) * vis_w
s = target_w / max(width, 1e-3)
root.scale = (s, s, s)
root.location.z = (0.5 - float(d.get("y", 0.5))) * vis_h

key, fill, rim = C.studio_lights(scale=1.0, accent=d.get("rim") or d.get("accent"))

n = sc.frame_end
f_in = C.frame_of(a, min(0.7, a.duration * 0.3))
f_out = max(f_in + 1, n - C.frame_of(a, 0.45))
intro = d.get("intro", "rise")
z0 = root.location.z
if intro == "flip":
    C.ease_keys(root, "rotation_euler", [(1, math.radians(-95)), (f_in, 0.0)], index=0)
elif intro == "spin":
    C.ease_keys(root, "rotation_euler", [(1, math.radians(-200)), (f_in, 0.0)], index=2)
elif intro == "zoom":
    C.ease_keys(root, "scale", [(1, 0.01 * s), (f_in, s)], index=0)
    C.ease_keys(root, "scale", [(1, 0.01 * s), (f_in, s)], index=1)
    C.ease_keys(root, "scale", [(1, 0.01 * s), (f_in, s)], index=2)
else:   # rise
    C.ease_keys(root, "location", [(1, z0 - vis_h * 0.6), (f_in, z0)], index=2)
    C.ease_keys(root, "rotation_euler", [(1, math.radians(35)), (f_in, 0.0)], index=0)
if d.get("idle", "sway") == "sway":
    C.ease_keys(root, "rotation_euler", [(f_in, 0.0), ((f_in + f_out) // 2, math.radians(-9)), (f_out, math.radians(6))], index=2)
if d.get("outro", True):
    C.ease_keys(root, "location", [(f_out, z0), (n, z0 + vis_h * 0.7)], index=2)
    C.ease_keys(root, "rotation_euler", [(f_out, 0.0), (n, math.radians(-40))], index=0)
if d.get("glint", True):
    glint = C.area_light("Glint", (-vis_w, -5, 2), energy=1500, size=1.2)
    C.ease_keys(glint, "location", [(f_in, -vis_w), (min(f_out, f_in + C.frame_of(a, 0.9)), vis_w)], index=0)

C.render(a)
