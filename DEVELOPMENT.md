# DEVELOPMENT.md · 仓库说明与索引

> 本文件是**门面 + 索引**：只放仓库级信息与入口，细节走链接。
> 拆分记录：2026-09-30 超过 200 行阈值 → 拆出 [`docs/架构.md`](./docs/架构.md) 与
> [`docs/问题记录/`](./docs/问题记录/)。

## 项目概览

个人 Blender 插件集：**一个仓库管全部插件**。每个插件是**单文件 legacy addon**，
放在 `addons/`，文件名即模块名。

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

## 仓库结构

```
blender-addons/
├── README.md                  # 门面：插件索引 + 安装 + 快速开始
├── AGENTS.md                  # AI / 协作规则与关键坑（顶部有文档基线行）
├── DEVELOPMENT.md             # 本文件：仓库说明与索引
├── CHANGELOG.md               # 版本变更记录（按插件分节）
├── .gitignore
├── addons/                    # 插件本体：每个插件一个单文件 .py
│   └── workbench_quick_render.py
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

| 插件 | 文件 | 版本 | 架构与实现 |
|---|---|---|---|
| **工作台快渲**<br>Workbench Quick Look | [`addons/workbench_quick_render.py`](./addons/workbench_quick_render.py) | v1.6.0 | [`docs/架构.md`](./docs/架构.md) |

### 工作台快渲 · 一句话

设好相机后一键出工作台（Workbench）风格的预览图 / 动画，**全程不切换渲染引擎**。
三个按钮（看一眼 / 渲染当前帧 / 渲染动画）+ 一个「实时预览」开关 + **预览外观记忆**（含抗锯齿）+ 腔体预设 0.3。
v1.6.0 做过一轮**受控重构**（渲染编排收敛 + 面板拆分），行为与 v1.5.0 完全一致，
审计与判据见 [`docs/技术债与重构计划.md`](./docs/技术债与重构计划.md)。

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
