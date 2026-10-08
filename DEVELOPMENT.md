# DEVELOPMENT.md · 仓库说明与索引

> 本文件是**门面 + 索引**：只放仓库级信息与入口，细节走链接。
> 拆分记录：2026-09-30 超过 200 行阈值 → 拆出 [`docs/架构.md`](./docs/架构.md) 与
> [`docs/问题记录/`](./docs/问题记录/)。

## 项目概览

个人 Blender 插件集：**一个仓库管全部插件**。每个自研插件是**单文件 legacy addon**，
放在 `addons/`，文件名即模块名。

> **例外**：`sketchup_importer` 与 `io_scene_max` 是**包目录形态**（第三方插件），
> 前者以 `sketchup_importer.zip` 进仓（需解压），后者以 `io_scene_max/` 文件夹进仓。见下文「两类插件形态」。

### 为什么是单文件（设计取舍）

- **用户体验优先**：安装只需在偏好设置里点「从磁盘安装 → 安装旧式插件」选一个 `.py`，
  不用解压、不用挑文件夹、不用管包里有没有 `__init__.py`
- **单文件够用**：无第三方依赖 ⇒ 不需要 `wheels/`；插件之间目前无共享代码 ⇒ 不需要 `common/`
- **代价（重要）**：legacy 单文件**不能**上 Blender 官方 Extensions 平台，也**不能**做成可订阅的
  私人扩展源 —— 这两条路都要求包里至少有 `blender_manifest.toml` + `__init__.py`。
  见文末「升级路径」

### 与业内做法的对照

| 做法 | 代表 | 采用 | 原因 |
|---|---|---|---|
| 每个插件一个独立仓库 | Blender 官方外围插件 | ✗ | 插件变多后 issue / 版本 / 文档分散，跨插件复用困难 |
| 一个仓库多个**包目录** | 官方 `blender-addons`、`BlenderAddonPackageTool`（`addons/<name>/__init__.py` + `common/`） | ✗ | 本仓库插件无共享代码，包目录徒增安装步骤 |
| **一个仓库多个单文件 `.py`** | —— | ✓ | 兼顾「统一管理」与「单文件即装」；真出现共享代码再按生长式原则升级 |
| 自建可订阅扩展源 | 社区私有扩展源（`index.json` + 静态托管） | 暂缓 | 需先把插件转成 manifest 形式，见「升级路径」 |

### 两类插件形态（务必分清）

仓库里现在有两种形态，**安装方式不同**，写文档 / 回答用户时不能混为一谈：

| | 自研插件（5 个） | SketchUp Importer | Import MAX |
|---|---|---|---|
| 形态 | 单文件 `.py` | 包目录，多版本 `.pyd` + `.dll` | 包目录：`blender_manifest.toml` + `import_max.py` |
| 交付 | 直接下载 `.py` | `sketchup_importer.zip`，**需解压** | `io_scene_max/`（文件夹，可打包 zip） |
| 安装 | 「从磁盘安装 → 安装旧式插件」选 `.py`，或丢进 `scripts/addons/` | 解压到 `scripts/addons/`，或直接对 zip 走「从磁盘安装」 | 复制文件夹到 `scripts/addons/`（或扩展目录），重启后启用 |
| 依赖 | 纯 `bpy` / `mathutils` | SketchUpAPI.dll（随包分发） | 无额外依赖 |
| 归属 | 本仓库自研 | **第三方 5.x 兼容修改版**，非自研 | **第三方插件（nrgsille io_scene_max v1.9.2）**，非自研 |

**为什么 zip 要放行 `.gitignore`**：原 `.gitignore` 有 `*.zip`，本意是排除 Blender 打包产物
（`build/` 下的东西）。但 SketchUp 插件必须以 zip 进仓，故加否定规则
`!addons/sketchup_importer.zip` 并注明理由。**新增 zip 类交付物时要留意这条。**

## 仓库结构

```
blender-addons/
├── README.md                  # 门面：插件索引 + 安装 + 快速开始
├── AGENTS.md                  # AI / 协作规则与关键坑（顶部有文档基线行）
├── DEVELOPMENT.md             # 本文件：仓库说明与索引
├── CHANGELOG.md               # 版本变更记录（按插件分节）
├── .gitignore                 # 含 !addons/sketchup_importer.zip 例外
├── addons/                    # 插件本体
│   ├── workbench_quick_render.py        # 单文件 · 稳定
│   ├── empty_align_center.py            # 单文件 · 稳定
│   ├── mesh_face_sorter.py              # 单文件 · 稳定
│   ├── intersect_quads_builder.py       # 单文件 · WIP
│   ├── blender_car_mesh_optimizer.py    # 单文件 · WIP
│   ├── sketchup_importer.zip            # 包目录 · 需解压 · 第三方修改版
│   └── io_scene_max/                   # 包目录 · 第三方（Import MAX，含 blender_manifest.toml）
└── docs/
    ├── 架构.md                # 工作台快渲的架构说明（数据流 / 分层 / 还原语义）
    ├── 技术债与重构计划.md     # 审计结论与受控重构记录（v1.6.0 已按此执行）
    └── 问题记录/              # 一坑一篇
        ├── 插件扫描不到-bl_info空行.md
        ├── 预览还原-枚举属性丢失.md
        ├── 预览预设-快照顺序.md
        ├── 预览记忆-保存顺序与优先级.md
        ├── 外观参数-分散在两个Struct上.md
        ├── 腔体-两组系数预设.md
        ├── 无头测试-浮点断言.md
        └── 无头-视口可测性.md
```

`docs/` 与 `rules/` 是**长出来的**，不要提前设计：
`DEVELOPMENT.md` > 200 行 → `docs/`；`AGENTS.md` > 150 词 → `rules/`。

## 插件清单

| 插件 | 文件 | 版本 | 形态 | 状态 | 架构与实现 |
|---|---|---|---|---|---|
| **工作台快渲**<br>Workbench Quick Look | [`workbench_quick_render.py`](./addons/workbench_quick_render.py) | v1.6.0 | 单文件 | ✅ | [`docs/架构.md`](./docs/架构.md) |
| **对象轴与居中工具**<br>Empty Align Center | [`empty_align_center.py`](./addons/empty_align_center.py) | v1.5.4 | 单文件 | ✅ | 见下 |
| **网格排序器**<br>Mesh Face Sorter | [`mesh_face_sorter.py`](./addons/mesh_face_sorter.py) | v1.7.0 | 单文件 | ✅ | 见下 |
| **SketchUp Importer** | [`sketchup_importer.zip`](./addons/sketchup_importer.zip) | v0.27.0 | 包目录 | ✅ | 第三方修改版 |
| **交点四边面生成器**<br>Intersect Quads Builder | [`intersect_quads_builder.py`](./addons/intersect_quads_builder.py) | v0.2.0 | 单文件 | ⚠️ WIP | 见下 |
| **车模网格减面**<br>Car Mesh Optimizer | [`blender_car_mesh_optimizer.py`](./addons/blender_car_mesh_optimizer.py) | v3.4.0 | 单文件 | ⚠️ WIP | 见下 |
| **Import MAX**<br>Import Autodesk MAX | [`io_scene_max/`](./addons/io_scene_max) | v1.9.2 | 包目录 | ✅ | 第三方修改版（见下） |

> ✅ 稳定可用　⚠️ WIP 开发中，会直接改动网格数据，**须先在测试文件验证**。
> 详细安装方式见 [README](./README.md#安装)。

### 各插件 · 一句话

- **工作台快渲**：设好相机后一键出工作台（Workbench）风格的预览图 / 动画，
  **全程不切换渲染引擎**。三个按钮（看一眼 / 渲染当前帧 / 渲染动画）+ 一个「实时预览」开关 +
  **预览外观记忆**（含抗锯齿）+ 腔体预设 0.3。v1.6.0 做过一轮**受控重构**
  （渲染编排收敛 + 面板拆分），行为与 v1.5.0 完全一致，
  审计与判据见 [`docs/技术债与重构计划.md`](./docs/技术债与重构计划.md)。

- **对象轴与居中工具**：居中（自身+子集）/ 轴居中贴底 / 轴居中贴底并落地，均含子集、不限类型。
  关键设计是**只改原点、网格数据完全不动** —— 属于「整理」而非「变形」，
  所以不会破坏 UV / 修改器 / 动画。

- **网格排序器**：按面数从高到低重排场景中所有网格体，让「先减哪个」一目了然。
  适合配合车模减面一类插件分批处理。

- **SketchUp Importer**：导入 `.skp`。官方插件在 Blender 5.x 上的兼容问题已修复，
  包内含 cp37~cp314 多版 `.pyd`。**非自研**，是第三方插件的兼容修改版。

- **交点四边面生成器**（WIP）：选若干面作切割面 → 生成交点处四边面，修补不干净的布尔/相交拓扑。
  2026-10-02 迁入时把 `bl_label` / `bl_category` / `location` 从英文 `Intersect Quads`
  改为中文「交点四边面」，**功能代码未动**。

- **车模网格减面**（WIP）：选取特征点 → 按密度选点 → 确认选取 → 生成优化网格，
  另提供快速预设。管线是「分离松散块 → 逐个减面 → 合并焊接」。

- **Import MAX**（第三方）：导入 `.max`（Autodesk 3ds Max）场景，含网格与材质；
  菜单路径 文件 → 导入 → Autodesk MAX (.max)。非自研，是 nrgsille 的 io_scene_max v1.9.2 兼容版。


## 问题索引

> 一坑一篇，格式与 [knowledge-base](https://github.com/Simiely/knowledge-base) 经验条目一致
> —— 提炼到经验库时零转换搬运。

| 问题 | 一句话 |
|---|---|
| [插件装好了，偏好设置里却找不到](./docs/问题记录/插件扫描不到-bl_info空行.md) | `bl_info` 后面必须紧跟空行，否则插件不被扫描收录 |
| [取消预览后枚举属性没还原](./docs/问题记录/预览还原-枚举属性丢失.md) | 快照对字符串枚举做了 `tuple()`，异常又被静默吞掉 |
| [打开预览套预设，覆盖了用户的原始值](./docs/问题记录/预览预设-快照顺序.md) | 必须先快照、后套用；另给一个「永久写入」按钮 |
| [关预览再开，调好的外观被重置](./docs/问题记录/预览记忆-保存顺序与优先级.md) | 记忆要在还原前存，且优先级必须高于出厂预设 |
| [「抗锯齿」记住了别的参数，它记不住](./docs/问题记录/外观参数-分散在两个Struct上.md) | 面板上的外观控件分属 `scene.display.shading` 与 `scene.display` 两个 Struct，要分别收集 |
| [换 cavity 类型，预设值跳回旧数字](./docs/问题记录/腔体-两组系数预设.md) | 腔体有世界 / 屏幕两组系数，预设要一次全写 |
| [无头测试断言浮点属性永远失败](./docs/问题记录/无头测试-浮点断言.md) | RNA `FLOAT` 是 32 位，断言值要用可精确表示的十进制数 |
| [无头下能不能测视口功能](./docs/问题记录/无头-视口可测性.md) | 能。`-b` 下仍有 window / screen，只有 OpenGL 渲染不行 |

## 每次改动的动作清单

| 场景 | 动作 |
|---|---|
| 改了功能 | `docs/架构.md` 追加 / 更新对应说明 |
| 踩坑并解决 | `docs/问题记录/` 加一篇（一坑一篇）→ 收尾时提炼到经验库 |
| 发版 | 插件内 `bl_info["version"]` 升版本 + `CHANGELOG.md` 加节 + README 一览表更新 |
| **动结构 / 重构** | 先读 `docs/技术债与重构计划.md` 第五节「动手前的固定动作」：跑基线 → 改 → 重跑（须 `FAILS 0`）→ `radon` 复核指标 |
| 约定 / 坑变化 | `AGENTS.md` 更新，或新增 `rules/` 文件 |
| 任何提交后 | 更新 `AGENTS.md` 顶部的**文档基线行**（日期 + 新 commit hash） |

## 升级路径：想上 Extensions 平台 / 想要「订阅式自动更新」

当前是 **legacy 单文件**形态，下面两条路线都需要先把插件改成
`addons/<插件名>/` 目录形式：

```
addons/workbench_quick_render/
├── __init__.py
└── blender_manifest.toml
```

`blender_manifest.toml` 必填字段（官方 schema `1.0.0`）：
`schema_version` / `id` / `version` / `name` / `tagline` / `maintainer` / `type` /
`blender_version_min` / `license`。

### 路线 A：打包成 zip 上官方 Extensions 平台

```bash
blender --command extension build --source-dir addons/workbench_quick_render --output-dir build
blender --command extension validate addons/workbench_quick_render
```

产出 `{id}-{version}.zip`，用户在「从磁盘安装」里选 zip 即可。

### 路线 B：自建可订阅扩展源（一个 URL 订阅全部插件）

1. 每个插件 build 成 zip，随 Release 发布（或用 CI 自动 build）
2. 把所有 zip 放进一个静态托管目录，生成索引：
   ```bash
   blender --command extension server-generate --repo-dir repo --html
   ```
   产出 `index.json`（Blender 靠它识别仓库）
3. 用户：偏好设置 → 扩展 → 添加远程仓库 → 填 `index.json` 的地址
   → 之后所有插件**自动收到更新**

代价：多一套 CI 与 Release 流程。**当前不做**，等插件数量与更新频率上来再说。
