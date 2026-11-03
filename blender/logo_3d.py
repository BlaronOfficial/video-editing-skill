"""A logo with real thickness: SVG paths extruded (their own fill colours on the front), or a PNG as a
thick die-cut card. Spins in, catches a light sweep, floats.

data: logo (path to .svg or .png), depth (0.02..0.4), side (edge colour), metallic, roughness,
      spin (turn|flip|none), tagline (text under it, Latin), y (0..1), width (0..1 of the frame)
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy  # noqa: E402
import common as C  # noqa: E402

a = C.args()
d = a.data
logo = d.get("logo")
if not logo or not os.path.exists(logo):
    raise SystemExit(f"logo file not found: {logo}")
sc = C.reset(a)
depth = float(d.get("depth", 0.12))
side_mat = C.material("Edge", d.get("side", "#c9ccd4"), metallic=0.8, roughness=0.25)


def from_svg(path):
    import addon_utils
    addon_utils.enable("io_curve_svg", default_set=True)
    before = set(bpy.data.objects)
    bpy.ops.import_curve.svg(filepath=path)
    curves = [o for o in bpy.data.objects if o not in before and o.type == "CURVE"]
    if not curves:
        raise SystemExit("the SVG had no paths Blender could import")
    for o in curves:
        o.data.extrude = depth * 0.05            # SVG units are tiny: scaled up below
        o.data.dimensions = "2D"
        o.data.fill_mode = "BOTH"
    bpy.ops.object.select_all(action="DESELECT")
    for o in curves:
        o.select_set(True)
    bpy.context.view_layer.objects.active = curves[0]
    bpy.ops.object.convert(target="MESH")
    bpy.ops.object.join()
    ob = bpy.context.view_layer.objects.active
    fronts = len(ob.data.materials)
    ob.data.materials.append(side_mat)
    for poly in ob.data.polygons:                 # caps keep their SVG fill; the walls get the edge material
        if abs(poly.normal.z) < 0.9:
            poly.material_index = fronts
    bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="BOUNDS")
    ob.location = (0, 0, 0)
    ob.rotation_euler = (math.radians(90), 0, 0)
    return ob


def from_png(path):
    img = bpy.data.images.load(path)
    w, h = img.size
    bpy.ops.mesh.primitive_plane_add(size=1)
    ob = bpy.context.view_layer.objects.active
    ob.scale = (w / max(w, h), h / max(w, h), 1)
    bpy.ops.object.transform_apply(scale=True)
    m = bpy.data.materials.new("Logo")
    m.use_nodes = True
    nt = m.node_tree
    p = nt.nodes.get("Principled BSDF")
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    nt.links.new(tex.outputs["Color"], p.inputs["Base Color"])
    nt.links.new(tex.outputs["Alpha"], p.inputs["Alpha"])
    p.inputs["Roughness"].default_value = float(d.get("roughness", 0.35))
    if hasattr(m, "blend_method"):
        m.blend_method = "CLIP" if hasattr(m, "alpha_threshold") else m.blend_method
    if hasattr(m, "surface_render_method"):
        m.surface_render_method = "DITHERED"
    ob.data.materials.append(m)
    ob.data.materials.append(side_mat)
    sol = ob.modifiers.new("Thick", "SOLIDIFY")
    sol.thickness = depth * 0.4
    sol.material_offset_rim = 1
    ob.rotation_euler = (math.radians(90), 0, 0)
    return ob


ob = from_svg(logo) if logo.lower().endswith(".svg") else from_png(logo)
root = bpy.data.objects.new("Root", None)
sc.collection.objects.link(root)
ob.parent = root
if d.get("tagline"):
    cu = bpy.data.curves.new("Tag", "FONT")
    cu.body = str(d["tagline"])
    cu.align_x, cu.align_y = "CENTER", "CENTER"
    cu.size = 0.16
    f = C.font_path(d, "Poppins-SemiBold.ttf")
    if f:
        cu.font = bpy.data.fonts.load(f)
    tag = bpy.data.objects.new("Tag", cu)
    sc.collection.objects.link(tag)
    tag.data.materials.append(C.material("TagMat", d.get("tag_color", "#ffffff")))
    tag.rotation_euler = (math.radians(90), 0, 0)
    tag.parent = root

cam = C.camera(location=(0, -12, 0), target=(0, 0, 0), lens=50)
bpy.context.view_layer.update()
vis_h = C.frustum_height(cam, 12)
vis_w = vis_h * a.width / a.height
dim = max(ob.dimensions.x, ob.dimensions.z, 1e-3)
s = float(d.get("width", 0.55)) * min(vis_w, vis_h) / dim
root.scale = (s, s, s)
if d.get("tagline"):
    tag.location.z = -(ob.dimensions.z / 2 + 0.25)
root.location.z = (0.5 - float(d.get("y", 0.45))) * vis_h
C.studio_lights(scale=1.0, accent=d.get("rim"))

n = sc.frame_end
f_in = C.frame_of(a, min(1.0, a.duration * 0.35))
spin = d.get("spin", "turn")
if spin == "turn":
    C.ease_keys(root, "rotation_euler", [(1, math.radians(-360)), (f_in, 0.0)], index=2)
    C.ease_keys(root, "scale", [(1, 0.2 * s), (f_in, s)], index=0)
    C.ease_keys(root, "scale", [(1, 0.2 * s), (f_in, s)], index=1)
    C.ease_keys(root, "scale", [(1, 0.2 * s), (f_in, s)], index=2)
elif spin == "flip":
    C.ease_keys(root, "rotation_euler", [(1, math.radians(-180)), (f_in, 0.0)], index=0)
z0 = root.location.z
C.ease_keys(root, "location", [(f_in, z0), ((f_in + n) // 2, z0 + vis_h * 0.015), (n, z0)], index=2)
C.ease_keys(root, "rotation_euler", [(f_in, 0.0), (n, math.radians(10))], index=2) if spin != "turn" else None
glint = C.area_light("Glint", (-vis_w, -5, 1.5), energy=1800, size=1.0)
C.ease_keys(glint, "location", [(f_in, -vis_w), (min(n, f_in + C.frame_of(a, 1.0)), vis_w)], index=0)

C.render(a)
