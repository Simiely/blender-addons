# Blender 插件集（Blender Addons）

> 个人的 Blender 插件集合 —— 每个插件一个**单文件 `.py`**，下载即装，无第三方依赖。

![Blender](https://img.shields.io/badge/Blender-4.0%2B-blue)
![Python](https://img.shields.io/badge/Python-3.11%2B-green)
![License](https://img.shields.io/badge/License-GPL--3.0--or--later-orange)

## 插件一览

| 插件 | 说明 | 版本 | 安装文件 |
|---|---|---|---|
| **工作台快渲**<br>Workbench Quick Look | 设好相机后直接出工作台（Workbench）风格的预览图 / 动画。**全程不切换渲染引擎**，Cycles 的设置原封不动 | v1.3.0 | [`addons/workbench_quick_render.py`](./addons/workbench_quick_render.py) |

> 加插件 = 往 `addons/` 丢一个 `.py` + 上表加一行。命名与提交约定见 [AGENTS.md](./AGENTS.md)。

## 安装

### 方式一：从磁盘安装（推荐）

1. 下载 `addons/` 下对应插件的 `.py` 文件
2. Blender → 编辑 → 偏好设置 → **插件**
3. 右上角下拉 → **从磁盘安装** → **安装旧式插件（Install Legacy Add-on）**
4. 选中那个 `.py` → 勾选启用

### 方式二：放进脚本目录

把 `.py` 复制到 Blender 的 `scripts/addons/`（或你自定义脚本目录下的 `addons/` 子目录），重启 Blender，再到偏好设置里勾选启用。

> 所有插件都是**单文件 legacy addon**：纯 Python + Blender 内置 `bpy` / `mathutils`，**无第三方依赖** —— 不用解压、不用装轮子、不用配环境。

## 快速开始

### 工作台快渲（Workbench Quick Look）

**它解决的问题**：设好相机后想按**工作台引擎**的样子出图，但每次都要「切到工作台 → 渲染 → 切回 Cycles」，来回折腾。

1. 3D 视口按 `N` → 侧栏找到 **「快渲」** 标签
2. 三个按钮：
   - **看一眼（不存盘）** —— 立刻出一张图给你看，不改动任何设置
   - **渲染当前帧** / **渲染动画** —— 存到 `//output/快渲/`（相对当前 `.blend` 文件）
3. **实时预览到视口**（建议先开这个）：打开后改「工作台外观」里的任何参数，3D 视口**立刻跟着变**；关掉即还原到打开前的外观与视口
4. **腔体预设**：出厂 `脊 = 谷 = 0.3`。勾着「开预览时套用」，一开预览就自动套上；想让它**永久留在场景里**，点 **「套用这个预设」**

完整参数说明与实现原理见 [DEVELOPMENT.md](./DEVELOPMENT.md)。

## 目录结构

```
blender-addons/
├── README.md          # 本文件：插件索引 + 安装 + 快速开始
├── AGENTS.md          # AI / 协作规则与关键坑
├── DEVELOPMENT.md     # 仓库设计取舍 + 各插件架构与问题记录
├── CHANGELOG.md       # 版本变更记录（按插件分节）
└── addons/            # 插件本体：每个插件一个单文件 .py
    └── workbench_quick_render.py
```

## 文档规范

本仓库按 [knowledge-base](https://github.com/Simiely/knowledge-base) 的**单项目文档规范**维护：

- **四件套各管一类读者**：`README`（用户与访客）/ `AGENTS`（AI 与未来的自己）/ `DEVELOPMENT`（开发者）/ `CHANGELOG`（所有人）
- **生长式拆分**：`docs/`、`rules/` 目录**长出来的**，超过拆分阈值才建，不提前设计
- **文档基线**记在 [AGENTS.md](./AGENTS.md) 顶部（日期 + commit hash），支持断点续传
