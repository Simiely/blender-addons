# 工作台快渲 —— 设好相机后一键出工作台风格的预览，不用切引擎再切回来。
#
# 原理：bpy.ops.render.opengl(view_context=False) 用**场景设置**渲染，
# 即「相机视角 + scene.display.shading（也就是渲染属性里的工作台面板）」，
# 它压根不看 scene.render.engine —— 实测 Cycles 下 poll() 依然为 True。
#
# 因此本插件：
#   · 主路径完全不碰渲染引擎（渲染引擎字段全程保持不变）；
#   · 「引擎式渲染」按钮才切引擎，但用 try/finally 保证一定切回来；
#   · 输出路径/格式/分辨率/帧范围默认渲染后还原，不污染 Cycles 的正式输出设置。
#
# ⚠️ bl_info 后面必须紧跟一个空行：Blender 的快速 bl_info 扫描器只读到第一个空行，
#    若后面接了多行 docstring 会被截成未闭合的三引号，ast.parse 失败 → 插件不显示在列表里。

bl_info = {
    "name": "工作台快渲 (Workbench Quick Look)",
    "author": "WorkBuddy",
    "version": (1, 4, 0),
    "blender": (4, 0, 0),
    "location": "3D 视图 > 侧栏 (N) > 快渲",
    "description": "设好相机后直接出工作台风格的预览图/动画；全程不切换渲染引擎，Cycles 保持不动",
    "category": "Render",
}

import json
import os
import time

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import Operator, Panel, PropertyGroup

PANEL_CATEGORY = "快渲"
DEFAULT_DIR = "//output/快渲/"

# 视口 shading 与 scene.display.shading 共有的属性（两侧都有才同步）
_SHADING_ATTRS = (
    "light",
    "studio_light",
    "color_type",
    "single_color",
    "show_shadows",
    "shadow_intensity",
    "show_cavity",
    "cavity_type",
    "cavity_ridge_factor",
    "cavity_valley_factor",
    "curvature_ridge_factor",
    "curvature_valley_factor",
    "show_object_outline",
    "show_specular_highlight",
    "show_backface_culling",
    "use_world_space_lighting",
)

# 实时预览的运行时状态。只活在本次 Blender 会话里，不写进 .blend。
_PREVIEW = {
    "active": False,
    "shading": None,   # scene.display.shading 的快照
    "spaces": None,    # 各 3D 视口的快照
}


# --------------------------------------------------------------------------
# 工具函数
# --------------------------------------------------------------------------

def _out_dir(scene):
    raw = (scene.wqr.output_dir or "").strip() or DEFAULT_DIR
    if not raw.endswith(("/", "\\")):
        raw += "/"
    return bpy.path.abspath(raw)


def _set_image_format(image_settings, video):
    """5.2 的顺序坑：必须先设 media_type，再设 file_format。"""
    if hasattr(image_settings, "media_type"):
        image_settings.media_type = 'VIDEO' if video else 'IMAGE'
    image_settings.file_format = 'FFMPEG' if video else 'PNG'


def _snapshot(scene):
    render = scene.render
    return {
        "engine": render.engine,
        "filepath": render.filepath,
        "media_type": getattr(render.image_settings, "media_type", None),
        "file_format": render.image_settings.file_format,
        "res_x": render.resolution_x,
        "res_y": render.resolution_y,
        "res_pct": render.resolution_percentage,
        "frame_start": scene.frame_start,
        "frame_end": scene.frame_end,
        "frame_current": scene.frame_current,
    }


def _restore_output(scene, snap):
    """还原输出相关设置（不含引擎）。media_type 必须先于 file_format。"""
    render = scene.render
    img = render.image_settings
    if snap["media_type"] is not None and hasattr(img, "media_type"):
        img.media_type = snap["media_type"]
    try:
        img.file_format = snap["file_format"]
    except TypeError:
        # 跨版本兜底：media_type 与 file_format 不匹配时先退回 IMAGE
        if hasattr(img, "media_type"):
            img.media_type = 'IMAGE'
        img.file_format = snap["file_format"]
    render.filepath = snap["filepath"]
    render.resolution_x = snap["res_x"]
    render.resolution_y = snap["res_y"]
    render.resolution_percentage = snap["res_pct"]
    scene.frame_start = snap["frame_start"]
    scene.frame_end = snap["frame_end"]


def _apply_preview_scale(scene):
    preset = scene.wqr.res_preset
    if preset == 'HALF':
        scene.render.resolution_percentage = 50
    elif preset == 'QUARTER':
        scene.render.resolution_percentage = 25


def _apply_frames(scene):
    if scene.wqr.use_custom_range:
        scene.frame_start = min(scene.wqr.range_start, scene.wqr.range_end)
        scene.frame_end = max(scene.wqr.range_start, scene.wqr.range_end)


def _prepare_output(scene, video):
    directory = _out_dir(scene)
    os.makedirs(directory, exist_ok=True)
    # 统一剥掉结尾的下划线/空格，避免用户填 "快渲_" 时出现 "快渲__0001.png"
    name = (scene.wqr.file_name or "").strip().rstrip("_") or "快渲"
    render = scene.render
    _set_image_format(render.image_settings, video)
    if video:
        render.ffmpeg.format = 'MPEG4'
        render.ffmpeg.codec = 'H264'
        render.ffmpeg.audio_codec = 'NONE'
        render.filepath = os.path.join(directory, name + ".mp4")
    else:
        render.filepath = os.path.join(directory, name + "_")
    return directory, name


def _precheck(scene):
    if scene.camera is None:
        return "场景没有活动相机 —— 先选中相机按 Ctrl+Numpad0 设为活动相机"
    return None


def _count_png(directory, name):
    try:
        return len([
            f for f in os.listdir(directory)
            if f.startswith(name) and f.lower().endswith(".png")
        ])
    except OSError:
        return 0


# --------------------------------------------------------------------------
# 实时预览：把 scene.display.shading 同步到 3D 视口，并可整体还原
# --------------------------------------------------------------------------

def _viewport_spaces():
    """所有窗口里的 3D 视口 space（拿不到就跳过，后台模式安全）。"""
    spaces = []
    try:
        windows = bpy.context.window_manager.windows
    except Exception:
        return spaces
    for window in windows:
        try:
            screen = window.screen
        except Exception:
            continue
        if not screen:
            continue
        for area in screen.areas:
            if area.type != 'VIEW_3D':
                continue
            for space in area.spaces:
                if getattr(space, "type", "") == 'VIEW_3D':
                    spaces.append(space)
    return spaces


def _same_value(a, b):
    if isinstance(a, str) or isinstance(b, str):
        return a == b
    try:
        return tuple(a) == tuple(b)
    except TypeError:
        return a == b


def _assign_attrs(target, data):
    """把 data 逐项写进 target，返回**写失败的属性名**（不静默吞，便于报错）。"""
    failed = []
    for name, value in (data or {}).items():
        try:
            setattr(target, name, value)
        except Exception:
            failed.append(name)
    return failed


def _copy_attrs(source, target, attrs):
    """把 source 上 attrs 里的值拷到 target；返回是否有改动。"""
    changed = False
    for name in attrs:
        if not (hasattr(source, name) and hasattr(target, name)):
            continue
        try:
            value = getattr(source, name)
            current = getattr(target, name)
        except Exception:
            continue
        if _same_value(current, value):
            continue
        try:
            setattr(target, name, value)
            changed = True
        except Exception:
            pass
    return changed


def _snapshot_shading(shading):
    """冻结 shading 上的外观值。★ 字符串枚举必须原样保留 —— 一旦被 tuple() 成字符元组，
    还原时 setattr 会抛 TypeError，外观就悄悄还原不回去了（踩过）。"""
    data = {}
    for name in _SHADING_ATTRS:
        if not hasattr(shading, name):
            continue
        try:
            value = getattr(shading, name)
        except Exception:
            continue
        if not isinstance(value, (str, bool, int, float)):
            try:
                value = tuple(value)
            except TypeError:
                pass
        data[name] = value
    return data


def _snapshot_viewports():
    snapshot = []
    for space in _viewport_spaces():
        region = getattr(space, "region_3d", None)
        snapshot.append({
            "space": space,
            "type": getattr(space.shading, "type", None),
            "view_perspective": getattr(region, "view_perspective", None),
            "shading": _snapshot_shading(space.shading),
        })
    return snapshot


def _push_shading(scene):
    """把场景的工作台外观推到每个 3D 视口；只改有差异的值，避免重绘死循环。"""
    source = scene.display.shading
    for space in _viewport_spaces():
        try:
            _copy_attrs(source, space.shading, _SHADING_ATTRS)
        except ReferenceError:
            continue


def _apply_preview_to_viewports(scene, use_camera_view):
    """打开预览：切实体着色 + 套用外观 +（可选）切相机视角。"""
    source = scene.display.shading
    for space in _viewport_spaces():
        try:
            space.shading.type = 'SOLID'
            _copy_attrs(source, space.shading, _SHADING_ATTRS)
            if use_camera_view:
                region = getattr(space, "region_3d", None)
                if region is not None:
                    region.view_perspective = 'CAMERA'
        except ReferenceError:
            continue


def _restore_viewports(snapshot):
    failed = []
    for entry in snapshot or ():
        space = entry.get("space")
        try:
            if entry.get("type"):
                space.shading.type = entry["type"]
            failed += _assign_attrs(space.shading, entry.get("shading"))
            region = getattr(space, "region_3d", None)
            if region is not None and entry.get("view_perspective"):
                region.view_perspective = entry["view_perspective"]
        except ReferenceError:
            continue
    return failed


def _apply_cavity_preset(scene):
    """把腔体脊/谷系数写成预设值。世界与屏幕两组一起写 —— 面板随时可切类型。"""
    shading = scene.display.shading
    settings = scene.wqr
    ridge = float(settings.cavity_preset_ridge)
    valley = float(settings.cavity_preset_valley)
    if hasattr(shading, "show_cavity"):
        shading.show_cavity = True
    if hasattr(shading, "cavity_ridge_factor"):
        shading.cavity_ridge_factor = ridge
    if hasattr(shading, "cavity_valley_factor"):
        shading.cavity_valley_factor = valley
    if hasattr(shading, "curvature_ridge_factor"):
        shading.curvature_ridge_factor = ridge
    if hasattr(shading, "curvature_valley_factor"):
        shading.curvature_valley_factor = valley
    return ridge, valley


def _dump_shading(shading):
    """把当前外观压成 JSON 字符串，供「预览外观记忆」保存。"""
    return json.dumps(_snapshot_shading(shading), ensure_ascii=False, sort_keys=True)


def _load_profile(settings):
    """取出记住的预览外观；没记住或数据损坏则返回 None。"""
    raw = (settings.preview_profile or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) and data else None


def _save_profile(scene):
    """把「用户此刻调好的外观」记下来 —— 必须在还原之前调用，否则存到的是还原后的值。"""
    settings = scene.wqr
    if not settings.remember_preview:
        return False
    settings.preview_profile = _dump_shading(scene.display.shading)
    settings.preview_profile_time = time.strftime("%m-%d %H:%M")
    return True


def _start_preview(scene, state):
    # 先快照「当前」原值，保证关掉开关还能还原回去
    state["shading"] = _snapshot_shading(scene.display.shading)
    state["spaces"] = _snapshot_viewports()
    state["from_profile"] = False

    # 优先还原「上次预览时调好的外观」；没记忆时才退回出厂预设。
    # 顺序不能反：否则用户调好的腔体值会被预设覆盖，等于每次重来。
    failed = []
    profile = _load_profile(scene.wqr) if scene.wqr.remember_preview else None
    if profile:
        failed = _assign_attrs(scene.display.shading, profile)
        state["from_profile"] = True
    elif scene.wqr.apply_cavity_preset:
        _apply_cavity_preset(scene)

    _apply_preview_to_viewports(scene, scene.wqr.preview_camera)
    state["active"] = True
    return failed


def _stop_preview(scene, state):
    """关掉预览：先记住用户调好的外观（下次打开能还原），再把视口与外观还原到打开之前。

    返回写失败的属性名列表。
    """
    if state.get("active"):
        # 只有真的在预览中才存 —— 闲置时调用（例如卸载插件）不能把还原后的值当记忆存进去
        _save_profile(scene)
    failed = list(_restore_viewports(state.get("spaces")))
    failed += _assign_attrs(scene.display.shading, state.get("shading"))
    state["active"] = False
    state["shading"] = None
    state["spaces"] = None
    return failed


# --------------------------------------------------------------------------
# 参数
# --------------------------------------------------------------------------

def _on_preview_camera_changed(self, context):
    """预览开着的时候改「切到相机视角」，立刻生效（关掉不强行拉回原视角）。"""
    scene = getattr(context, "scene", None) if context else None
    if scene is not None and _PREVIEW.get("active") and self.preview_camera:
        _apply_preview_to_viewports(scene, True)


class WQR_Properties(PropertyGroup):
    output_dir: StringProperty(
        name="输出目录",
        description="支持 // 开头的相对路径（相对 .blend 所在目录）",
        default=DEFAULT_DIR,
        subtype='DIR_PATH',
    )
    file_name: StringProperty(
        name="文件名",
        description="MP4 存成 <文件名>.mp4；PNG 序列存成 <文件名>_0001.png（结尾的 _ 会自动去掉）",
        default="快渲",
    )
    anim_format: EnumProperty(
        name="动画格式",
        items=[
            ('MP4', "MP4 视频", "H.264 MP4，出来直接能发给别人"),
            ('PNG', "PNG 序列", "逐帧 PNG，方便再进剪辑"),
        ],
        default='MP4',
    )
    res_preset: EnumProperty(
        name="分辨率",
        items=[
            ('SCENE', "用场景设置", "沿用输出属性里的分辨率与百分比"),
            ('HALF', "1/2", "临时降到 50%，出得更快"),
            ('QUARTER', "1/4", "临时降到 25%，只求看个大概"),
        ],
        default='SCENE',
    )
    use_custom_range: BoolProperty(name="自定义帧范围", default=False)
    range_start: IntProperty(name="起始帧", default=1)
    range_end: IntProperty(name="结束帧", default=250)
    preview_on: BoolProperty(
        name="实时预览",
        description="打开后，下面的外观参数会立刻反映到 3D 视口；关掉则把视口与外观参数一起还原到打开前的状态",
        default=False,
    )
    preview_camera: BoolProperty(
        name="同时切到相机视角",
        description="打开预览时顺便把视口切到活动相机视角，方便看构图",
        default=True,
        update=_on_preview_camera_changed,
    )
    apply_cavity_preset: BoolProperty(
        name="无记忆时套用预设",
        description=(
            "仅在「还没记住任何预览外观」时生效：打开预览时把腔体脊/谷系数写成下面的预设值。"
            "一旦记住过外观，就优先用记住的那份"
        ),
        default=True,
    )
    remember_preview: BoolProperty(
        name="记住预览外观",
        description=(
            "关掉预览时自动保存当时的外观；下次打开预览自动还原成那个样子，"
            "不用每次重新调（记忆随 .blend 保存）"
        ),
        default=True,
    )
    preview_profile: StringProperty(default="")
    preview_profile_time: StringProperty(default="")
    cavity_preset_ridge: FloatProperty(
        name="脊",
        description="腔体脊系数（世界与屏幕两组一起写）",
        default=0.3,
        min=0.0,
        max=2.5,
        precision=3,
    )
    cavity_preset_valley: FloatProperty(
        name="谷",
        description="腔体谷系数（世界与屏幕两组一起写）",
        default=0.3,
        min=0.0,
        max=2.5,
        precision=3,
    )
    restore_settings: BoolProperty(
        name="渲染后还原输出设置",
        description="渲染结束后把输出路径 / 格式 / 分辨率 / 帧范围改回去；渲染引擎始终会自动还原",
        default=True,
    )


# --------------------------------------------------------------------------
# 操作符
# --------------------------------------------------------------------------

class WQR_OT_preview(Operator):
    bl_idname = "wqr.preview"
    bl_label = "看一眼（不存盘）"
    bl_description = "用当前相机渲染一帧工作台风格画面，只送进查看器，不写文件"
    bl_options = {'REGISTER'}

    def execute(self, context):
        scene = context.scene
        problem = _precheck(scene)
        if problem:
            self.report({'ERROR'}, problem)
            return {'CANCELLED'}

        snap = _snapshot(scene)
        try:
            _apply_preview_scale(scene)
            bpy.ops.render.opengl(animation=False, write_still=False, view_context=False)
        except Exception as exc:
            self.report({'ERROR'}, "快渲失败：%s" % exc)
            return {'CANCELLED'}
        finally:
            if scene.wqr.restore_settings:
                _restore_output(scene, snap)

        self.report({'INFO'}, "已送进渲染结果查看器（未写盘）")
        return {'FINISHED'}


class WQR_OT_still(Operator):
    bl_idname = "wqr.render_still"
    bl_label = "快渲当前帧 (PNG)"
    bl_description = "用当前相机出一张工作台风格 PNG，渲染引擎保持不变"
    bl_options = {'REGISTER'}

    def execute(self, context):
        scene = context.scene
        problem = _precheck(scene)
        if problem:
            self.report({'ERROR'}, problem)
            return {'CANCELLED'}

        snap = _snapshot(scene)
        written = ""
        failure = ""
        try:
            _apply_preview_scale(scene)
            _prepare_output(scene, video=False)
            bpy.ops.render.opengl(animation=False, write_still=True, view_context=False)
            written = scene.render.frame_path(frame=scene.frame_current)
        except Exception as exc:
            failure = str(exc)
        finally:
            if scene.wqr.restore_settings:
                _restore_output(scene, snap)

        if failure:
            self.report({'ERROR'}, "快渲失败：%s" % failure)
            return {'CANCELLED'}
        self.report({'INFO'}, "已写出：%s" % written)
        return {'FINISHED'}


class WQR_OT_anim(Operator):
    bl_idname = "wqr.render_anim"
    bl_label = "快渲动画"
    bl_description = "按帧范围用当前相机出工作台风格 MP4 / PNG 序列，渲染引擎保持不变"
    bl_options = {'REGISTER'}

    def execute(self, context):
        scene = context.scene
        problem = _precheck(scene)
        if problem:
            self.report({'ERROR'}, problem)
            return {'CANCELLED'}

        snap = _snapshot(scene)
        video = scene.wqr.anim_format == 'MP4'
        directory = name = ""
        frames = 0
        aborted = False
        failure = ""
        try:
            _apply_preview_scale(scene)
            _apply_frames(scene)
            directory, name = _prepare_output(scene, video=video)
            result = bpy.ops.render.opengl(animation=True, view_context=False)
            aborted = 'CANCELLED' in result
            if not video:
                frames = _count_png(directory, name)
        except Exception as exc:
            failure = str(exc)
        finally:
            if scene.wqr.restore_settings:
                _restore_output(scene, snap)

        if failure:
            self.report({'ERROR'}, "快渲失败：%s" % failure)
            return {'CANCELLED'}
        if aborted:
            self.report({'WARNING'}, "已被中止，已出的文件留在：%s" % directory)
            return {'CANCELLED'}
        if video:
            self.report({'INFO'}, "已写出：%s" % os.path.join(directory, name + ".mp4"))
        else:
            self.report({'INFO'}, "已写出 %d 帧到：%s" % (frames, directory))
        return {'FINISHED'}


class WQR_OT_engine_anim(Operator):
    bl_idname = "wqr.render_engine"
    bl_label = "引擎式渲染（自动切回）"
    bl_description = (
        "临时把渲染引擎切到工作台、渲染完自动切回原引擎。"
        "只有需要工作台引擎专属能力（Freestyle 自由线等）时才用，比快渲慢"
    )
    bl_options = {'REGISTER'}

    def execute(self, context):
        scene = context.scene
        problem = _precheck(scene)
        if problem:
            self.report({'ERROR'}, problem)
            return {'CANCELLED'}

        snap = _snapshot(scene)
        video = scene.wqr.anim_format == 'MP4'
        directory = name = ""
        failure = ""
        try:
            _apply_preview_scale(scene)
            _apply_frames(scene)
            directory, name = _prepare_output(scene, video=video)
            scene.render.engine = 'BLENDER_WORKBENCH'
            bpy.ops.render.render(animation=True)
        except Exception as exc:
            failure = str(exc)
        finally:
            # 引擎无条件还原，避免「忘了切回 Cycles」
            scene.render.engine = snap["engine"]
            if scene.wqr.restore_settings:
                _restore_output(scene, snap)

        if failure:
            self.report({'ERROR'}, "渲染失败：%s" % failure)
            return {'CANCELLED'}
        self.report({'INFO'}, "已切回 %s；输出在：%s" % (snap["engine"], directory))
        return {'FINISHED'}


class WQR_OT_toggle_preview(Operator):
    bl_idname = "wqr.toggle_preview"
    bl_label = "实时预览"
    bl_description = (
        "打开：把 3D 视口切实体着色并套用下面的外观参数，之后改参数立刻可见；"
        "关掉：视口和外观参数一起还原到打开开关之前"
    )
    bl_options = {'REGISTER'}

    def execute(self, context):
        scene = context.scene
        settings = scene.wqr

        if _PREVIEW.get("active"):
            saved = settings.remember_preview
            failed = _stop_preview(scene, _PREVIEW)
            settings.preview_on = False
            tail = "；这次的外观已记住，下次打开会还原" if saved else ""
            if failed:
                self.report({'WARNING'}, "已还原，但有 %d 项没能写回：%s%s"
                            % (len(failed), "、".join(failed), tail))
            else:
                self.report({'INFO'}, "已还原到打开预览前的视口与外观%s" % tail)
            return {'FINISHED'}

        try:
            failed = _start_preview(scene, _PREVIEW)
        except Exception as exc:
            _PREVIEW["active"] = False
            settings.preview_on = False
            self.report({'ERROR'}, "打开预览失败：%s" % exc)
            return {'CANCELLED'}

        settings.preview_on = True
        if _PREVIEW.get("from_profile"):
            head = "预览已打开：用的是上次记住的外观"
        else:
            head = "预览已打开：改下面的外观参数会立刻在视口生效"
        if failed:
            self.report({'WARNING'}, "%s；但有 %d 项没能写回：%s"
                        % (head, len(failed), "、".join(failed)))
        else:
            self.report({'INFO'}, head)
        return {'FINISHED'}


class WQR_OT_apply_cavity_preset(Operator):
    bl_idname = "wqr.apply_cavity_preset"
    bl_label = "套用这个预设"
    bl_description = "立刻把腔体脊/谷系数写成上面的预设值（预览开着时会同步到视口）"
    bl_options = {'REGISTER'}

    def execute(self, context):
        scene = context.scene
        ridge, valley = _apply_cavity_preset(scene)
        if _PREVIEW.get("active"):
            _push_shading(scene)
        self.report({'INFO'}, "腔体 脊 = %.3g，谷 = %.3g（世界与屏幕两组都已写入）"
                    % (ridge, valley))
        return {'FINISHED'}


class WQR_OT_forget_preview_profile(Operator):
    bl_idname = "wqr.forget_preview_profile"
    bl_label = "忘记记住的外观"
    bl_description = "清掉记住的预览外观；下次打开预览会重新使用出厂预设"
    bl_options = {'REGISTER'}

    def execute(self, context):
        settings = context.scene.wqr
        settings.preview_profile = ""
        settings.preview_profile_time = ""
        self.report({'INFO'}, "已清掉记住的预览外观；下次打开预览会重新用出厂预设")
        return {'FINISHED'}


class WQR_OT_open_folder(Operator):
    bl_idname = "wqr.open_folder"
    bl_label = "打开输出目录"
    bl_options = {'REGISTER'}

    def execute(self, context):
        directory = _out_dir(context.scene)
        try:
            os.makedirs(directory, exist_ok=True)
            bpy.ops.wm.path_open(filepath=directory)
        except Exception as exc:
            self.report({'ERROR'}, "打不开目录：%s" % exc)
            return {'CANCELLED'}
        return {'FINISHED'}


# --------------------------------------------------------------------------
# 面板
# --------------------------------------------------------------------------

def _prop(layout, owner, name, **kwargs):
    """属性不存在就跳过，避免版本差异直接把面板画崩。"""
    try:
        if hasattr(owner, name):
            layout.prop(owner, name, **kwargs)
            return True
    except Exception:
        pass
    return False


class WQR_PT_panel(Panel):
    bl_idname = "WQR_PT_panel"
    bl_label = "工作台快渲"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = PANEL_CATEGORY

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        settings = scene.wqr

        box = layout.box()
        row = box.row()
        row.label(text="渲染引擎：" + scene.render.engine)
        row = box.row()
        if scene.camera:
            row.label(text="相机：" + scene.camera.name)
        else:
            row.label(text="相机：未设置（Ctrl+Numpad0）", icon='ERROR')

        col = layout.column(align=True)
        col.scale_y = 1.35
        col.operator("wqr.preview", icon='HIDE_OFF')
        col.operator("wqr.render_still", icon='IMAGE_DATA')
        col.operator("wqr.render_anim", icon='RENDER_ANIMATION')

        layout.separator()
        box = layout.box()
        box.label(text="输出", icon='FILE_FOLDER')
        _prop(box, settings, "output_dir", text="目录")
        _prop(box, settings, "file_name", text="文件名")
        _prop(box, settings, "anim_format", text="动画格式")
        _prop(box, settings, "res_preset", text="分辨率")
        row = box.row(align=True)
        _prop(row, settings, "use_custom_range", text="自定义帧范围")
        sub = row.row(align=True)
        sub.enabled = settings.use_custom_range
        _prop(sub, settings, "range_start", text="")
        _prop(sub, settings, "range_end", text="")
        box.operator("wqr.open_folder", icon='FILEBROWSER', text="打开输出目录")

        layout.separator()
        box = layout.box()
        col = box.column(align=True)
        col.scale_y = 1.25
        col.operator(
            "wqr.toggle_preview",
            text=("停止预览（还原）" if settings.preview_on else "实时预览到视口"),
            icon='RESTRICT_VIEW_OFF' if settings.preview_on else 'RESTRICT_VIEW_ON',
            depress=settings.preview_on,
        )
        sub = box.column()
        sub.enabled = settings.preview_on
        _prop(sub, settings, "preview_camera", text="同时切到相机视角")

        sub = box.column()
        _prop(sub, settings, "remember_preview", text="记住外观（下次开预览自动还原）")
        row = box.row(align=True)
        if settings.preview_profile:
            row.label(text="已记住 " + (settings.preview_profile_time or "（本次）"),
                      icon='CHECKMARK')
            row.operator("wqr.forget_preview_profile", text="", icon='TRASH')
        else:
            row.label(text="还没记住外观（用出厂预设）", icon='INFO')

        tip = box.column()
        tip.scale_y = 0.9
        if settings.preview_on:
            tip.label(text="改下面的外观，视口立刻跟着变", icon='INFO')
        else:
            tip.label(text="关掉会还原场景外观，但会记住你调好的样子", icon='INFO')

        layout.separator()
        box = layout.box()
        box.label(text="工作台外观（直接改，不用切引擎）", icon='MATERIAL')
        shading = scene.display.shading
        _prop(box, shading, "light", text="光照")
        if getattr(shading, "light", "") == 'STUDIO':
            _prop(box, shading, "studio_light", text="")
        _prop(box, shading, "color_type", text="颜色")
        if getattr(shading, "color_type", "") == 'SINGLE':
            _prop(box, shading, "single_color", text="")
        _prop(box, shading, "show_shadows", text="阴影")
        if getattr(shading, "show_shadows", False):
            sub = box.column(align=True)
            _prop(sub, shading, "shadow_intensity", text="阴影强度", slider=True)

        _prop(box, shading, "show_cavity", text="腔体")
        if getattr(shading, "show_cavity", False):
            sub = box.column(align=True)
            _prop(sub, shading, "cavity_type", text="类型")
            cavity_type = getattr(shading, "cavity_type", "")
            if cavity_type in {'WORLD', 'BOTH'}:
                _prop(sub, shading, "cavity_ridge_factor", text="世界 脊", slider=True)
                _prop(sub, shading, "cavity_valley_factor", text="世界 谷", slider=True)
            if cavity_type in {'SCREEN', 'BOTH'}:
                _prop(sub, shading, "curvature_ridge_factor", text="屏幕 脊", slider=True)
                _prop(sub, shading, "curvature_valley_factor", text="屏幕 谷", slider=True)
            row = sub.row(align=True)
            _prop(row, settings, "cavity_preset_ridge", text="预设 脊")
            _prop(row, settings, "cavity_preset_valley", text="谷")
            sub.row(align=True).operator("wqr.apply_cavity_preset", icon='CHECKMARK')
            sub.row(align=True).prop(settings, "apply_cavity_preset")

        _prop(box, shading, "show_object_outline", text="描边")
        _prop(box, scene.display, "render_aa", text="抗锯齿")

        layout.separator()
        _prop(layout, settings, "restore_settings")
        col = layout.column()
        col.scale_y = 0.9
        col.label(text="换个结果不满意？先调上面外观再重渲", icon='INFO')
        col.label(text="引擎式渲染仅在需要 Freestyle 时用", icon='INFO')

        # 预览开着时，每次面板重绘都把外观推给视口 → 改哪个参数都立刻可见。
        # 只写有差异的值，重复重绘不会互相触发死循环。
        if settings.preview_on:
            if _PREVIEW.get("active"):
                _push_shading(scene)
            else:
                # 例如重开了一个旧文件：按钮状态和运行时状态对不上，纠正回来
                settings.preview_on = False


# --------------------------------------------------------------------------
# 注册
# --------------------------------------------------------------------------

_CLASSES = (
    WQR_Properties,
    WQR_OT_preview,
    WQR_OT_still,
    WQR_OT_anim,
    WQR_OT_engine_anim,
    WQR_OT_toggle_preview,
    WQR_OT_apply_cavity_preset,
    WQR_OT_forget_preview_profile,
    WQR_OT_open_folder,
    WQR_PT_panel,
)


@bpy.app.handlers.persistent
def _on_file_load(*_args):
    """换文件后预览状态会失真，直接作废（视口保持当时的样子，不再尝试还原）。"""
    _PREVIEW["active"] = False
    _PREVIEW["shading"] = None
    _PREVIEW["spaces"] = None


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.wqr = PointerProperty(type=WQR_Properties)
    bpy.app.handlers.load_post.append(_on_file_load)


def unregister():
    if _on_file_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_file_load)
    if _PREVIEW.get("active"):
        try:
            failed = _stop_preview(bpy.context.scene, _PREVIEW)
            if failed:
                print("[工作台快渲] 卸载还原时未能写回：", failed)
        except Exception as exc:
            print("[工作台快渲] 卸载还原失败：", exc)
            _PREVIEW["active"] = False
            _PREVIEW["shading"] = None
            _PREVIEW["spaces"] = None
    if hasattr(bpy.types.Scene, "wqr"):
        del bpy.types.Scene.wqr
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
