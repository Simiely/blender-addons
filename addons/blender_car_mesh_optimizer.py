"""Car Mesh Optimizer v3.4 — 高面车模智能减面

选取特征点 → 调参数 → 一键生成优化网格
顶点组加权 Decimate + 松散块分离 + 边界保护 + 四边面 + 镜像
"""
bl_info = {
    "name": "Car Mesh Optimizer",
    "author": "Simiely",
    "version": (3, 4, 0),
    "blender": (3, 6, 0),
    "location": "3D 视图 > 右侧边栏 > 车模减面",
    "description": "高面车模智能减面 — 选点定密度，Decimate + 细分 + 包裹",
    "category": "Mesh",
    "support": "COMMUNITY",
    "doc_url": "https://github.com/Simiely/blender-car-mesh-optimizer",
    "tracker_url": "https://github.com/Simiely/blender-car-mesh-optimizer/issues",
}

import bpy
import bmesh
from bpy.props import (
    IntProperty, FloatProperty, BoolProperty, StringProperty, PointerProperty,
    EnumProperty,
)
from mathutils.kdtree import KDTree


# ══════════════ 工具 ══════════════

def _active_mesh(ctx):
    obj = ctx.active_object
    return obj if (obj and obj.type == 'MESH') else None

def _tri_count(obj):
    return sum(max(1, len(p.vertices) - 2) for p in obj.data.polygons)

def _ensure_obj_mode():
    try:
        if bpy.context.object and bpy.context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
    except Exception:
        pass

def _safe_remove_mods(obj, prefix):
    for m in list(obj.modifiers):
        if m.name.startswith(prefix):
            try:
                obj.modifiers.remove(m)
            except Exception:
                pass

def _sel_count_in_edit(obj, mode='VERT'):
    """编辑模式下从 bmesh 读选中数"""
    try:
        bm = bmesh.from_edit_mesh(obj.data)
        if mode == 'EDGE':
            return sum(1 for e in bm.edges if e.select)
        return sum(1 for v in bm.verts if v.select)
    except Exception:
        return 0


# ══════════════ 选点 → 特征边 ══════════════

def _verts_to_edges(obj, bm):
    """选中顶点 → 选中两端都被选中的边 → 同步到 obj.data"""
    for e in obj.data.edges:
        e.select = False
    cnt = 0
    selected_verts = {v.index for v in bm.verts if v.select}
    for e in bm.edges:
        if e.verts[0].index in selected_verts and e.verts[1].index in selected_verts:
            e.select = True
            if e.index < len(obj.data.edges):
                obj.data.edges[e.index].select = True
            cnt += 1
    return cnt


def _build_kdtree(obj):
    """从 obj.data.edges 选中状态构建 KDTree (边中点)"""
    pts, idxs = [], []
    for e in obj.data.edges:
        if e.select:
            v0 = obj.data.vertices[e.vertices[0]].co
            v1 = obj.data.vertices[e.vertices[1]].co
            pts.append((v0 + v1) / 2.0)
            idxs.append(e.index)
    if not pts:
        return None, [], 0
    kd = KDTree(len(pts))
    for i, p in enumerate(pts):
        kd.insert((p.x, p.y, p.z), i)
    kd.balance()
    return kd, idxs, len(idxs)


# ══════════════ 引擎 ══════════════

def _shrinkwrap(obj, target, offset=0.0005):
    _ensure_obj_mode()
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    _safe_remove_mods(obj, "CD_SW")
    mod = obj.modifiers.new(name="CD_SW", type='SHRINKWRAP')
    mod.wrap_method = 'PROJECT'
    mod.target = target
    mod.offset = offset
    mod.use_project_x = mod.use_project_y = mod.use_project_z = True
    mod.use_positive_direction = mod.use_negative_direction = True
    bpy.ops.object.modifier_apply(modifier=mod.name)


def _build_protected_verts(orig):
    """构建保护顶点集合：特征边两端顶点 + 边界边顶点"""
    protected = set()
    # 特征边顶点
    for e in orig.data.edges:
        if e.select:
            protected.add(e.vertices[0])
            protected.add(e.vertices[1])
    # 边界边顶点（仅邻接 1 个面 → 模型边缘 / 多部件接缝）
    bm = bmesh.new()
    bm.from_mesh(orig.data)
    bm.edges.ensure_lookup_table()
    for e in bm.edges:
        if len(e.link_faces) == 1:
            protected.add(e.verts[0].index)
            protected.add(e.verts[1].index)
    bm.free()
    return protected


def _island_count(obj):
    """统计网格中的松散块数量"""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    visited = set()
    islands = 0
    for f in bm.faces:
        if f.index in visited:
            continue
        islands += 1
        stack = [f]
        while stack:
            cf = stack.pop()
            if cf.index in visited:
                continue
            visited.add(cf.index)
            for e in cf.edges:
                for nf in e.link_faces:
                    if nf.index not in visited:
                        stack.append(nf)
    bm.free()
    return islands


def _process_separated(obj, nf_pct, feature_edge_select, use_shrinkwrap, use_quad):
    """分离松散块 → 各自减面 → 合并焊接 → 返回 (结果对象, 总面数)"""
    _ensure_obj_mode()
    
    prefix = "_carmesh_split_"
    # Step 1: 创建临时副本并复制边选中状态
    tmp_mesh = obj.data.copy()
    tmp_name = prefix + obj.name
    tmp_obj = bpy.data.objects.new(tmp_name, tmp_mesh)
    tmp_obj.matrix_world = obj.matrix_world.copy()
    bpy.context.collection.objects.link(tmp_obj)
    
    for e in tmp_mesh.edges:
        e.select = e.index in feature_edge_select
    
    # Step 2: 分离松散块
    bpy.ops.object.select_all(action='DESELECT')
    tmp_obj.select_set(True)
    bpy.context.view_layer.objects.active = tmp_obj
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.separate(type='LOOSE')
    bpy.ops.object.mode_set(mode='OBJECT')
    
    # Step 3: 收集所有分离出的块
    parts = [o for o in bpy.data.objects if o.name.startswith(prefix)]
    
    # Step 4: 每个块独立处理
    results = []
    part_meshes = []  # 追踪分离源 mesh 以便清理
    for p in parts:
        part_meshes.append(p.data)
    try:
        for part in parts:
            protected = _build_protected_verts(part)
            r, _ = _run_pipeline(part, nf_pct, protected,
                                 use_shrinkwrap=use_shrinkwrap, use_quad=use_quad)
            results.append(r)
    except Exception:
        # 清理已生成的结果对象
        for r in results:
            md = r.data
            for coll in r.users_collection:
                coll.objects.unlink(r)
            try:
                bpy.data.objects.remove(r)
            except Exception:
                pass
            if md and md.users == 0:
                try:
                    bpy.data.meshes.remove(md)
                except Exception:
                    pass
        # 清理分离源对象
        for p in parts:
            md = p.data
            for coll in p.users_collection:
                coll.objects.unlink(p)
            try:
                bpy.data.objects.remove(p)
            except Exception:
                pass
            if md and md.users == 0:
                try:
                    bpy.data.meshes.remove(md)
                except Exception:
                    pass
        raise
    
    # Step 5: 合并
    _ensure_obj_mode()
    bpy.ops.object.select_all(action='DESELECT')
    if len(results) == 1:
        robj = results[0]
    else:
        for r in results:
            r.select_set(True)
        bpy.context.view_layer.objects.active = results[0]
        bpy.ops.object.join()
        robj = results[0]
        # 焊接相邻块边缘接缝
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.remove_doubles(threshold=0.0001)
        bpy.ops.object.mode_set(mode='OBJECT')
    
    # Step 6: 清理分离源对象（保留合并结果）
    for p in parts:
        if p and p.name in bpy.data.objects and p != robj:
            md = p.data
            for coll in p.users_collection:
                coll.objects.unlink(p)
            try:
                bpy.data.objects.remove(p)
            except Exception:
                pass
            if md and md.users == 0 and md not in [r.data for r in results]:
                try:
                    bpy.data.meshes.remove(md)
                except Exception:
                    pass
    
    fc = _tri_count(robj)
    return robj, fc
    """新管线：顶点组加权 Decimate → 平面溶解 → 可选包裹 → 四边面"""
    mesh = orig.data.copy()
    mesh.name = orig.data.name + "_tmp"
    robj = bpy.data.objects.new(orig.name + "_tmp", mesh)
    robj.matrix_world = orig.matrix_world.copy()
    bpy.context.collection.objects.link(robj)
    try:
        _ensure_obj_mode()
        bpy.ops.object.select_all(action='DESELECT')
        robj.select_set(True)
        bpy.context.view_layer.objects.active = robj

        # ── 步骤1：顶点组加权 Decimate ──
        if protected_verts:
            vg = robj.vertex_groups.new(name="CD_Protect")
            all_idx = list(range(len(robj.data.vertices)))
            vg.add(all_idx, 0.0, 'REPLACE')
            for i in protected_verts:
                if i < len(robj.data.vertices):
                    vg.add([i], 1.0, 'REPLACE')

        mod = robj.modifiers.new(name="CD_Dec", type='DECIMATE')
        mod.decimate_type = 'COLLAPSE'
        mod.ratio = min(1.0, max(0.01, nf_pct / 100.0))
        mod.use_collapse_triangulate = True
        if protected_verts:
            mod.vertex_group = vg.name
            mod.vertex_group_factor = 1.0
        bpy.ops.object.modifier_apply(modifier=mod.name)

        # ── 步骤2：可选 Shrinkwrap ──
        if use_shrinkwrap:
            _shrinkwrap(robj, orig, 0.0002)

        # ── 步骤3：平面溶解（清理共面三角对） ──
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        try:
            bpy.ops.mesh.dissolve_limited(angle_limit=0.087)  # ~5°
        except Exception:
            pass
        bpy.ops.object.mode_set(mode='OBJECT')

        # ── 步骤4：四边面转换（循环多轮） ──
        if use_quad:
            for _ in range(3):
                prev = _tri_count(robj)
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.select_all(action='SELECT')
                try:
                    bpy.ops.mesh.tris_convert_to_quads(
                        face_threshold=0.785, shape_threshold=0.785,
                        uvs=False, vcols=False, materials=False)
                except Exception:
                    pass
                bpy.ops.object.mode_set(mode='OBJECT')
                if _tri_count(robj) == prev:
                    break

        return robj, _tri_count(robj)
    except Exception:
        if robj:
            for coll in robj.users_collection:
                coll.objects.unlink(robj)
            bpy.data.objects.remove(robj)
        if mesh and mesh.users == 0:
            bpy.data.meshes.remove(mesh)
        raise


# ══════════════ 属性 ══════════════

class CarDecimatorSettings(bpy.types.PropertyGroup):
    feature_keep: FloatProperty(
        name="特征区保留比例", default=30.0, min=1.0, max=100.0,
        subtype='PERCENTAGE',
        description="特征点附近的保留比例，越高越密")
    nonfeature_keep: FloatProperty(
        name="非特征区保留比例", default=5.0, min=1.0, max=100.0,
        subtype='PERCENTAGE',
        description="远离特征点的保留比例，越低面越少")
    density_threshold: FloatProperty(
        name="密集度阈值", default=0.05, min=0.001, max=10.0,
        step=0.001, precision=3, subtype='DISTANCE', unit='LENGTH',
        description="相邻边平均长度小于此值的点被视为密集区")
    selected_count: IntProperty(name="已选点数", default=0)
    has_selection: BoolProperty(name="已选取特征点", default=False)
    original_face_count: IntProperty(name="原始面数", default=0)
    original_obj_name: StringProperty(name="原始对象", default="")
    result_face_count: IntProperty(name="结果面数", default=0)
    result_name: StringProperty(name="结果名称", default="")
    use_quad: BoolProperty(
        name="生成四边面", default=True,
        description="尽可能将三角面合并为四边面（循环转换）")
    use_shrinkwrap: BoolProperty(
        name="收缩包裹", default=False,
        description="用原模型收缩包裹生成结果（薄壳模型慎用，可能产生形变）")
    mirror_axis: EnumProperty(
        name="镜像轴",
        items=[
            ('NONE', "无", "不生成镜像"),
            ('X', "X 轴", "沿 X 轴左右镜像"),
            ('Y', "Y 轴", "沿 Y 轴前后镜像"),
            ('Z', "Z 轴", "沿 Z 轴上下镜像"),
        ],
        default='NONE',
        description="生成对称网格的镜像轴")



PRESETS = {
    "DEFAULT": {"name": "默认",   "fv": 30, "nf": 5},
    "HIGH":    {"name": "高精度", "fv": 50, "nf": 10},
    "LOW":     {"name": "低面数", "fv": 15, "nf": 2},
    "BALANCE": {"name": "均衡",   "fv": 25, "nf": 5},
}


def _apply_preset(s, key):
    p = PRESETS.get(key, PRESETS["DEFAULT"])
    s.feature_keep = p["fv"]
    s.nonfeature_keep = p["nf"]


# ══════════════ Operators ══════════════

class CARMESH_OT_prepare(bpy.types.Operator):
    bl_idname = "carmesh.prepare"
    bl_label = "选取特征点"
    bl_description = "进入编辑模式手动选择密集区域的关键顶点"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, ctx):
        obj = _active_mesh(ctx)
        if not obj:
            self.report({'ERROR'}, "请先选中一个网格对象")
            return {'CANCELLED'}
        s = ctx.scene.car_decimator
        s.original_face_count = _tri_count(obj)
        s.original_obj_name = obj.name
        s.has_selection = False
        s.selected_count = 0
        s.result_face_count = 0
        s.result_name = ""
        if obj.mode != 'EDIT':
            bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_mode(type='VERT')
        self.report({'INFO'}, "选好特征点后切回物体模式，点击确认")
        return {'FINISHED'}


class CARMESH_OT_select_dense(bpy.types.Operator):
    bl_idname = "carmesh.select_dense"
    bl_label = "按密度选点"
    bl_description = "自动选中相邻边短于阈值的密集区域顶点"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, ctx):
        obj = _active_mesh(ctx)
        if not obj:
            self.report({'ERROR'}, "请先选中一个网格对象")
            return {'CANCELLED'}
        t = ctx.scene.car_decimator.density_threshold
        if obj.mode != 'EDIT':
            bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_mode(type='VERT')
        bpy.ops.mesh.select_all(action='DESELECT')
        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        cnt = 0
        for v in bm.verts:
            if not v.link_edges:
                continue
            avg_len = sum(e.calc_length() for e in v.link_edges) / len(v.link_edges)
            if avg_len < t:
                v.select = True
                cnt += 1
        bmesh.update_edit_mesh(obj.data)
        # 同步选择到 obj.data（确保物体模式下也能读到）
        sel_set = {v.index for v in bm.verts if v.select}
        for v in obj.data.vertices:
            v.select = v.index in sel_set
        # 强制刷新所有 3D 视图
        for a in ctx.screen.areas:
            if a.type == 'VIEW_3D':
                a.tag_redraw()
        if cnt == 0:
            self.report({'WARNING'}, f"没有平均边长 < {t:.3f}m 的点")
        else:
            self.report({'INFO'}, f"已选中 {cnt} 个密集点")
        return {'FINISHED'}


class CARMESH_OT_capture(bpy.types.Operator):
    bl_idname = "carmesh.capture"
    bl_label = "确认选取"
    bl_description = "将选中的点转为特征边并记录"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, ctx):
        obj = _active_mesh(ctx)
        if not obj:
            self.report({'ERROR'}, "请先选中一个网格对象")
            return {'CANCELLED'}
        s = ctx.scene.car_decimator
        if obj.mode == 'EDIT':
            bm = bmesh.from_edit_mesh(obj.data)
            cnt = _verts_to_edges(obj, bm)
            bmesh.update_edit_mesh(obj.data)
        else:
            # 物体模式：已有顶点选中，直接取边
            sv = {v.index for v in obj.data.vertices if v.select}
            for e in obj.data.edges:
                e.select = False
            cnt = 0
            for e in obj.data.edges:
                if e.vertices[0] in sv and e.vertices[1] in sv:
                    e.select = True
                    cnt += 1
        s.selected_count = cnt
        s.has_selection = cnt > 0
        if cnt == 0:
            self.report({'WARNING'}, "未匹配到特征边，请至少选 2 个相邻顶点")
            return {'CANCELLED'}
        self.report({'INFO'}, f"已记录 {cnt} 条特征边")
        return {'FINISHED'}


class CARMESH_OT_optimize(bpy.types.Operator):
    bl_idname = "carmesh.optimize"
    bl_label = "生成优化网格"
    bl_description = "一键生成优化后的网格"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, ctx):
        obj = _active_mesh(ctx)
        if not obj:
            self.report({'ERROR'}, "请先选中一个网格对象")
            return {'CANCELLED'}
        s = ctx.scene.car_decimator
        if not s.has_selection:
            self.report({'ERROR'}, "请先选取特征点并确认")
            return {'CANCELLED'}
        fp, np_ = s.feature_keep, s.nonfeature_keep
        if fp <= np_:
            self.report({'ERROR'}, f"特征区保留({fp:.0f}%)必须大于非特征区({np_:.0f}%)")
            return {'CANCELLED'}
        _ensure_obj_mode()  # 确保边选择状态已同步到 obj.data
        # 收集原始对象的特征边索引
        feature_edges = {e.index for e in obj.data.edges if e.select}
        if not feature_edges:
            self.report({'ERROR'}, "特征线数据异常，请重新选取")
            return {'CANCELLED'}
        # 检测松散块数量
        islands = _island_count(obj)
        self.report({'INFO'}, f"检测到 {islands} 个松散块，正在生成...")
        try:
            if islands > 1:
                robj, fc = _process_separated(obj, np_, feature_edges,
                                              use_shrinkwrap=s.use_shrinkwrap,
                                              use_quad=s.use_quad)
            else:
                protected = _build_protected_verts(obj)
                robj, fc = _run_pipeline(obj, np_, protected,
                                         use_shrinkwrap=s.use_shrinkwrap,
                                         use_quad=s.use_quad)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.report({'ERROR'}, f"生成失败: {e}")
            return {'CANCELLED'}
        base = obj.name + "_优化"
        name = base
        i = 1
        while bpy.data.objects.get(name):
            name = f"{base}_{i}"
            i += 1
        robj.name = name
        robj.data.name = name
        robj.display_type = 'SOLID'
        # 镜像：复制网格 → 翻转 X → 合并 → 焊接接缝
        mirror_obj = None
        if s.mirror_axis != 'NONE':
            _ensure_obj_mode()
            axis_map = {'X': 0, 'Y': 1, 'Z': 2}
            idx = axis_map[s.mirror_axis]
            mirror_mesh = robj.data.copy()
            mirror_mesh.name = robj.data.name + "_mirror"
            mirror_obj = bpy.data.objects.new(name + "_mirror", mirror_mesh)
            mirror_obj.matrix_world = robj.matrix_world.copy()
            mirror_obj.scale[idx] *= -1
            bpy.context.collection.objects.link(mirror_obj)
            bpy.ops.object.select_all(action='DESELECT')
            robj.select_set(True)
            mirror_obj.select_set(True)
            bpy.context.view_layer.objects.active = robj
            bpy.ops.object.join()
            mirror_obj = None
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.remove_doubles(threshold=0.0001)
            bpy.ops.object.mode_set(mode='OBJECT')
            fc = _tri_count(robj)
        bpy.ops.object.select_all(action='DESELECT')
        robj.select_set(True)
        ctx.view_layer.objects.active = robj
        ofc = s.original_face_count
        s.result_face_count = fc
        s.result_name = name + ("（对称）" if s.mirror_axis != 'NONE' else "")
        s.has_selection = False
        s.selected_count = 0
        msg = f"已生成: {name}, {fc:,} 面"
        if ofc > 0:
            msg += f" (原始 {ofc:,}, -{(1-fc/ofc)*100:.1f}%)"
        self.report({'INFO'}, msg)
        return {'FINISHED'}


class CARMESH_OT_preset(bpy.types.Operator):
    bl_idname = "carmesh.preset"
    bl_label = "快速预设"
    bl_options = {'REGISTER', 'UNDO'}
    preset_key: bpy.props.StringProperty()

    def execute(self, ctx):
        _apply_preset(ctx.scene.car_decimator, self.preset_key)
        self.report({'INFO'}, "已应用预设")
        return {'FINISHED'}


# ══════════════ 面板 ══════════════

class CARMESH_PT_main(bpy.types.Panel):
    bl_label = "车模网格减面"
    bl_idname = "CARMESH_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "车模减面"

    def draw(self, ctx):
        layout = self.layout
        try:
            s = ctx.scene.car_decimator
        except AttributeError:
            layout.label(text="插件未正确加载", icon='ERROR')
            return
        obj = _active_mesh(ctx)

        box = layout.box()
        box.label(text="当前模型", icon='OBJECT_DATA')
        if obj is None:
            box.label(text="请选择一个网格对象", icon='ERROR')
            return
        box.label(text=f"名称: {obj.name}")
        box.label(text=f"原始面数: {_tri_count(obj):,}")

        # 选点
        box = layout.box()
        box.label(text="步骤 1  选取特征点", icon='VERTEXSEL')
        if s.has_selection:
            col = box.column(align=True)
            col.label(text=f"已记录 {s.selected_count} 条特征边", icon='CHECKMARK')
            col.operator("carmesh.prepare", text="重新选取")
        else:
            col = box.column(align=True)
            col.operator("carmesh.prepare", text="手动选取特征点")
            row = col.row(align=True)
            row.prop(s, "density_threshold", text="密集阈值")
            row.operator("carmesh.select_dense", text="", icon='AUTO')
            col.label(text="选好后切回物体模式点确认", icon='INFO')
            cnt = _sel_count_in_edit(obj) if obj.mode == 'EDIT' else sum(1 for v in obj.data.vertices if v.select)
            # 回退：bmesh 暂不可用时从 obj.data 读
            if cnt == 0 and obj.mode == 'EDIT':
                cnt = sum(1 for v in obj.data.vertices if v.select)
            if cnt > 0:
                col.separator()
                col.operator("carmesh.capture",
                    text=f"确认选取 ({cnt} 个点)", icon='CHECKMARK')

        layout.separator()

        box = layout.box()
        box.label(text="步骤 2  密度参数", icon='PREFERENCES')
        row = box.row(align=True)
        for k, v in PRESETS.items():
            op = row.operator("carmesh.preset", text=v["name"])
            op.preset_key = k
        col = box.column(align=True)
        col.prop(s, "feature_keep", text="特征区保留")
        col.separator()
        col.prop(s, "nonfeature_keep", text="非特征区保留")
        r = s.feature_keep / max(s.nonfeature_keep, 1)
        col.label(text=f"特征区密度 x{r:.1f}", icon='SORTSIZE')

        layout.separator()

        box = layout.box()
        box.label(text="步骤 3  生成", icon='RESTRICT_RENDER_OFF')
        col = box.column(align=True)
        col.prop(s, "use_quad", text="生成四边面")
        col.prop(s, "use_shrinkwrap", text="收缩包裹（薄壳慎用）")
        col.prop(s, "mirror_axis", text="镜像轴")
        col.separator()
        col.scale_y = 1.8
        col.operator("carmesh.optimize", text="生成优化网格", icon='CHECKMARK')

        layout.separator()

        if s.result_name:
            box = layout.box()
            box.label(text="上次结果", icon='INFO')
            col = box.column(align=True)
            col.label(text=f"{s.result_name}", icon='OUTLINER_OB_MESH')
            col.label(text=f"{s.result_face_count:,} 面", icon='MESH_DATA')
            ofc = s.original_face_count
            if ofc > 0:
                pct = s.result_face_count / ofc * 100
                col.label(text=f"占比 {pct:.1f}% (-{(100-pct):.1f}%)")


# ══════════════ 注册 ══════════════

CLASSES = (
    CarDecimatorSettings,
    CARMESH_OT_prepare, CARMESH_OT_select_dense, CARMESH_OT_capture,
    CARMESH_OT_optimize, CARMESH_OT_preset, CARMESH_PT_main,
)

def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.car_decimator = PointerProperty(type=CarDecimatorSettings)

def unregister():
    del bpy.types.Scene.car_decimator
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    register()
