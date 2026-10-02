# -*- coding: utf-8 -*-
"""
对象轴与居中工具 (Object Origin & Center Tools)
================================================
Blender 插件: 把所有"轴体操作"统一在一个面板里 —— 物体(网格)永远不动, 只改原点(轴)位置。

三个功能组(全部含子集, 不限对象类型; 空物体本身跳过):
1. 居中(自身+子集): 选中对象及其全部后代逐个处理
   - 网格/曲线等: 轴(原点)居中到自身几何中心, 几何不动
   - 空物体: 移动到它所有子物体的中心 (子物体世界位置不变)
2. 轴居中贴底(一键): 每个对象轴移动到自身底部中心(几何中心 xy + 最低点 z), 几何不动
3. 轴居中贴底并落地: 每个对象先轴移到底部中心, 再整体下移贴到 Z=0 (几何移动)

中心模式(仅影响空物体定位):
  - 包围盒中心 / 原点平均 / 顶点平均

实现要点:
  - 直接移动父级会连累子物体(父子联动): 先记录子物体世界矩阵, 移动后再逐个恢复
  - 手动 Set Origin: mw_new.translation = target, 顶点局部坐标用 mw_new.inv() @ mw_old 变换,
    网格世界位置精确不变(对带父级/旋转缩放也可靠, 替代原生 origin_set 对带父级对象的问题)
  - MESH 的 bound_box 是缓存属性, 改 v.co 后不刷新 -> 包围盒一律用真实顶点计算

安装:
    编辑(Edit) > 偏好设置(Preferences) > 插件(Add-ons) > 安装(Install)
    选择本文件后勾选启用。3D 视图右侧 N 面板 > Tool 标签使用。

Blender 2.93+, 兼容 5.x。
"""

bl_info = {
    "name": "对象轴与居中工具",
    "author": "WorkBuddy",
    "version": (1, 5, 4),
    "blender": (2, 93, 0),
    "location": "3D视图 > 侧边栏(N) > Tool",
    "description": "轴体工具: 居中(自身+子集)/ 轴居中贴底 / 轴居中贴底并落地, 均含子集、不限类型, 物体网格不动只改原点",
    "category": "Object",
}

import bpy
from mathutils import Vector
from collections import namedtuple
from contextlib import contextmanager

AABB = namedtuple('AABB', ['mn', 'mx', 'center', 'minz'])
GEOMETRY_TYPES = {'MESH', 'CURVE', 'SURFACE', 'META', 'FONT', 'LATTICE'}


# ----------------------------------------------------------------------------
# 几何工具
# ----------------------------------------------------------------------------
def _world_geom_points(obj):
    """对象的世界空间几何点(MESH/CURVE/SURFACE/LATTICE 用真实数据点, 避免 bound_box 缓存过期;
    META/FONT 等用包围盒角点; EMPTY 返回空)"""
    if obj.type == 'MESH':
        return [obj.matrix_world @ v.co for v in obj.data.vertices]
    if obj.type == 'CURVE':
        pts = []
        for s in obj.data.splines:
            if s.type == 'BEZIER':
                pts.extend(obj.matrix_world @ p.co for p in s.bezier_points)
            else:
                pts.extend(obj.matrix_world @ p.co for p in s.points)
        return pts
    if obj.type == 'SURFACE':
        return [obj.matrix_world @ p.co for s in obj.data.splines for p in s.points]
    if obj.type == 'LATTICE':
        return [obj.matrix_world @ p.co for p in obj.data.points]
    if obj.type in GEOMETRY_TYPES:
        return [obj.matrix_world @ Vector(v) for v in obj.bound_box]
    return []


def world_aabb(obj):
    """单个对象的世界包围盒, 返回 AABB(mn, mx, center, minz); 无几何返回 None"""
    pts = _world_geom_points(obj)
    if not pts:
        return None
    mn = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    mx = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return AABB(mn, mx, (mn + mx) / 2, mn.z)


def world_aabb_multi(objs):
    """一组对象合并后的世界包围盒; 无几何返回 None"""
    pts = []
    for o in objs:
        pts.extend(_world_geom_points(o))
    if not pts:
        return None
    mn = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    mx = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return AABB(mn, mx, (mn + mx) / 2, mn.z)


def get_world_origin_avg(objs):
    """所有对象原点(世界坐标)的平均值"""
    if not objs:
        return None
    total = Vector()
    for o in objs:
        total += o.matrix_world.translation
    return total / len(objs)


def get_world_verts_avg(objs):
    """所有网格顶点的平均位置(世界坐标)"""
    total = Vector()
    count = 0
    for o in objs:
        if o.type == 'MESH':
            for v in o.data.vertices:
                total += o.matrix_world @ v.co
                count += 1
    if count == 0:
        return None
    return total / count


# ----------------------------------------------------------------------------
# 变换工具
# ----------------------------------------------------------------------------
def _transform_geom_data(obj, matrix):
    """对对象几何数据应用局部矩阵变换(轴移动时的逆向补偿)。
    用官方 data.transform(): 正确处理 Bezier ALIGNED/AUTO 控制柄约束;
    不支持的几何类型返回 False。"""
    try:
        obj.data.transform(matrix)
        return True
    except Exception:
        return False


def set_origin_to_world_point(obj, target):
    """把对象原点(轴)移动到世界坐标 target, 几何世界位置不变(仅改轴)。
    返回 True 表示成功; META/FONT 等无顶点数据可改的类型返回 False。"""
    mw_old = obj.matrix_world.copy()
    mw_new = mw_old.copy()
    mw_new.translation = target
    obj.matrix_world = mw_new
    m = mw_new.inverted() @ mw_old
    return _transform_geom_data(obj, m)


def origin_bottom_center(obj):
    """对象底部中心(几何中心 xy + 最低点 z); 无几何返回 None"""
    aabb = world_aabb(obj)
    if aabb is None:
        return None
    return Vector((aabb.center.x, aabb.center.y, aabb.minz))


def land_to_ground(obj):
    """把对象整体下移, 使底部贴到 Z=0(网格移动); 成功返回 True"""
    aabb = world_aabb(obj)
    if aabb is None:
        return False
    mw = obj.matrix_world.copy()
    mw.translation.z -= aabb.minz
    obj.matrix_world = mw
    return True


# ----------------------------------------------------------------------------
# 核心算法: 对齐到子物体中心
# ----------------------------------------------------------------------------
def align_to_children(obj, mode):
    """
    把 obj 移动到它的子物体中心, 同时保持子物体世界位置不变。
    返回对齐后的世界坐标; 无子物体或无法计算时返回 None。
    """
    children = list(obj.children_recursive)
    if not children:
        return None

    if mode == 'BBOX':
        aabb = world_aabb_multi(children)
        center = aabb.center if aabb else None
    elif mode == 'ORIGIN':
        center = get_world_origin_avg(children)
    elif mode == 'VERTS':
        center = get_world_verts_avg(children)
    else:
        return None

    if center is None:
        return None

    with preserve_children_world(children):
        mw = obj.matrix_world.copy()
        mw.translation = center
        obj.matrix_world = mw
    return center


# ----------------------------------------------------------------------------
# 选择 / 子物体保护 管理
# ----------------------------------------------------------------------------
@contextmanager
def preserve_selection(context):
    """临时切换选择后自动恢复原选择与 active 对象"""
    saved_active = context.active_object
    saved_selected = [o.name for o in context.selected_objects]
    try:
        yield
    finally:
        bpy.ops.object.select_all(action='DESELECT')
        for name in saved_selected:
            o = bpy.data.objects.get(name)
            if o:
                o.select_set(True)
        context.view_layer.objects.active = saved_active


@contextmanager
def preserve_children_world(children):
    """移动父级前记录子物体世界矩阵, 退出时恢复(避免父子联动拖走子物体)"""
    saved = {c: c.matrix_world.copy() for c in children}
    try:
        yield
    finally:
        for c, m in saved.items():
            c.matrix_world = m


# ----------------------------------------------------------------------------
# 层级工具: 居中(自身+子集)
# ----------------------------------------------------------------------------
def _collect_tree(obj, depth, out):
    """递归收集 obj 及其全部后代, 记录层级深度"""
    out.append((obj, depth))
    for ch in obj.children:
        _collect_tree(ch, depth + 1, out)


def collect_self_and_descendants(objects):
    """收集选中对象及全部后代, 去重并按深度从深到浅排序"""
    items = []
    for obj in objects:
        _collect_tree(obj, 0, items)
    seen = set()
    dedup = []
    for o, d in items:
        if o.name not in seen:
            seen.add(o.name)
            dedup.append((o, d))
    dedup.sort(key=lambda x: -x[1])
    return [o for o, _d in dedup]


def center_object_itself(obj, mode, context):
    """
    对单个对象执行"居中"(轴体操作):
      - 空物体: 移动到它所有子物体的中心 (align_to_children)
      - 有几何类型: 轴居中到几何中心 (set_origin_to_world_point, 带子物体保护);
        META/FONT 无顶点数据, 回退原生 origin_set
    返回 True 表示处理成功。
    """
    if obj.type == 'EMPTY':
        return align_to_children(obj, mode) is not None

    children = list(obj.children_recursive)
    aabb = world_aabb(obj)
    if aabb is None:
        return False

    with preserve_children_world(children):
        if not set_origin_to_world_point(obj, aabb.center):
            # META/FONT 等无顶点数据可改的类型: 回退原生 origin_set
            with preserve_selection(context):
                bpy.ops.object.select_all(action='DESELECT')
                obj.select_set(True)
                context.view_layer.objects.active = obj
                bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')
    context.view_layer.update()
    return True


# ----------------------------------------------------------------------------
# 属性 / 操作符 / 面板
# ----------------------------------------------------------------------------
def register_props():
    bpy.types.Scene.empty_center_mode = bpy.props.EnumProperty(
        name="中心模式",
        description="定义子物体的\"中心\"(仅影响空物体定位)",
        items=[
            ('BBOX', "包围盒中心", "所有子物体世界包围盒的中心(最常用)"),
            ('ORIGIN', "原点平均", "所有子物体原点位置的平均值"),
            ('VERTS', "顶点平均", "所有网格顶点坐标的平均值(接近体积中心)"),
        ],
        default='BBOX',
    )


def unregister_props():
    del bpy.types.Scene.empty_center_mode


class OBJECT_OT_AlignEmptyToChildren(bpy.types.Operator):
    bl_idname = "object.align_empty_to_children"
    bl_label = "对齐到子物体中心"
    bl_description = "(单对象快捷操作, 面板按钮'居中(自身+子集)'已覆盖含子集) 把选中的每个对象移动到各自子物体的中心, 子物体位置不变"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects)

    def execute(self, context):
        mode = context.scene.empty_center_mode
        done, skipped = [], []
        for obj in context.selected_objects:
            center = align_to_children(obj, mode)
            if center is None:
                skipped.append(obj.name)
            else:
                done.append(obj.name)
        if done:
            brief = ", ".join(done[:5]) + ("..." if len(done) > 5 else "")
            self.report({'INFO'}, "已对齐 %d 个对象: %s" % (len(done), brief))
            if skipped:
                self.report({'WARNING'},
                            "%d 个对象没有子物体, 已跳过: %s" % (len(skipped), ", ".join(skipped[:5])))
            return {'FINISHED'}
        self.report({'WARNING'}, "选中的对象都没有子物体, 无法对齐")
        return {'CANCELLED'}


class OBJECT_OT_OriginToCenter(bpy.types.Operator):
    bl_idname = "object.origin_to_geometry_center"
    bl_label = "原点居中(自身几何中心)"
    bl_description = "(单对象快捷操作) 把选中对象的原点移到它自身的几何中心, 网格位置不变"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects)

    def execute(self, context):
        done = 0
        for obj in context.selected_objects:
            if obj.type != 'MESH':
                continue
            aabb = world_aabb(obj)
            if aabb is None:
                continue
            set_origin_to_world_point(obj, aabb.center)
            done += 1
        if done == 0:
            self.report({'WARNING'}, "没有可处理的网格对象")
            return {'CANCELLED'}
        self.report({'INFO'}, "已把 %d 个对象的原点居中到几何中心(网格不动)" % done)
        return {'FINISHED'}


class OBJECT_OT_AlignBottomToGround(bpy.types.Operator):
    bl_idname = "object.align_bottom_to_ground"
    bl_label = "轴贴底部"
    bl_description = "(单对象快捷操作, 面板'轴居中贴底'已覆盖含子集) 把选中对象的轴(原点)对齐到物体自身底部, 网格位置不变"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects)

    def execute(self, context):
        done = 0
        for obj in context.selected_objects:
            if obj.type != 'MESH':
                continue
            aabb = world_aabb(obj)
            if aabb is None:
                continue
            target = obj.matrix_world.translation.copy()
            target.z = aabb.minz
            set_origin_to_world_point(obj, target)
            done += 1
        if done == 0:
            self.report({'WARNING'}, "没有可处理的网格对象")
            return {'CANCELLED'}
        self.report({'INFO'}, "已把 %d 个对象的轴贴到底部(网格不动)" % done)
        return {'FINISHED'}


def center_tree_objects(objects, mode, context):
    """
    按钮1逻辑: 对选中对象及全部后代逐个"居中"(空物体移到子物体中心, 几何轴居中到几何中心)。
    返回 (done_objects, skipped_names)。
    """
    dedup = collect_self_and_descendants(objects)
    done, skipped = [], []
    for obj in dedup:
        if center_object_itself(obj, mode, context):
            done.append(obj)
        else:
            skipped.append(obj.name)
    return done, skipped


def align_axis_to_bottom(obj):
    """按钮2追加步骤: 把轴从当前位置移到底部(轴 z -> 几何最低点), 几何不动。无几何返回 False"""
    aabb = world_aabb(obj)
    if aabb is None:
        return False
    target = obj.matrix_world.translation.copy()
    target.z = aabb.minz
    return set_origin_to_world_point(obj, target)


def align_empty_to_children_bottom(empty, mode):
    """空物体的"贴底": 把它移到子物体包围盒的底部中心(几何中心 xy + 最低点 z)。
    保持子物体世界位置不变。无子物体返回 None。"""
    children = list(empty.children_recursive)
    aabb = world_aabb_multi(children) if children else None
    if aabb is None:
        return None
    target = Vector((aabb.center.x, aabb.center.y, aabb.minz))
    with preserve_children_world(children):
        mw = empty.matrix_world.copy()
        mw.translation = target
        empty.matrix_world = mw
    return target


def apply_axis_steps(done_objects, mode, land):
    """按钮2/3共用: 对已居中的对象执行"贴底"(land=True 时再整体落地)。
    空物体移到子物体底部中心, 几何对象轴贴底(+落地)。返回处理数。"""
    count = 0
    for obj in done_objects:
        if obj.type == 'EMPTY':
            if align_empty_to_children_bottom(obj, mode) is not None:
                count += 1
        elif align_axis_to_bottom(obj):
            if land:
                land_to_ground(obj)
            count += 1
    return count


class OBJECT_OT_CenterThenAlignBottom(bpy.types.Operator):
    bl_idname = "object.center_then_align_bottom"
    bl_label = "轴居中贴底(一键)"
    bl_description = "= 居中(自身+子集) + 把每个几何对象的轴移到自己底部(几何不动)"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects)

    def execute(self, context):
        mode = context.scene.empty_center_mode
        done, skipped = center_tree_objects(context.selected_objects, mode, context)
        bottom = apply_axis_steps(done, mode, land=False)
        if not done:
            self.report({'WARNING'}, "没有可居中的对象")
            return {'CANCELLED'}
        self.report({'INFO'}, "已居中 %d 个对象, 其中 %d 个轴贴底(含空物体)" % (len(done), bottom))
        if skipped:
            self.report({'WARNING'}, "跳过 %d 个无几何且非空物体的对象" % len(skipped))
        return {'FINISHED'}


class OBJECT_OT_CenterBottomAndLand(bpy.types.Operator):
    bl_idname = "object.center_bottom_and_land"
    bl_label = "轴居中贴底并落地"
    bl_description = "= 轴居中贴底 + 把每个几何对象整体下移贴到 Z=0"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects)

    def execute(self, context):
        mode = context.scene.empty_center_mode
        done, skipped = center_tree_objects(context.selected_objects, mode, context)
        landed = apply_axis_steps(done, mode, land=True)
        if not done:
            self.report({'WARNING'}, "没有可居中的对象")
            return {'CANCELLED'}
        self.report({'INFO'}, "已居中 %d 个对象, 其中 %d 个轴贴底并落地(含空物体)" % (len(done), landed))
        if skipped:
            self.report({'WARNING'}, "跳过 %d 个无几何且非空物体的对象" % len(skipped))
        return {'FINISHED'}


class OBJECT_OT_CenterAllWithChildren(bpy.types.Operator):
    bl_idname = "object.center_all_with_children"
    bl_label = "居中(自身+子集)"
    bl_description = "选中的对象及其所有子物体逐个居中: 模型原点居中到几何中心, 空物体移到子物体中心"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects)

    def execute(self, context):
        mode = context.scene.empty_center_mode
        done_objs, skipped = center_tree_objects(context.selected_objects, mode, context)
        done = [o.name for o in done_objs]

        if done:
            brief = ", ".join(done[:5]) + ("..." if len(done) > 5 else "")
            self.report({'INFO'}, "已居中 %d 个对象: %s" % (len(done), brief))
            if skipped:
                self.report({'WARNING'}, "跳过 %d 个无几何且非空物体的对象" % len(skipped))
            return {'FINISHED'}
        self.report({'WARNING'}, "没有可居中的对象")
        return {'CANCELLED'}


class OBJECT_PT_EmptyAlignPanel(bpy.types.Panel):
    bl_label = "对象轴与居中工具"
    bl_idname = "OBJECT_PT_EmptyAlignPanel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Tool"

    def draw(self, context):
        layout = self.layout
        layout.label(text="选中任意对象(可多选), 含子集统一处理")
        layout.prop(context.scene, "empty_center_mode", expand=True)
        layout.operator("object.center_all_with_children", icon='SNAP_ON')
        layout.separator()
        layout.label(text="轴定位:")
        layout.operator("object.center_then_align_bottom", icon='OBJECT_DATA')
        layout.operator("object.center_bottom_and_land", icon='SNAP_FACE')


# ----------------------------------------------------------------------------
# 注册
# ----------------------------------------------------------------------------
classes = (
    OBJECT_OT_AlignEmptyToChildren,
    OBJECT_OT_OriginToCenter,
    OBJECT_OT_AlignBottomToGround,
    OBJECT_OT_CenterThenAlignBottom,
    OBJECT_OT_CenterBottomAndLand,
    OBJECT_OT_CenterAllWithChildren,
    OBJECT_PT_EmptyAlignPanel,
)


def register():
    register_props()
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    unregister_props()


if __name__ == "__main__":
    register()
