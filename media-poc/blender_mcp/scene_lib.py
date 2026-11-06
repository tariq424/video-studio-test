# Blender-side scene library for the r11 Blender-MCP route.
#
# This file is NEVER imported. Its text is sent over MCP (execute_blender_code)
# together with one function call, and runs inside the live Blender.
# It must pass the MCP server's safe mode (BLENDER_MCP_SAFE_MODE=1):
#   only bpy / bmesh / mathutils / pure-stdlib imports; no os/sys/open; no
#   classes, lambdas, globals, handlers, timers or drivers; getattr with
#   literal names only. tests/test_blender_mcp_poc.py runs the real validator.
# Units: metres, Z up, ground is z = 0. Each function prints ONE JSON line.
import bpy
import bmesh
import json
import math
import random
from mathutils import Vector


def _out(**kw):
    print(json.dumps(kw))


def _scene():
    return bpy.context.scene


def _st():
    raw = _scene().get("bv_state")
    if raw:
        return json.loads(raw)
    return {"assets": {}, "before": []}


def _save_st(st):
    _scene()["bv_state"] = json.dumps(st)


# --------------------------------------------------------------------------- reset
def reset(fps=24, frames=96):
    scn = _scene()
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for c in list(bpy.data.collections):
        bpy.data.collections.remove(c)
    for blocks in (bpy.data.meshes, bpy.data.materials, bpy.data.images, bpy.data.cameras,
                   bpy.data.lights, bpy.data.node_groups, bpy.data.textures, bpy.data.actions,
                   bpy.data.curves):
        for b in list(blocks):
            if b.users == 0:
                blocks.remove(b)
    if scn.world is None:
        scn.world = bpy.data.worlds.new("World")
    scn.world.use_nodes = True
    scn.unit_settings.system = "METRIC"
    scn.render.fps = int(fps)
    scn.frame_start = 1
    scn.frame_end = int(frames)
    scn.frame_set(1)
    _save_st({"assets": {}, "before": []})
    _out(ok=True, frames=int(frames), fps=int(fps))


# --------------------------------------------------------------------------- sky
def sky_adjust(strength=1.0, rotation_deg=0.0):
    nt = _scene().world.node_tree
    env = None
    mapping = None
    for n in nt.nodes:
        if n.type == "TEX_ENVIRONMENT":
            env = n
        if n.type == "MAPPING":
            mapping = n
        if n.type == "BACKGROUND":
            n.inputs["Strength"].default_value = float(strength)
    if env is not None:
        if mapping is None:
            tc = nt.nodes.new("ShaderNodeTexCoord")
            mapping = nt.nodes.new("ShaderNodeMapping")
            nt.links.new(tc.outputs["Generated"], mapping.inputs["Vector"])
            nt.links.new(mapping.outputs["Vector"], env.inputs["Vector"])
        mapping.inputs["Rotation"].default_value[2] = math.radians(float(rotation_deg))
    _out(ok=True, hdri=env is not None)


def sky_fallback(time_of_day="afternoon"):
    nt = _scene().world.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")
    sky = nt.nodes.new("ShaderNodeTexSky")
    for t in ("MULTIPLE_SCATTERING", "SINGLE_SCATTERING", "NISHITA", "HOSEK_WILKIE"):
        try:
            sky.sky_type = t
            break
        except Exception:
            pass
    elev = {"sunrise": 4, "sunset": 4, "golden hour": 8, "night": -6, "dusk": 1}.get(time_of_day, 40)
    try:
        sky.sun_elevation = math.radians(elev)
        sky.sun_rotation = math.radians(220)
    except Exception:
        pass
    nt.links.new(sky.outputs[0], bg.inputs["Color"])
    nt.links.new(bg.outputs[0], out.inputs[0])
    bg.inputs["Strength"].default_value = 0.3 if elev < 0 else 1.0
    _out(ok=True, sky=sky.sky_type)


# --------------------------------------------------------------------------- ground / water
def _grid_object(name, size, uv_repeat=1.0):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new("UVMap")  # create_grid only fills UVs when a layer exists
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=size / 2.0, calc_uvs=True)
    if uv_repeat != 1.0:
        for f in bm.faces:
            for loop in f.loops:
                loop[uv].uv = loop[uv].uv * uv_repeat
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    _scene().collection.objects.link(ob)
    return ob


def make_ground(size_m=200.0, texture_size_m=2.0):
    repeat = max(1.0, float(size_m) / max(0.25, float(texture_size_m)))
    ob = _grid_object("BV_Ground", float(size_m), uv_repeat=repeat)
    mat = bpy.data.materials.new("BV_Ground_Fallback")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (0.18, 0.17, 0.15, 1)
        bsdf.inputs["Roughness"].default_value = 0.9
    ob.data.materials.append(mat)
    _out(ok=True, name=ob.name, uv_repeat=round(repeat, 2))


def make_water(size_m=200.0, frames=96, fps=24):
    ob = _grid_object("BV_Water", 10.0)
    mod = ob.modifiers.new("Ocean", "OCEAN")
    mod.geometry_mode = "GENERATE"
    mod.size = 1.0
    mod.spatial_size = 40
    mod.repeat_x = max(1, int(float(size_m) / 40))
    mod.repeat_y = mod.repeat_x
    mod.resolution = 12
    mod.wave_scale = 0.6
    mod.choppiness = 1.0
    ob.location = (-float(size_m) / 2.0, -float(size_m) / 2.0, 0.05)
    mod.time = 1.0
    mod.keyframe_insert("time", frame=1)
    mod.time = 1.0 + float(frames) / float(fps)
    mod.keyframe_insert("time", frame=int(frames))
    _linear(ob)
    mat = bpy.data.materials.new("BV_Water")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (0.01, 0.045, 0.06, 1)
    bsdf.inputs["Roughness"].default_value = 0.04
    bsdf.inputs["IOR"].default_value = 1.333
    ob.data.materials.append(mat)
    _out(ok=True, name=ob.name)


# --------------------------------------------------------------------------- assets
def snapshot():
    st = _st()
    st["before"] = [o.name for o in bpy.data.objects]
    _save_st(st)
    _out(ok=True, count=len(st["before"]))


def adopt(label):
    """Objects created since snapshot() become an instanceable source collection
    whose origin is the model's bottom-centre."""
    st = _st()
    before = set(st.get("before", []))
    new = [o for o in bpy.data.objects if o.name not in before]
    if not new:
        _out(ok=False, error="import created no objects")
        return
    bpy.context.view_layer.update()
    pts = []
    for o in new:
        if o.type in {"MESH", "CURVE", "SURFACE", "META", "FONT"}:
            for c in o.bound_box:
                pts.append(o.matrix_world @ Vector(c))
    if not pts:
        pts = [o.matrix_world.translation for o in new]
    mn = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    mx = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    src = bpy.data.collections.new("BVsrc_" + label)
    _scene().collection.children.link(src)
    for o in new:
        for c in list(o.users_collection):
            c.objects.unlink(o)
        src.objects.link(o)
    src.instance_offset = ((mn.x + mx.x) / 2, (mn.y + mx.y) / 2, mn.z)
    for lc in bpy.context.view_layer.layer_collection.children:
        if lc.collection == src:
            lc.exclude = True
    dims = [round(v, 3) for v in (mx - mn)]
    st["assets"][label] = {"collection": src.name, "dims": dims}
    _save_st(st)
    _out(ok=True, label=label, dims=dims, objects=len(new))


def alias(label, existing_label):
    st = _st()
    info = st["assets"].get(existing_label)
    if not info:
        _out(ok=False, error="unknown asset " + existing_label)
        return
    st["assets"][label] = {"collection": info["collection"], "dims": info["dims"]}
    _save_st(st)
    _out(ok=True, label=label, dims=info["dims"], objects=0)


def place(label, placements):
    """placements: [[x, y, rot_deg, z], ...] -> one collection instance each."""
    st = _st()
    info = st["assets"].get(label)
    if not info:
        _out(ok=False, error="unknown asset " + label)
        return
    src = bpy.data.collections[info["collection"]]
    names = []
    for i, pl in enumerate(placements):
        z = pl[3] if len(pl) > 3 else 0.0
        e = bpy.data.objects.new("BV_%s_%d" % (label, i), None)
        e.instance_type = "COLLECTION"
        e.instance_collection = src
        e.location = (float(pl[0]), float(pl[1]), float(z))
        e.rotation_euler = (0.0, 0.0, math.radians(float(pl[2])))
        _scene().collection.objects.link(e)
        names.append(e.name)
    info["instances"] = names
    _save_st(st)
    _out(ok=True, label=label, instances=names)


# --------------------------------------------------------------------------- motion
def _fcurves(action):
    out = []
    if hasattr(action, "fcurves"):
        out = list(action.fcurves)
    if out:
        return out
    if hasattr(action, "layers"):
        for layer in action.layers:
            for strip in layer.strips:
                if hasattr(strip, "channelbags"):
                    for bag in strip.channelbags:
                        out.extend(bag.fcurves)
    return out


def _linear(ob):
    ad = ob.animation_data
    if ad and ad.action:
        for fc in _fcurves(ad.action):
            for k in fc.keyframe_points:
                k.interpolation = "LINEAR"


def _key(ob, frame, loc=None, rot=None):
    if loc is not None:
        ob.location = loc
        ob.keyframe_insert("location", frame=frame)
    if rot is not None:
        ob.rotation_euler = rot
        ob.keyframe_insert("rotation_euler", frame=frame)


def animate(label, motion, speed=1.0, frames=96, fps=24):
    info = _st()["assets"].get(label, {})
    dims = info.get("dims", [1, 1, 1])
    size = max(dims) if dims else 1.0
    speed = max(0.1, float(speed))
    F = int(frames)
    for i, name in enumerate(info.get("instances", [])):
        ob = bpy.data.objects[name]
        x0, y0, z0 = ob.location
        r0 = ob.rotation_euler.copy()
        if motion == "spin":
            _key(ob, 1, rot=r0)
            _key(ob, F, rot=(r0.x, r0.y, r0.z + math.radians(120 * speed * F / fps / 4)))
            _linear(ob)
        elif motion == "float":
            amp = 0.06 * size * speed
            step = max(6, int(fps * 1.2 / speed))
            f = 1
            up = True
            while f <= F + step:
                _key(ob, f, loc=(x0, y0, z0 + (amp if up else 0.0)))
                f += step
                up = not up
        elif motion == "fall":
            h = z0 + 2.5 * size + 2.0
            land = int(F * 0.45) + i * 7
            _key(ob, 1, loc=(x0, y0, h), rot=(r0.x + 0.6, r0.y - 0.4, r0.z))
            _key(ob, land, loc=(x0, y0, z0), rot=r0)
            _key(ob, land + 5, loc=(x0, y0, z0 + 0.08 * size))
            _key(ob, land + 10, loc=(x0, y0, z0))
            for fc in _fcurves(ob.animation_data.action):
                if len(fc.keyframe_points):
                    k = fc.keyframe_points[0]
                    k.interpolation = "QUAD"
                    k.easing = "EASE_IN"
        elif motion == "drive":
            d = 4.0 * size * speed
            _key(ob, 1, loc=(x0 - d / 2, y0, z0))
            _key(ob, F, loc=(x0 + d / 2, y0, z0))
            _linear(ob)
        elif motion == "flight_tumble":
            # drop + tumble + recovery (the FlyDubai physics profile):
            # 0-30% drop, 30-60% full roll, 60-100% recover
            alt = 4.0 * size + 3.0
            fwd = 10.0 * size * speed
            for f in range(1, F + 1, 4):
                t = (f - 1) / max(1, F - 1)
                if t < 0.3:
                    u = t / 0.3
                    z = alt - (alt * 0.55) * u * u
                    roll = 0.0
                    pitch = -0.35 * u
                elif t < 0.6:
                    u = (t - 0.3) / 0.3
                    z = alt * 0.45 - alt * 0.15 * u
                    roll = 2 * math.pi * u
                    pitch = -0.35 + 0.15 * u
                else:
                    u = (t - 0.6) / 0.4
                    z = alt * 0.3 + alt * 0.25 * (1 - (1 - u) ** 2)
                    roll = 2 * math.pi
                    pitch = -0.2 * (1 - u)
                _key(ob, f, loc=(x0 - fwd / 2 + fwd * t, y0, z), rot=(roll, pitch, r0.z))
    _out(ok=True, label=label, motion=motion)


# --------------------------------------------------------------------------- atmosphere
def fog(density=0.3, size_m=200.0):
    d = max(0.0, min(1.0, float(density)))
    if d < 0.03:
        _out(ok=True, fog=False)
        return
    me = bpy.data.meshes.new("BV_Fog")
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new("BV_Fog", me)
    ob.scale = (float(size_m), float(size_m), 40.0)
    ob.location = (0, 0, 19.5)
    _scene().collection.objects.link(ob)
    mat = bpy.data.materials.new("BV_Fog")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    outn = nt.nodes.new("ShaderNodeOutputMaterial")
    vol = nt.nodes.new("ShaderNodeVolumePrincipled")
    vol.inputs["Density"].default_value = 0.0005 + 0.012 * d * d
    nt.links.new(vol.outputs[0], outn.inputs["Volume"])
    me.materials.append(mat)
    ob.visible_shadow = False
    _out(ok=True, fog=True)


# --------------------------------------------------------------------------- camera
def camera(hero_label, move="orbit", lens_mm=35.0, handheld=False, dof=True,
           frames=96, speed=1.0, aspect="16:9", az_deg=-35.0):
    scn = _scene()
    F = int(frames)
    info = _st()["assets"].get(hero_label or "", {})
    inst = info.get("instances") or []
    dims = info.get("dims") or [2.0, 2.0, 1.5]
    size = max(0.2, max(dims))
    hero = bpy.data.objects.get(inst[0]) if inst else None
    center = hero.location.copy() if hero else Vector((0, 0, 0))
    center.z += dims[2] * 0.5

    lens = max(14.0, min(135.0, float(lens_mm or 35)))
    long_side = 36.0
    short_side = 36.0 * 9 / 16
    portrait = aspect == "9:16"
    hfov = 2 * math.atan((short_side if portrait else long_side) / 2 / lens)
    vfov = 2 * math.atan((long_side if portrait else short_side) / 2 / lens)
    footprint = math.hypot(dims[0], dims[1])
    fit = max((footprint / 2) / math.tan(hfov / 2), (dims[2] / 2) / math.tan(vfov / 2))
    auto_dist = max(fit / 0.7 + footprint * 0.25, 0.35)
    dist = auto_dist
    elev = math.radians(8 if size > 2.5 else (13 if size > 0.5 else 22))
    eye_h = max(0.15, center.z + dist * math.tan(elev))

    target = bpy.data.objects.new("BV_Target", None)
    scn.collection.objects.link(target)
    target.location = center
    cam_data = bpy.data.cameras.new("BV_Camera")
    cam_data.lens = lens
    cam_data.sensor_fit = "AUTO"
    cam_data.clip_end = 2000
    cam = bpy.data.objects.new("BV_Camera", cam_data)
    scn.collection.objects.link(cam)
    scn.camera = cam
    tr = cam.constraints.new("TRACK_TO")
    tr.target = target
    tr.track_axis = "TRACK_NEGATIVE_Z"
    tr.up_axis = "UP_Y"

    def at(a_deg, d, z):
        a = math.radians(a_deg)
        return Vector((center.x + d * math.sin(a), center.y - d * math.cos(a), z))

    az = float(az_deg)
    s = max(0.2, float(speed))
    if move == "static":
        _key(cam, 1, loc=at(az, dist, eye_h))
    elif move == "dolly_in":
        _key(cam, 1, loc=at(az, dist * 1.45, eye_h))
        _key(cam, F, loc=at(az, dist * 0.8, eye_h))
    elif move == "dolly_out":
        _key(cam, 1, loc=at(az, dist * 0.8, eye_h))
        _key(cam, F, loc=at(az, dist * 1.5, eye_h))
    elif move == "pan_left" or move == "pan_right":
        sgn = -1 if move == "pan_left" else 1
        _key(cam, 1, loc=at(az, dist, eye_h))
        right = Vector((math.cos(math.radians(az)), math.sin(math.radians(az)), 0))
        target.location = center - right * size * 0.9 * sgn
        target.keyframe_insert("location", frame=1)
        target.location = center + right * size * 0.9 * sgn
        target.keyframe_insert("location", frame=F)
    elif move == "crane_up":
        _key(cam, 1, loc=at(az, dist, max(0.25, center.z * 0.3)))
        _key(cam, F, loc=at(az + 10, dist * 1.1, center.z + size * 1.6))
    elif move == "flyover":
        _key(cam, 1, loc=at(az, dist * 1.6, center.z + size * 1.2))
        _key(cam, F, loc=at(az + 180, dist * 1.2, center.z + size * 0.8))
    elif move == "tracking" and hero is not None:
        cl = cam.constraints.new("COPY_LOCATION")
        cl.target = hero
        cl.use_offset = True
        cam.constraints.move(1, 0)
        off = at(az + 60, dist, eye_h) - Vector((center.x, center.y, 0))
        _key(cam, 1, loc=off)
        tc = target.constraints.new("COPY_LOCATION")
        tc.target = hero
        tc.use_offset = True
        target.location = (0, 0, dims[2] * 0.5)
    else:  # orbit
        sweep = 70.0 * s
        steps = 8
        for i in range(steps + 1):
            f = 1 + int((F - 1) * i / steps)
            _key(cam, f, loc=at(az - sweep / 2 + sweep * i / steps, dist, eye_h))
        _linear(cam)

    if handheld:
        for ob, amt in ((cam, 0.012 * dist), (target, 0.006 * dist)):
            if not (ob.animation_data and ob.animation_data.action):
                ob.keyframe_insert("location", frame=1)
            for fc in _fcurves(ob.animation_data.action):
                if fc.data_path == "location":
                    m = fc.modifiers.new("NOISE")
                    m.scale = 18
                    m.strength = amt
                    m.phase = random.random() * 100

    if dof:
        cam_data.dof.use_dof = True
        cam_data.dof.focus_object = target
        cam_data.dof.aperture_fstop = 2.8 if size < 3 else 5.6
    _out(ok=True, lens=lens, distance=round(dist, 2), hero=hero.name if hero else None)


# --------------------------------------------------------------------------- render
QUALITY = {
    "preview": {"long": 1280, "samples": 48, "threshold": 0.05, "bounces": 6, "blur": False},
    "final": {"long": 1920, "samples": 256, "threshold": 0.01, "bounces": 12, "blur": True},
}


def render_setup(quality="preview", out_dir="", exposure=0.0, aspect="16:9"):
    scn = _scene()
    q = QUALITY.get(quality, QUALITY["preview"])
    long_px = q["long"]
    short_px = int(long_px * 9 / 16)
    if aspect == "9:16":
        res = (short_px, long_px)
    else:
        res = (long_px, short_px)
    scn.render.engine = "CYCLES"
    device = "CPU"
    cycles_addon = bpy.context.preferences.addons.get("cycles")  # .get(): the form safe mode can check
    prefs = cycles_addon.preferences
    for kind in ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"):
        try:
            prefs.compute_device_type = kind
            prefs.get_devices()
            gpus = [d for d in prefs.devices if d.type == kind]
            if gpus:
                for d in prefs.devices:
                    d.use = d.type == kind
                device = kind
                break
        except Exception:
            continue
    scn.cycles.device = "GPU" if device != "CPU" else "CPU"
    scn.cycles.samples = q["samples"]
    scn.cycles.use_adaptive_sampling = True
    scn.cycles.adaptive_threshold = q["threshold"]
    scn.cycles.max_bounces = q["bounces"]
    scn.cycles.sample_clamp_indirect = 10.0
    scn.cycles.use_denoising = True
    try:
        scn.cycles.denoiser = "OPENIMAGEDENOISE"
        scn.cycles.denoising_use_gpu = device != "CPU"
    except Exception:
        pass
    # Keep the scene on the GPU between frames (about 3x faster). It does not outlive the job:
    # Blender is closed (or the scene emptied) as soon as the frames are done.
    scn.render.use_persistent_data = True
    scn.render.use_motion_blur = q["blur"]
    scn.render.resolution_x = res[0]
    scn.render.resolution_y = res[1]
    scn.render.resolution_percentage = 100
    scn.render.film_transparent = False
    try:
        scn.view_settings.view_transform = "AgX"
        scn.view_settings.look = "AgX - Medium High Contrast"
    except Exception:
        pass
    scn.view_settings.exposure = float(exposure)
    scn.render.image_settings.file_format = "PNG"
    scn.render.image_settings.color_mode = "RGB"
    scn.render.use_file_extension = True
    scn.render.use_overwrite = True
    scn.render.filepath = out_dir.rstrip("/") + "/frame_"
    _out(ok=True, device=device, samples=q["samples"], res=list(res))


def still(path, frame=1):
    scn = _scene()
    keep = (scn.render.resolution_percentage, scn.cycles.samples, scn.cycles.adaptive_threshold, scn.frame_current)
    scn.render.resolution_percentage = 50
    scn.cycles.samples = 16
    scn.cycles.adaptive_threshold = 0.1
    scn.frame_set(int(frame))
    bpy.ops.render.render(write_still=False)
    bpy.data.images["Render Result"].save_render(filepath=path)
    scn.render.resolution_percentage = keep[0]
    scn.cycles.samples = keep[1]
    scn.cycles.adaptive_threshold = keep[2]
    scn.frame_set(keep[3])
    _out(ok=True, path=path)


def save_blend(path):
    # Not a copy: the file becomes "clean", so closing Blender afterwards needs no save prompt.
    bpy.ops.wm.save_as_mainfile(filepath=path)
    _out(ok=True, path=path)


def start_render():
    win = bpy.context.window_manager.windows[0]
    area = win.screen.areas[0]
    for a in win.screen.areas:
        if a.type == "VIEW_3D":
            area = a
    with bpy.context.temp_override(window=win, screen=win.screen, area=area):
        res = bpy.ops.render.render("INVOKE_DEFAULT", animation=True)
    _out(ok=True, result=sorted(res))


def render_status():
    _out(ok=True, running=bool(bpy.app.is_job_running("RENDER")), frame=_scene().frame_current)


def free_memory():
    """Used when Blender was already open before the job: empty the scene so
    its textures/geometry leave the GPU, but leave the user's window open."""
    reset(24, 1)
    _out(ok=True, freed=True)
