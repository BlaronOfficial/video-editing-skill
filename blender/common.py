"""Shared helpers for vedit's Blender templates (run inside Blender: `blender -b -P <template>.py -- ...`).

Contract (same as CustomFX kind=blender):
  -- --params p.json --out <frames dir> --width W --height H --fps F --duration D [--engine eevee|cycles]
     [--samples N] [--still T]
The template renders RGBA PNG frames (transparent background) named f_00001.png ... into --out;
vedit encodes them (WebM alpha, ProRes 4444, green key) like any other graphic.
Colour management is "Standard" so brand colours come out as given.
"""

import argparse
import json
import math
import os
import sys

import bpy
from mathutils import Vector


def args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--params", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--width", type=int, default=1080)
    ap.add_argument("--height", type=int, default=1920)
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--duration", type=float, default=3.0)
    ap.add_argument("--engine", default="eevee")
    ap.add_argument("--samples", type=int, default=0)
    ap.add_argument("--still", type=float, default=None)
    a = ap.parse_args(argv)
    a.data = {}
    if a.params and os.path.exists(a.params):
        with open(a.params, encoding="utf-8") as f:
            a.data = json.load(f)
    return a


def hex_rgba(c, a=1.0):
    c = str(c or "#ffffff").lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    srgb = [int(c[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in srgb]
    return (*lin, a)


def shade(c, k):
    """Darker (k < 1) or lighter (k > 1) version of a hex colour."""
    c = str(c or "#ffffff").lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    rgb = [min(255, int(int(c[i:i + 2], 16) * k)) for i in (0, 2, 4)]
    return "#" + "".join(f"{v:02x}" for v in rgb)


def reset(a, *, transparent=True):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.resolution_x, sc.render.resolution_y = a.width, a.height
    sc.render.resolution_percentage = 100
    fps = a.fps
    sc.render.fps = max(1, int(round(fps)))
    sc.render.fps_base = sc.render.fps / fps          # 29.97 -> 30 / 1.001 (vedit encodes at the exact rate anyway)
    sc.frame_start = 1
    sc.frame_end = max(1, int(round(a.duration * fps)))
    sc.render.film_transparent = transparent
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGBA"
    sc.render.image_settings.color_depth = "8"
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.look = "None"
    engines = [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items]
    want = "CYCLES" if a.engine == "cycles" else next((e for e in engines if e.startswith("BLENDER_EEVEE")), engines[0])
    try:
        sc.render.engine = want
    except TypeError:
        sc.render.engine = engines[0]
    if sc.render.engine == "CYCLES":
        sc.cycles.samples = a.samples or 64
        sc.cycles.use_denoising = True
        sc.cycles.device = "CPU"
    else:
        ee = sc.eevee
        if hasattr(ee, "taa_render_samples"):
            ee.taa_render_samples = a.samples or 32
        for prop in ("use_shadows", "use_raytracing"):
            if hasattr(ee, prop):
                setattr(ee, prop, True)
    world = bpy.data.worlds.new("World")
    sc.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    bg.inputs[0].default_value = (0.05, 0.05, 0.06, 1)
    bg.inputs[1].default_value = 0.6
    return sc


def material(name, color, *, metallic=0.0, roughness=0.35, emission=None, emission_strength=0.0, alpha=1.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    p = m.node_tree.nodes.get("Principled BSDF")
    p.inputs["Base Color"].default_value = hex_rgba(color)
    p.inputs["Metallic"].default_value = metallic
    p.inputs["Roughness"].default_value = roughness
    if "Coat Weight" in p.inputs:
        p.inputs["Coat Weight"].default_value = 0.25
    if emission:
        key = "Emission Color" if "Emission Color" in p.inputs else "Emission"
        p.inputs[key].default_value = hex_rgba(emission)
        p.inputs["Emission Strength"].default_value = emission_strength
    if alpha < 1:
        p.inputs["Alpha"].default_value = alpha
    return m


def look_at(obj, target):
    d = Vector(target) - obj.location
    obj.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


def camera(location=(0, -10, 0), target=(0, 0, 0), lens=50):
    cam_data = bpy.data.cameras.new("Camera")
    cam_data.lens = lens
    cam = bpy.data.objects.new("Camera", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    cam.location = location
    look_at(cam, target)
    bpy.context.scene.camera = cam
    return cam


def area_light(name, location, target=(0, 0, 0), energy=500, size=4.0, color="#ffffff"):
    ld = bpy.data.lights.new(name, "AREA")
    ld.energy = energy
    ld.size = size
    ld.color = hex_rgba(color)[:3]
    lo = bpy.data.objects.new(name, ld)
    bpy.context.scene.collection.objects.link(lo)
    lo.location = location
    look_at(lo, target)
    return lo


def studio_lights(scale=1.0, accent=None):
    key = area_light("Key", (4 * scale, -6 * scale, 5 * scale), energy=900 * scale * scale, size=5 * scale)
    fill = area_light("Fill", (-6 * scale, -4 * scale, 2 * scale), energy=300 * scale * scale, size=6 * scale)
    rim = area_light("Rim", (0, 6 * scale, 4 * scale), energy=700 * scale * scale, size=4 * scale, color=accent or "#ffffff")
    return key, fill, rim


def frame_of(a, t):
    return 1 + int(round(t * a.fps))


def ease_keys(obj, path, keys, index=-1):
    """keys: [(frame, value)] with Bezier easing (ease in/out) between them."""
    for f, v in keys:
        setattr_path(obj, path, v, index)
        obj.keyframe_insert(data_path=path, frame=f, index=index)
    ad = obj.animation_data
    if ad and ad.action:
        for fc in fcurves(ad.action):
            for kp in fc.keyframe_points:
                kp.interpolation = "BEZIER"
                kp.easing = "AUTO"


def fcurves(action):
    if hasattr(action, "fcurves"):
        return list(action.fcurves)
    out = []                                    # Blender 5 layered actions
    for layer in getattr(action, "layers", []):
        for strip in layer.strips:
            for bag in getattr(strip, "channelbags", []):
                out.extend(bag.fcurves)
    return out


def setattr_path(obj, path, v, index):
    if index >= 0:
        getattr(obj, path)[index] = v
    else:
        setattr(obj, path, v)


def frustum_height(cam, distance):
    """Visible height at `distance` (sensor fit AUTO: the sensor width spans the larger image side)."""
    sc = bpy.context.scene
    w, h = sc.render.resolution_x, sc.render.resolution_y
    span = distance * cam.data.sensor_width / cam.data.lens
    return span if h >= w else span * h / w


def font_path(data, fallback="Poppins-ExtraBold.ttf"):
    name = data.get("font") or fallback
    if os.path.isabs(name) and os.path.exists(name):
        return name
    for d in (data.get("fonts_dir") or "",):
        for cand in (name, name + ".ttf", name.replace(" ", "") + "-Regular.ttf", name.replace(" ", "") + "-Bold.ttf"):
            p = os.path.join(d, cand)
            if d and os.path.exists(p):
                return p
    p = os.path.join(data.get("fonts_dir") or "", fallback)
    return p if os.path.exists(p) else None


def has_bangla(text):
    return any("ঀ" <= ch <= "৿" for ch in text or "")


def split_materials_by_normal(obj, front_index=0, side_index=1, threshold=0.9):
    """Faces facing the camera (+/-Y after a text is stood up, or +Z before) get the front material."""
    me = obj.data
    for poly in me.polygons:
        n = poly.normal
        poly.material_index = front_index if abs(n.z) > threshold else side_index


def render(a):
    sc = bpy.context.scene
    os.makedirs(a.out, exist_ok=True)
    if a.still is not None:
        sc.frame_set(frame_of(a, a.still))
        sc.render.filepath = os.path.join(a.out, "still.png")
        bpy.ops.render.render(write_still=True)
        return
    sc.render.filepath = os.path.join(a.out, "f_#####")
    bpy.ops.render.render(animation=True)
