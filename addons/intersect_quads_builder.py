# -*- coding: utf-8 -*-
# 名称: Intersect Quads Builder（交点四边面）
# 功能: 选取 1 个主对象（实体或面）+ N 个切割面，
#       两两切割面的交线与主对象表面的交点为"交点"(xyz 确定)，
#       再由交点自动生成贴合主对象表面的四边形网格。
# 模式:
#   AUTO      - 自动判断: 切割面能聚成 2 组方向 -> 索引网格(纯四边面), 否则 Delaunay
#   GRID      - 强制索引网格(切割面聚成 2 组, 跨组组合的交点按行列连四边面)
#   DELAUNAY  - 全部交点做 2D Delaunay 三角化 + 相邻三角对合并(四边形为主)
# 面板位置: 3D 视图 -> 侧边栏(N) -> Intersect Quads

bl_info = {
    "name": "Intersect Quads Builder",
    "author": "Simiely",
    "version": (0, 2, 0),
    "blender": (2, 80, 0),
    "location": "3D 视图 > 侧边栏(N) > 交点四边面",
    "description": "切割面交线 x 主对象表面 -> 交点 -> 自动四边面",
    "category": "Mesh",
}

import bpy
import bmesh
import math
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import intersect_plane_plane
from collections import defaultdict, namedtuple


# ------------------------------------------------------------------
# 几何工具
# ------------------------------------------------------------------

def obj_to_bmesh_world(obj, dg):
    """取对象评估后的 mesh 并变换到世界坐标, 返回 bmesh(调用方负责 free)"""
    bm = bmesh.new()
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    bm.from_mesh(me)
    bm.transform(obj.matrix_world)
    ev.to_mesh_clear()
    return bm


def bm_bbox_diagonal(bm):
    """手写包围盒对角线长度(兼容各版本; Blender 5.x 移除了 bm.calc_bbox())"""
    if not bm.verts:
        return 0.0
    it = iter(bm.verts)
    v = next(it)
    lo = v.co.copy()
    hi = v.co.copy()
    for v in it:
        c = v.co
        if c.x < lo.x:
            lo.x = c.x
        elif c.x > hi.x:
            hi.x = c.x
        if c.y < lo.y:
            lo.y = c.y
        elif c.y > hi.y:
            hi.y = c.y
        if c.z < lo.z:
            lo.z = c.z
        elif c.z > hi.z:
            hi.z = c.z
    return (hi - lo).length


def mesh_polys_world(obj, dg):
    """世界坐标下的多边形顶点列表"""
    bm = obj_to_bmesh_world(obj, dg)
    polys = []
    for f in bm.faces:
        polys.append([v.co.copy() for v in f.verts])
    bm.free()
    return polys


def plane_of(verts):
    """由顶点求平面(中心点, 单位法线)"""
    co = sum(verts, Vector((0, 0, 0))) / len(verts)
    no = (verts[1] - verts[0]).cross(verts[2] - verts[0])
    if no.length < 1e-9:
        return None
    no.normalize()
    return co, no


def line_of_planes(coA, noA, coB, noB):
    """两平面(中心点+单位法线) -> 交线 (co, dir) ; 平行/共面返回 None"""
    res = intersect_plane_plane(coA, noA, coB, noB)
    if res is None:
        return None
    co, dirv = res
    if co is None or dirv is None or dirv.length < 1e-9:
        return None
    return co, dirv.normalized()


def distinct_planes(obj, dg, tol_ang=1e-3, tol_dist=1e-2):
    """从对象里聚类出所有"不同"的平面。

    规则: 同一对象内, 法线接近且共面(有符号距离 < tol_dist)的面合并为 1 个平面;
    法线接近但平行偏移(距离 > tol_dist, 如沿法线阵列出的平面)保留为多个平面。
    返回 [(co, no), ...], co 为面上一点, no 为单位法线。
    """
    polys = mesh_polys_world(obj, dg)
    planes = []
    for poly in polys:
        p = plane_of(poly)
        if p is None:
            continue
        co, no = p
        merged = False
        for (eco, eno) in planes:
            if no.dot(eno) < (1.0 - tol_ang):
                continue  # 法线不接近 -> 不同平面
            # 共面判定: 已存在平面上一点到新平面的有符号距离
            if abs((co - eco).dot(eno)) <= tol_dist:
                merged = True
                break
        if not merged:
            planes.append((co, no))
    return planes


def build_planes(cuts, dg, tol, use_all):
    """把切割对象列表扁平化为平面列表 [(co, no, src_obj_idx), ...]。

    use_all=True : 每个对象取全部不同平面(支持阵列/多面切割对象)
    use_all=False: 回退旧行为, 每个对象仅取首个面
    """
    planes = []
    for si, obj in enumerate(cuts):
        if use_all:
            pls = distinct_planes(obj, dg, tol_ang=max(tol * 10.0, 1e-3),
                                  tol_dist=max(tol * 10.0, 1e-2))
        else:
            polys = mesh_polys_world(obj, dg)
            p = plane_of(polys[0]) if polys else None
            pls = [p] if p else []
        for (co, no) in pls:
            planes.append((co, no, si))
    return planes


def ray_hits_all(bvh, origin, direction, max_dist):
    """从 origin 沿 direction 连续 ray_cast, 收集全部命中点(穿过多次也算)"""
    hits = []
    cur = origin
    remaining = max_dist
    eps = 1e-5
    while remaining > eps:
        loc, no, idx, dist = bvh.ray_cast(cur, direction, remaining)
        if loc is None:
            break
        hits.append(Vector(loc))
        remaining -= dist + eps
        cur = cur + direction * (dist + eps)
    return hits


def line_hits_solid(bvh, line_co, line_dir, solid_diag):
    """交线(无限长) 与主对象表面的全部交点(正反两个方向都射, 覆盖背面/薄片)"""
    d = solid_diag * 0.5 + 10.0
    hits = ray_hits_all(bvh, line_co - line_dir * d, line_dir, d * 2.0)
    hits += ray_hits_all(bvh, line_co + line_dir * d, -line_dir, d * 2.0)
    return hits


def dedup_points(points, tol):
    """按容差合并近似重合的点(网格哈希), 返回去重后的点与每个点的原始索引组"""
    if not points:
        return [], []
    # 包围盒 -> 网格
    minc = Vector((min(p[0] for p in points), min(p[1] for p in points), min(p[2] for p in points)))
    maxc = Vector((max(p[0] for p in points), max(p[1] for p in points), max(p[2] for p in points)))
    span = max((maxc - minc).length, tol * 4)
    cell = max(tol, span / 200.0)
    grid = {}
    result = []
    groups = []
    for p in points:
        key = (round(p[0] / cell), round(p[1] / cell), round(p[2] / cell))
        found = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    cand = grid.get((key[0] + dx, key[1] + dy, key[2] + dz))
                    if cand is not None and (p - cand).length <= tol:
                        found = cand
                        break
                if found is not None:
                    break
            if found is not None:
                break
        if found is None:
            grid[key] = p
            result.append(p)
    # 计算每个原始点到去重点的归属(距离最近)
    groups = []
    for p in points:
        best_i = min(range(len(result)), key=lambda i: (p - result[i]).length)
        groups.append(best_i)
    return result, groups


def cluster_by_normal_planes(planes):
    """按平面法线方向 k-means 聚成 2 组, 返回 (groupA, groupB) 平面下标列表"""
    normals = [no for (_, no, _) in planes]
    n = len(normals)
    if n < 2:
        return list(range(n)), []
    c0 = normals[0].normalized()
    c1 = min(normals, key=lambda x: x.normalized().dot(c0)).normalized()
    g0, g1 = [], []
    for _ in range(25):
        g0, g1 = [], []
        for i, nm in enumerate(normals):
            nv = nm.normalized()
            (g0 if nv.dot(c0) >= nv.dot(c1) else g1).append(i)
        if not g0 or not g1:
            break
        s0 = sum((normals[i] for i in g0), Vector((0, 0, 0)))
        s1 = sum((normals[i] for i in g1), Vector((0, 0, 0)))
        if s0.length < 1e-9 or s1.length < 1e-9:
            break
        c0, c1 = s0.normalized(), s1.normalized()
    return g0, g1


def sort_group_rank_planes(planes, group_idx, axis):
    """组内平面沿统一轴排序, 返回 {plane_idx: rank}"""
    items = []
    for i in group_idx:
        co = planes[i][0]
        items.append((co.dot(axis), i))
    items.sort(key=lambda x: x[0])
    return {i: r for r, (_, i) in enumerate(items)}


def build_grid_quads(grid, rows, cols):
    """grid: {(row_rank, col_rank): 去重点索引}; 返回四边形(索引列表)列表"""
    quads = []
    for ri in range(len(rows) - 1):
        for ci in range(len(cols) - 1):
            i00 = grid.get((rows[ri], cols[ci]))
            i10 = grid.get((rows[ri + 1], cols[ci]))
            i11 = grid.get((rows[ri + 1], cols[ci + 1]))
            i01 = grid.get((rows[ri], cols[ci + 1]))
            if None in (i00, i10, i11, i01):
                continue
            quads.append((i00, i10, i11, i01))
    return quads


# ------------------------------------------------------------------
# 管线步骤 (从 IQ_OT_Build.execute 抽出的构建函数, 便于单测)
# ------------------------------------------------------------------

CellHit = namedtuple("CellHit", ("a", "b", "gidx"))


class IntersectionData:
    """collect_intersections 的结果: 命中点 + 每点的平面对标签 + 交线方向表"""
    __slots__ = ("points", "labels", "dirs_by_pair")

    def __init__(self, points, labels, dirs_by_pair):
        self.points = points          # 全部命中点(Vector)
        self.labels = labels          # 每个点对应的 (a, b) 平面下标
        self.dirs_by_pair = dirs_by_pair  # (a, b) -> 交线单位方向(区分进/出点)


class BuildCtx:
    """索引网格构建的中间态, 把多个上游产物打包以减少函数参数"""
    __slots__ = ("planes", "dedup", "point_labels", "dirs_by_pair")

    def __init__(self, planes, dedup, point_labels, dirs_by_pair):
        self.planes = planes              # [(co, no, src_obj_idx), ...]
        self.dedup = dedup                # 去重后的交点(Vector)
        self.point_labels = point_labels  # {去重点gidx: set((a,b), ...)}
        self.dirs_by_pair = dirs_by_pair  # (a, b) -> 交线单位方向


def sort_cell_entries(entries, dirs_by_pair, dedup):
    """格内交点(CellHit 列表)按交线方向投影排序: 首=进点, 尾=出点"""
    d = None
    for e in entries:
        d = dirs_by_pair.get((e.a, e.b)) or dirs_by_pair.get((e.b, e.a))
        if d is not None:
            break
    if d is None:
        return entries
    return sorted(entries, key=lambda e: dedup[e.gidx].dot(d))


def collect_intersections(planes, bvh, solid_diag):
    """平面两两组合求交线, 交线与主对象表面求交点, 返回 IntersectionData。"""
    points = []
    labels = []
    dirs_by_pair = {}
    for a in range(len(planes)):
        coA, noA, _ = planes[a]
        for b in range(a + 1, len(planes)):
            coB, noB, _ = planes[b]
            line = line_of_planes(coA, noA, coB, noB)
            if line is None:
                continue  # 平行或共面, 无交线
            dirs_by_pair[(a, b)] = line[1]
            hits = line_hits_solid(bvh, line[0], line[1], solid_diag)
            for h in hits:
                points.append(h)
                labels.append((a, b))
    return IntersectionData(points, labels, dirs_by_pair)


def build_grid_faces(ctx, g0, g1, layer_mode):
    """GRID: 两组法线各自排秩, 跨组交线交点归入网格格, 生成四边形索引列表。
    ctx 为 BuildCtx(planes/dedup/point_labels/dirs_by_pair)。
    返回 (quad_faces, used_mode); 组退化/格不足时返回 (None, None)。
    layer_mode: "AUTO"/"SINGLE"/"DOUBLE" (AUTO 在此内部判定)。
    """
    planes = ctx.planes
    dedup = ctx.dedup
    axisA = Vector((0, 0, 0))
    for i in g0:
        axisA += planes[i][1]
    axisB = Vector((0, 0, 0))
    for i in g1:
        axisB += planes[i][1]
    if axisA.length < 1e-9 or axisB.length < 1e-9:
        return None, None
    axisA.normalize()
    axisB.normalize()
    rankA = sort_group_rank_planes(planes, g0, axisA)
    rankB = sort_group_rank_planes(planes, g1, axisB)
    # 每个去重点: 若来源标签是"跨组"(一个在 g0 一个在 g1),
    # 归入对应网格格 (ra, rb), 一格可能收集多个交点(进/出)
    cell_pts = defaultdict(list)   # (ra, rb) -> [CellHit(a, b, gidx), ...]
    for gidx in range(len(dedup)):
        for (a, b) in ctx.point_labels[gidx]:
            ra, rb = rankA.get(a), rankB.get(b)
            if ra is not None and rb is not None:
                cell_pts[(ra, rb)].append(CellHit(a, b, gidx))
                break
            ra, rb = rankA.get(b), rankB.get(a)
            if ra is not None and rb is not None:
                cell_pts[(ra, rb)].append(CellHit(a, b, gidx))
                break
    if len(cell_pts) < 4:
        return None, None
    rows = sorted({r for r, _ in cell_pts})
    cols = sorted({c for _, c in cell_pts})

    # 层数判定
    if layer_mode == "AUTO":
        counts = [len(v) for v in cell_pts.values()]
        multi = sum(1 for c in counts if c >= 2)
        layer_mode = "DOUBLE" if multi >= len(counts) * 0.5 else "SINGLE"

    if layer_mode == "DOUBLE":
        grid0, grid1 = {}, {}
        for (ra, rb), entries in cell_pts.items():
            se = sort_cell_entries(entries, ctx.dirs_by_pair, dedup)
            grid0[(ra, rb)] = se[0].gidx
            grid1[(ra, rb)] = se[-1].gidx
        q0 = build_grid_quads(grid0, rows, cols)
        q1 = build_grid_quads(grid1, rows, cols)
        quad_faces = [order_convex_quad(dedup, q) or q for q in q0 + q1]
        used_mode = "索引网格双层(%d 面)" % len(quad_faces)
    else:
        grid = {}
        for (ra, rb), entries in cell_pts.items():
            se = sort_cell_entries(entries, ctx.dirs_by_pair, dedup)
            grid[(ra, rb)] = se[0].gidx
        quad_faces = build_grid_quads(grid, rows, cols)
        # 按环绕序重排, 避免贴合曲面时四边形折叠
        quad_faces = [order_convex_quad(dedup, q) or q for q in quad_faces]
        used_mode = "索引网格(%d 面)" % len(quad_faces)
    return quad_faces, used_mode


def build_delaunay_faces(dedup, quad_angle):
    """DELAUNAY: 交点 PCA 投影 -> Bowyer-Watson 三角化 -> 合并四边形。
    返回 (quad_faces, tri_faces, error); error 为 None 表示成功。
    """
    pts2d = project_to_2d(dedup)
    if pts2d is None:
        return None, None, "交点退化共线/共点, 无法三角化"
    tris = bowyer_watson(pts2d)
    if not tris:
        return None, None, "三角化失败(交点过少?)"
    quad_faces, rem = merge_tris_to_quads(dedup, tris, quad_angle)
    tri_faces = [list(tris[ti]) for ti in rem]
    return quad_faces, tri_faces, None


def build_result_mesh(context, dedup, quad_faces, tri_faces):
    """用去重后的交点 + 面索引列表建 IQ_Result 对象并选中。
    返回 (obj, error); error 为 None 表示成功。
    """
    me = bpy.data.meshes.new("IQ_Result")
    bm = bmesh.new()
    verts = [bm.verts.new(p) for p in dedup]
    for q in quad_faces:
        try:
            bm.faces.new([verts[i] for i in q])
        except ValueError:
            pass
    for t in tri_faces:
        try:
            bm.faces.new([verts[i] for i in t])
        except ValueError:
            pass
    if not bm.faces:
        bm.free()
        return None, "没有生成任何面(交点太少或容差过大)"
    bm.normal_update()
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new("IQ_Result", me)
    context.collection.objects.link(obj)
    me.update()
    # 选中结果对象并设为活动对象, 便于立即检查
    for ob in context.selected_objects:
        ob.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj
    return obj, None


# ------------------------------------------------------------------
# 2D Delaunay (Bowyer-Watson, 纯 python, 不依赖 scipy)
# ------------------------------------------------------------------

def circumcircle_params(p1, p2, p3):
    ax, ay = p1
    bx, by = p2
    cx, cy = p3
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        return None
    a2 = ax * ax + ay * ay
    b2 = bx * bx + by * by
    c2 = cx * cx + cy * cy
    ux = (a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / d
    uy = (a2 * (cx - bx) + b2 * (ax - cx) + c2 * (bx - ax)) / d
    return ux, uy, (ax - ux) ** 2 + (ay - uy) ** 2


def bowyer_watson(pts2d):
    """2D 点集 -> 三角形索引列表 (Bowyer-Watson)"""
    n = len(pts2d)
    if n < 3:
        return []
    xs = [p[0] for p in pts2d]
    ys = [p[1] for p in pts2d]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    dx, dy = maxx - minx, maxy - miny
    midx, midy = (minx + maxx) / 2.0, (miny + maxy) / 2.0
    dmax = max(dx, dy) * 2.0
    s0 = (midx - 20.0 * dmax, midy - dmax)
    s1 = (midx, midy + 20.0 * dmax)
    s2 = (midx + 20.0 * dmax, midy - dmax)
    allpts = pts2d + [s0, s1, s2]
    super_idx = {n, n + 1, n + 2}
    tris = [[n, n + 1, n + 2]]
    for i in range(n):
        bad = []
        for t in tris:
            cc = circumcircle_params(allpts[t[0]], allpts[t[1]], allpts[t[2]])
            if cc is None:
                continue
            ux, uy, r2 = cc
            px, py = pts2d[i]
            if (px - ux) ** 2 + (py - uy) ** 2 <= r2 + 1e-9:
                bad.append(t)
        edge_count = defaultdict(int)
        for t in bad:
            for k in range(3):
                # 必须用无向边统计: (a,b) 与 (b,a) 是同一共享边,
                # 否则内部边会被误判为多边形空洞边界, 生成大量重叠三角形
                e = tuple(sorted((t[k], t[(k + 1) % 3])))
                edge_count[e] += 1
        boundary = [e for e, c in edge_count.items() if c == 1]
        tris = [t for t in tris if t not in bad]
        for e in boundary:
            tris.append([e[0], e[1], i])
    return [t for t in tris if not (t[0] in super_idx or t[1] in super_idx or t[2] in super_idx)]


def project_to_2d(pts3d):
    """PCA 投影到最佳拟合平面, 返回 (2d点列表, 逆映射矩阵不用)"""
    if len(pts3d) < 3:
        return None
    centroid = sum(pts3d, Vector((0, 0, 0))) / len(pts3d)
    A = np.array([(p - centroid) for p in pts3d], dtype=float)
    cov = A.T @ A
    w, v = np.linalg.eigh(cov)
    if w[0] < 1e-9 and w[1] < 1e-9:
        return None
    basis = v[:, -2:]
    P = A @ basis
    return [(float(x), float(y)) for x, y in P]


def order_convex_quad(pts3d, idx4):
    """若 4 点投影后为凸四边形, 返回按环绕序排好的索引; 否则返回 None"""
    c = sum((pts3d[i] for i in idx4), Vector((0, 0, 0))) / 4.0
    nrm = (pts3d[idx4[1]] - pts3d[idx4[0]]).cross(pts3d[idx4[2]] - pts3d[idx4[0]])
    if nrm.length < 1e-9:
        return None
    nrm.normalize()
    u = (pts3d[idx4[0]] - c)
    u = u if u.length > 1e-9 else Vector((1, 0, 0))
    u.normalize()
    v = nrm.cross(u)
    order = sorted(idx4, key=lambda i: math.atan2(
        (pts3d[i] - c).dot(v), (pts3d[i] - c).dot(u)))
    signs = []
    for k in range(4):
        a, b, cc = order[k], order[(k + 1) % 4], order[(k + 2) % 4]
        cr = (pts3d[b] - pts3d[a]).cross(pts3d[cc] - pts3d[b])
        if cr.length < 1e-9:
            return None
        signs.append(cr.dot(nrm))
    if all(s > 0 for s in signs) or all(s < 0 for s in signs):
        return order
    return None


def merge_tris_to_quads(pts3d, tris, angle_limit):
    """三角形 -> 合并相邻三角对为四边形, 返回 (quads, remaining_tris)"""
    edge_tris = defaultdict(list)
    for ti, t in enumerate(tris):
        for k in range(3):
            e = tuple(sorted((t[k], t[(k + 1) % 3])))
            edge_tris[e].append(ti)

    def tri_normal(t):
        return (pts3d[t[1]] - pts3d[t[0]]).cross(pts3d[t[2]] - pts3d[t[0]])

    candidates = []
    for e, tis in edge_tris.items():
        if len(tis) != 2:
            continue
        t0, t1 = tis
        vset = set(tris[t0]) | set(tris[t1])
        if len(vset) != 4:
            continue
        n0, n1 = tri_normal(tris[t0]), tri_normal(tris[t1])
        if n0.length < 1e-9 or n1.length < 1e-9:
            continue
        ang = math.degrees(n0.angle(n1))
        if ang > angle_limit:
            continue
        order = order_convex_quad(pts3d, list(vset))
        if order is None:
            continue
        candidates.append((ang, order, t0, t1))
    candidates.sort(key=lambda x: x[0])

    used = set()
    quads = []
    for _, order, t0, t1 in candidates:
        if t0 in used or t1 in used:
            continue
        used.add(t0)
        used.add(t1)
        quads.append(order)
    remaining = [i for i in range(len(tris)) if i not in used]
    return quads, remaining


# ------------------------------------------------------------------
# 属性
# ------------------------------------------------------------------

class IQ_CutObj(bpy.types.PropertyGroup):
    obj: bpy.props.PointerProperty(type=bpy.types.Object)
    name: bpy.props.StringProperty()


class IQ_Props(bpy.types.PropertyGroup):
    solid: bpy.props.PointerProperty(
        type=bpy.types.Object, name="主对象",
        description="交点要落在它表面上的实体(实体或面均可)")
    cut_objs: bpy.props.CollectionProperty(type=IQ_CutObj)
    cut_index: bpy.props.IntProperty()
    mode: bpy.props.EnumProperty(
        name="拓扑模式",
        items=[
            ("AUTO", "自动", "能聚成 2 组方向则索引网格, 否则 Delaunay"),
            ("GRID", "索引网格", "切割面聚成 2 组, 跨组交线交点按行列连纯四边面"),
            ("DELAUNAY", "Delaunay 散点", "全部交点三角化后合并成四边形(为主)"),
        ],
        default="AUTO",
    )
    merge_tol: bpy.props.FloatProperty(
        name="合并容差", default=0.001, min=0.0, precision=4,
        description="交点去重容差(场景尺寸较大时可调大)")
    quad_angle: bpy.props.FloatProperty(
        name="合并角度限", default=20.0, min=0.0, max=90.0,
        description="Delaunay 模式下两三角形法线夹角小于该值才合并为四边形")
    layers: bpy.props.EnumProperty(
        name="网格层数",
        items=[
            ("AUTO", "自动", "多数格有进出双交点则双层, 否则单层"),
            ("SINGLE", "单层", "每个交点位置只生成一面(贴合实体一侧)"),
            ("DOUBLE", "双层", "交点进出各生成一层, 包裹实体"),
        ],
        default="AUTO",
        description="仅影响索引网格/自动模式; Delaunay 散点模式天然包含全部交点",
    )
    use_all_faces: bpy.props.BoolProperty(
        name="切割面取全部平面", default=True,
        description="开启: 每个切割对象里的所有不同平面(含阵列/多面)都当切割面; "
                    "关闭: 仅用每个对象首个面(旧行为, 用于回退)")


# ------------------------------------------------------------------
# UI 列表
# ------------------------------------------------------------------

class IQ_UL_Cuts(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index):
        if item.obj:
            layout.label(text=item.obj.name, icon="OBJECT_DATA")
        else:
            layout.label(text="(空)", icon="QUESTION")


# ------------------------------------------------------------------
# 操作符
# ------------------------------------------------------------------

class IQ_OT_AddCuts(bpy.types.Operator):
    """把当前选中的对象(主对象除外)加入切割面列表"""
    bl_idname = "iq.add_cuts"
    bl_label = "添加选中为切割面"
    bl_description = "把当前选中的对象加入切割面列表(主对象除外)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.iq_props
        sel = [o for o in context.selected_objects if o is not props.solid]
        if not sel:
            self.report({"WARNING"}, "没有可添加的对象(已排除主对象)")
            return {"CANCELLED"}
        existing = {c.obj for c in props.cut_objs}
        added = 0
        for o in sel:
            if o in existing:
                continue
            c = props.cut_objs.add()
            c.obj = o
            c.name = o.name
            added += 1
        self.report({"INFO"}, "已添加 %d 个切割面" % added)
        return {"FINISHED"}


class IQ_OT_RemoveCut(bpy.types.Operator):
    bl_idname = "iq.remove_cut"
    bl_label = "移除切割面"
    bl_description = "从列表移除当前选中的切割面"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.iq_props
        idx = props.cut_index
        if 0 <= idx < len(props.cut_objs):
            props.cut_objs.remove(idx)
        return {"FINISHED"}


class IQ_OT_ClearCuts(bpy.types.Operator):
    bl_idname = "iq.clear_cuts"
    bl_label = "清空切割面"
    bl_description = "清空切割面列表"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        context.scene.iq_props.cut_objs.clear()
        return {"FINISHED"}


class IQ_OT_Build(bpy.types.Operator):
    """核心: 求交点并生成四边形网格"""
    bl_idname = "iq.build"
    bl_label = "生成四边面"
    bl_description = "计算切割面交线与主对象表面的交点并生成四边形网格"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        p = context.scene.iq_props
        return p.solid is not None and len(p.cut_objs) >= 2

    def execute(self, context):
        props = context.scene.iq_props
        solid = props.solid
        if solid is None or solid.type != "MESH":
            self.report({"ERROR"}, "主对象必须是网格对象(实体或面)")
            return {"CANCELLED"}
        cuts = [c.obj for c in props.cut_objs if c.obj and c.obj.type == "MESH"]
        if len(cuts) < 2:
            self.report({"ERROR"}, "需要至少 2 个网格切割面")
            return {"CANCELLED"}
        dg = context.evaluated_depsgraph_get()
        tol = props.merge_tol

        # ---- 1. 主对象 BVH ----
        bm_solid = obj_to_bmesh_world(solid, dg)
        bvh = BVHTree.FromBMesh(bm_solid)
        solid_diag = bm_bbox_diagonal(bm_solid)
        bm_solid.free()

        # ---- 2. 切割平面收集: 每个切割对象可贡献多个不同平面 ----
        # use_all_faces 关闭时回退旧行为(仅取每对象首个面)
        planes = build_planes(cuts, dg, tol, props.use_all_faces)
        if len(planes) < 2:
            self.report({"ERROR"}, "有效的切割平面不足 2 个(检查切割面是否为网格/平面)")
            return {"CANCELLED"}

        # ---- 3. 平面两两组合求交线, 交线与主对象表面求交点 ----
        ix = collect_intersections(planes, bvh, solid_diag)
        if not ix.points:
            self.report({"ERROR"}, "没有找到任何交点: 请检查主对象是否被切割面穿过")
            return {"CANCELLED"}

        # ---- 4. 交点去重 ----
        dedup, groups = dedup_points(ix.points, tol)
        n = len(dedup)
        # 合并后每个去重点的来源标签(用于索引网格)
        point_labels = defaultdict(set)
        for g, lab in zip(groups, ix.labels):
            point_labels[g].add(lab)

        # ---- 5. 选拓扑模式: GRID 优先, 聚类不足/格不足时自动落到 Delaunay ----
        quad_faces = []
        tri_faces = []
        used_mode = "Delaunay 散点"
        if props.mode in ("GRID", "AUTO"):
            g0, g1 = cluster_by_normal_planes(planes)
            if props.mode == "GRID" or (len(g0) >= 2 and len(g1) >= 2):
                ctx = BuildCtx(planes, dedup, point_labels, ix.dirs_by_pair)
                quad_faces, used_mode = build_grid_faces(ctx, g0, g1, props.layers)

        if not quad_faces:
            quad_faces, tri_faces, err = build_delaunay_faces(dedup, props.quad_angle)
            if err:
                self.report({"ERROR"}, err)
                return {"CANCELLED"}
            used_mode = "Delaunay 散点"

        # ---- 6. 建 mesh 输出 ----
        obj, err = build_result_mesh(context, dedup, quad_faces, tri_faces)
        if err:
            self.report({"ERROR"}, err)
            return {"CANCELLED"}
        self.report({"INFO"}, "%s: 交点 %d, 四边形 %d, 三角形 %d" %
                    (used_mode, n, len(quad_faces), len(tri_faces)))
        return {"FINISHED"}


# ------------------------------------------------------------------
# 面板
# ------------------------------------------------------------------

class IQ_PT_Panel(bpy.types.Panel):
    bl_label = "交点四边面生成器"
    bl_idname = "IQ_PT_Panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "交点四边面"

    def draw(self, context):
        p = context.scene.iq_props
        layout = self.layout

        layout.label(text="Blender %s" % bpy.app.version_string, icon="INFO")

        box = layout.box()
        box.label(text="主对象(实体/面)", icon="MESH_DATA")
        box.prop(p, "solid", text="", icon="EYEDROPPER")

        box = layout.box()
        box.label(text="切割面列表", icon="MESH_PLANE")
        row = box.row()
        row.operator("iq.add_cuts", text="添加选中", icon="ADD")
        row.operator("iq.clear_cuts", text="", icon="X")
        box.template_list("IQ_UL_Cuts", "", p, "cut_objs", p, "cut_index")
        row = box.row()
        row.operator("iq.remove_cut", text="移除", icon="REMOVE")
        row.label(text="共 %d 个" % len(p.cut_objs))

        layout.prop(p, "mode")
        layout.prop(p, "layers")
        layout.prop(p, "use_all_faces")
        layout.prop(p, "merge_tol")
        layout.prop(p, "quad_angle")
        layout.separator()
        layout.operator("iq.build", text="生成四边面", icon="MESH_GRID")


classes = (
    IQ_CutObj,
    IQ_Props,
    IQ_UL_Cuts,
    IQ_OT_AddCuts,
    IQ_OT_RemoveCut,
    IQ_OT_ClearCuts,
    IQ_OT_Build,
    IQ_PT_Panel,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.iq_props = bpy.props.PointerProperty(type=IQ_Props)


def unregister():
    del bpy.types.Scene.iq_props
    for c in reversed(classes):
        bpy.utils.unregister_class(c)


if __name__ == "__main__":
    register()
