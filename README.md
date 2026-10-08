# Blender 插件集（Blender Addons）

> 个人的 Blender 插件集合 —— **一个仓库管全部插件**。自研插件每个一个**单文件 `.py`**，下载即装、无第三方依赖。

![Blender](https://img.shields.io/badge/Blender-2.80%2B-blue)
![Python](https://img.shields.io/badge/Python-3.7%2B-green)
![License](https://img.shields.io/badge/License-GPL--3.0--or--later-orange)

## 插件一览

| # | 插件 | 说明 | 版本 | 兼容 | 安装文件 |
|---|---|---|---|---|---|
| 1 | **工作台快渲**<br>Workbench Quick Look | 设好相机后直接出工作台（Workbench）风格的预览图 / 动画。**全程不切换渲染引擎**，Cycles 的设置原封不动 | v1.6.0 | 4.0+ | [`workbench_quick_render.py`](./addons/workbench_quick_render.py) |
| 2 | **对象轴与居中工具**<br>Empty Align Center | 居中（自身+子集）/ 轴居中贴底 / 轴居中贴底并落地。均含子集、不限类型，**物体网格不动只改原点** | v1.5.4 | 2.93+ | [`empty_align_center.py`](./addons/empty_align_center.py) |
| 3 | **网格排序器**<br>Mesh Face Sorter | 按**面数从高到低**排列场景中所有网格体，便于逐个检查与处理 | v1.7.0 | 3.0+ | [`mesh_face_sorter.py`](./addons/mesh_face_sorter.py) |
| 4 | **SketchUp Importer** | 导入 `.skp` 模型到 Blender（官方插件的 5.x 兼容修改版，含 cp37~cp314 多版二进制） | v0.27.0 | 2.80+ | [`sketchup_importer.zip`](./addons/sketchup_importer.zip) ⚠️ **需解压** |
| 5 | **交点四边面生成器**<br>Intersect Quads Builder | 用选面作切割面，生成交点处的四边面（修补建模用） | v0.2.0 | 2.80+ | [`intersect_quads_builder.py`](./addons/intersect_quads_builder.py) ⚠️ **WIP** |
| 6 | **车模网格减面**<br>Car Mesh Optimizer | 车模高精度网格减面：分离松散块 → 逐个减面 → 合并焊接 | v3.4.0 | 3.6+ | [`blender_car_mesh_optimizer.py`](./addons/blender_car_mesh_optimizer.py) ⚠️ **WIP** |
| 7 | **Import MAX**<br>Import Autodesk MAX | 导入 `.max`（Autodesk 3ds Max）场景：网格 + 材质，第三方插件的 Blender 4.2+ 兼容版 | v1.9.2 | 4.2+ | [`io_scene_max/`](./addons/io_scene_max) ⚠️ **包目录·第三方** |

> **状态说明**：✅ 稳定可用　⚠️ **WIP 开发中，可能不稳定或数据损坏，请勿用于正式项目**
>
> 5、6 号仍在开发（原独立仓库 README 标注「请勿安装」）。迁入本仓库是为了**统一管理**，
> 不代表它们已可交付 —— 用之前请自行在测试文件上验证。

## 安装

### 方式一：从磁盘安装（推荐，仅限单文件 `.py`）

1. 下载 `addons/` 下对应插件的 `.py` 文件
2. Blender → 编辑 → 偏好设置 → **插件**
3. 右上角下拉 → **从磁盘安装** → **安装旧式插件（Install Legacy Add-on）**
4. 选中那个 `.py` → 勾选启用

> 方式一适用于 **1、2、3、5、6 号**（都是单文件 legacy addon）。

### 方式二：放进脚本目录（通用于全部插件）

把 `.py` 复制到 Blender 的 `scripts/addons/`，重启 Blender，再在偏好设置里勾选启用。

Windows 用户路径通常是：
```
C:\Users\<你的用户名>\AppData\Roaming\Blender Foundation\Blender\<版本号>\scripts\addons\
```

### ⚠️ SketchUp Importer（4 号）必须单独处理

它是**包目录形态**（一个文件夹里含 `.pyd` / `.dll`），不是单文件，走不了上面两种方式：

1. 下载 [`sketchup_importer.zip`](./addons/sketchup_importer.zip)
2. **解压**到 Blender 的 `scripts/addons/` 目录 —— 解压后应得到 `addons/sketchup_importer/` 文件夹
3. 重启 Blender → 偏好设置 → 插件 → 勾选 **SketchUp Importer**
4. 使用：文件 → 导入 → **SketchUp Importer (.skp)**

> 也可以直接在偏好设置里用「从磁盘安装」直接选那个 `.zip`，Blender 会自动完成解压。

### ⚠️ Import MAX（7 号）是包目录插件

它和 SketchUp Importer 一样是**包目录形态**（含 `blender_manifest.toml` + `import_max.py`），不是单文件：

1. 把 `addons/io_scene_max/` **整个文件夹**复制到 Blender 的 `scripts/addons/`（或扩展目录 `extensions/user_default/`）
2. 重启 Blender → 偏好设置 → 插件 → 搜索 `Autodesk MAX` → 勾选 **Import Autodesk MAX (.max)**
3. 使用：文件 → 导入 → **Autodesk MAX (.max)**

> 它是第三方插件（nrgsille 的 io_scene_max v1.9.2），非本仓库自研；含官方扩展 manifest，
> 也可把 `io_scene_max/` 打包成 zip 走「扩展 → 从磁盘安装」。

## 插件位置速查

装好后，插件面板都在 **3D 视口按 `N` → 右侧边栏**：

| 插件 | 侧栏标签 |
|---|---|
| 工作台快渲 | `快渲` |
| 对象轴与居中工具 | `Tool` |
| 网格排序器 | `网格排序器` |
| SketchUp Importer | 无面板，走 文件 → 导入 菜单 |
| 交点四边面生成器 | `交点四边面` |
| 车模网格减面 | `车模减面` |
| Import MAX | 无面板，走 文件 → 导入 → Autodesk MAX (.max) |

## 快速开始

### 1. 工作台快渲（Workbench Quick Look）

**它解决的问题**：设好相机后想按**工作台引擎**的样子出图，但每次都要「切到工作台 → 渲染 → 切回 Cycles」，来回折腾。

1. 3D 视口按 `N` → 侧栏找到 **「快渲」** 标签
2. 三个按钮：
   - **看一眼（不存盘）** —— 立刻出一张图给你看，不改动任何设置
   - **渲染当前帧** / **渲染动画** —— 存到 `//output/快渲/`（相对当前 `.blend` 文件）
3. **实时预览到视口**（建议先开这个）：打开后改「工作台外观」里的任何参数，3D 视口**立刻跟着变**；
   关掉会把场景外观还原，**但会记住你调好的样子** —— 下次打开预览自动还原，不用重调。
   面板上「工作台外观」里的**每一个**控件都在记忆范围内（含阴影、腔体、描边、**抗锯齿**）
4. **腔体预设**：出厂 `脊 = 谷 = 0.3`，只在**还没记住任何外观**时生效。
   想让它永久留在场景里，点 **「套用这个预设」**
5. 不想留记忆了？点记忆那行右侧的垃圾桶图标（**忘记记住的外观**），下次开预览重新用出厂预设

### 2. 对象轴与居中工具（Empty Align Center）

**它解决的问题**：模型导入后原点乱飞、子物体跟着漂；想「贴底」「落地」却得手动算偏移。

三种模式，都支持**含子集**、**不限对象类型**：

- **居中** —— 把选中对象的原点移到自身包围盒中心
- **轴居中贴底** —— 原点移到包围盒底面中心（X/Y 居中，Z 贴底）
- **轴居中贴底并落地** —— 贴底后直接落到当前地面高度（Z = 0）

> 关键设计：**只改原点，物体网格数据完全不动**。所以是「整理」而不是「变形」——
> 网格没动，贴图UV、修改器、动画都不会因此错位。

### 3. 网格排序器（Mesh Face Sorter）

**它解决的问题**：场景里几十个网格体，想找出「哪个面数最高、最该先减」时只能一个个数。

一键把场景中所有网格体**按面数从高到低重排**，从上往下数就是优先级。
适合配合减面类插件（仓库里的 6 号车模减面）分批处理。

### 4. SketchUp Importer

导入 `.skp` 文件。官方插件在 Blender 5.x 上的兼容问题已在此版修复（含 cp313/cp314 二进制）。

若导入报错，注意菜单路径是 **文件 → 导入 → SketchUp Importer**，不是 Blender 原生的 `.fbx` 导入器。

### 5. 交点四边面生成器（WIP）

选中若干面作为**切割面** → 生成在这些面交点处的四边面，用于修补不干净的布尔/相交拓扑。

流程：**添加选中为切割面** → **生成四边面** →（可选）**移除切割面** / **清空切割面**。

### 6. 车模网格减面（WIP）

针对高精度车模的减面流程：**选取特征点** → **按密度选点** → **确认选取** → **生成优化网格**。
另提供**快速预设**一键跑通流程。

> ⚠️ 这两个 WIP 插件会**直接改动网格数据**。请务必先在新文件里测试，确认无误再用于正式项目。

## 目录结构

```
blender-addons/
├── README.md          # 本文件：插件索引 + 安装 + 快速开始
├── AGENTS.md          # AI / 协作规则与关键坑
├── DEVELOPMENT.md     # 仓库设计取舍 + 各插件架构与问题记录
├── CHANGELOG.md       # 版本变更记录（按插件分节）
├── .gitignore
├── addons/            # 插件本体
│   ├── workbench_quick_render.py        # 单文件
│   ├── empty_align_center.py            # 单文件
│   ├── mesh_face_sorter.py              # 单文件
│   ├── intersect_quads_builder.py       # 单文件（WIP）
│   ├── blender_car_mesh_optimizer.py    # 单文件（WIP）
│   ├── sketchup_importer.zip            # 包目录，需解压（第三方修改版）
│   └── io_scene_max/                   # 包目录（第三方 Import MAX，含 blender_manifest.toml）
└── docs/              # 生长出来的详细文档（超过阈值才拆，不提前设计）
    ├── 架构.md
    ├── 技术债与重构计划.md
    └── 问题记录/
```

## 文档规范

本仓库按 [knowledge-base](https://github.com/Simiely/knowledge-base) 的**单项目文档规范**维护：

- **四件套各管一类读者**：`README`（用户与访客）/ `AGENTS`（AI 与未来的自己）/ `DEVELOPMENT`（开发者）/ `CHANGELOG`（所有人）
- **生长式拆分**：`docs/`、`rules/` 目录**长出来的**，超过拆分阈值才建，不提前设计
- **文档基线**记在 [AGENTS.md](./AGENTS.md) 顶部（日期 + commit hash），支持断点续传

## 相关仓库

本仓库为插件的**唯一维护处**。原独立仓库的处理结果如下（内容均已并入本仓库，**本仓库即唯一来源**）：

| 原仓库 | 处理结果 | 对应内容 |
|---|---|---|
| `blender-empty-align-center` | 🗄️ 已归档（只读） | `addons/empty_align_center.py` |
| `blender-mesh-face-sorter` | 🗄️ 已归档·公开（只读） | `addons/mesh_face_sorter.py` |
| `blender-skp-importer` | 🗄️ 已归档（只读） | `addons/sketchup_importer.zip`；其内含的 **Import MAX（io_scene_max）** 也已并入 `addons/io_scene_max/` |
| `blender-car-mesh-optimizer` | 🗄️ 已删除 | 内容已并入 `addons/blender_car_mesh_optimizer.py` |
| `blender-intersect-quads-builder` | 🗄️ 已删除 | 内容已并入 `addons/intersect_quads_builder.py` |
