# AGENTS.md · 项目规则

> 📌 **文档基线**：2026-10-02（commit `49d2a6c`）插件集扩容：5 个插件迁入，含 zip 形态例外
> **更新文档/代码后，请更新此行**（日期 + 新 commit hash），并在 CHANGELOG 追加版本

## 技术栈

- Blender **2.80 ~ 5.x**（验证环境：Blender 5.2.2 LTS，内置 Python 3.13）
  - 各插件的**最低版本看自己的 `bl_info["blender"]`**：快渲 4.0+、居中 2.93+、
    排序器 3.0+、交点四边面 2.80+、车模减面 3.6+
- 自研插件：纯 Python + Blender 内置 `bpy` / `mathutils`；**无任何第三方依赖**
- **单文件 legacy addon**（完整 `bl_info`，不用 `blender_manifest.toml`）
- 交付路径：`addons/<插件名>.py`，**文件名 = 模块名**（`workbench_quick_render.py` → `workbench_quick_render`）
- **唯一例外**：`addons/sketchup_importer.zip` 是包目录形态的**第三方插件修改版**
  （含 cp37~cp314 多版 `.pyd` + `SketchUpAPI.dll`），不适用上面两条。
  它需要 `.gitignore` 里的 `!addons/sketchup_importer.zip` 放行才能进仓

## 关键坑（务必先读，都是代码里看不出来的）

- ★ **`bl_info` 后面必须紧跟一个空行**。Blender 的快速扫描器从 `bl_info` 往下读，**读到第一个空行就停**，再 `ast.parse` 一遍。若紧跟多行 docstring，会被截成三引号未闭合 → 语法错误 → **插件根本不出现在偏好设置列表里**（但 `addon_utils.enable()` 依然成功，极具迷惑性）。说明文字一律用 `#` 注释写在 `bl_info` **前面**。
- ★ **脚本文件绝不能带 BOM**。会炸 `SyntaxError: invalid non-printable character U+FEFF`。
- **快照还原时不要对字符串枚举做 `tuple()`**：`'STUDIO'` 会被拆成字符元组，还原时 `setattr` 抛 `TypeError`；若这个异常被 `except: pass` 吞掉，现象是「枚举属性没还原、数值属性还原了」，极难定位。
- **还原类操作不要静默吞失败**：把写失败的属性名收集起来 `self.report({'WARNING'}, ...)` 报出去。
- **测试 RNA `FLOAT`（C 32 位 float）时，断言值要用二进制可精确表示的数**：`0.25 / 0.5 / 0.75 / 1.5 / 1.75 / 2.0`。写 `0.3` / `0.4` 必失败（实际是 `0.4000000059604645`）；或两边都 `round(x, 4)`。
- **测试里不要硬编码版本号**（如 `assert version == (1, 2, 0)`）——升版本就报假失败。改成读源码里声明的版本再比对。
- **无头 `-b` 下仍然有 window / screen**：`space.shading`、`region_3d.view_perspective` 这类「看着要 GUI」的东西**可以在无头下真测**。只有 **OpenGL 渲染**不行（`Cannot use OpenGL render in background mode`），但 `poll()` 仍可调用，可用来判断按钮会不会灰。
- **`scene.display.shading`（渲染属性 → 工作台）与 `space.shading`（视口着色）是两块独立数据**，改前者不影响后者 —— 这正是「实时预览」要同步的东西。
- **`bpy.ops.render.opengl(view_context=False)` 与 `scene.render.engine` 无关**：它按**场景设置**渲染（活动相机 + `scene.display.shading`），Cycles 下 `poll()` 依然为 `True`。
- ★ **「记住临时改过的值」类功能：保存必须在还原之前，且优先级必须高于出厂预设。**
  以预览外观记忆为例 —— 顺序反了会存到还原后的空值；优先级反了则用户调好的值每次开预览都会被预设冲掉，等于白调。
- ★ **工作台外观参数分属两个 Struct，收集清单必须分两份**：绝大多数在 `scene.display.shading`（`View3DShading`），
  但「抗锯齿」`render_aa` 在 `scene.display`（`SceneDisplay`）**本体**上 —— 只收 shading 就会漏掉它，
  而且**完全不报错**（它根本没进收集清单，连「写失败」都不会出现）。加外观控件前先两边各 `hasattr` 测一次：
  `hasattr(scene.display, name)` / `hasattr(scene.display.shading, name)`。
- ★ **渲染类 Operator 一律走 `_render_with_restore(scene, body)`**，别在 `execute` 里自己写
  `_snapshot` / `try...finally`。新渲染方式只要把「**那一行渲染调用**」放进 `body` 闭包即可；
  需要无条件还原引擎（如引擎式渲染）就传 `restore_engine=True`。
  这样做是为了把**唯一无法无头测试的那行调用**单独隔离出来 —— 抽成一个大函数反而会**扩大**不可测面积。
- ★ **`_PREVIEW` 的 4 个字段只从 `_reset_preview_state()` 一处清空**，别在 `unregister` / 换文件 /
  打开失败各写一遍。往 `_PREVIEW` 加字段时**必须同步改这个函数**（漏改不报错，表现为残留旧快照）。
- ★ **改代码前先量**：判断「要不要重构」不要凭感觉，跑 `analyze_arch.py`（AST 调用图）+ `radon cc/mi`
  + 重复度，并按三条判据决策（触发条件是否出现 / 改完能否被自动化接住 / 收益是「防未来」还是「解当下痛点」）。
  完整方法见技能 `python-arch-audit`，本仓库的例子见 [`docs/技术债与重构计划.md`](./docs/技术债与重构计划.md)。

## 约定

- 注释用中文；UI 标签 / 按钮 / 面板名 / `bl_info` 用中文
- 版本号写在 `bl_info["version"]`，三段元组（如 `(1, 3, 0)`）
- 插件的 `bl_idname` 统一用小写模块前缀（`wqr.preview`、`wqr.render_still`）
- 涉及临时改场景状态的操作（引擎、输出路径、格式、分辨率、帧范围）一律 `try/finally` 还原
- **新增 Operator 后记得同步加进 `_CLASSES`**，否则 `register()` 不会注册它（面板上直接报错）
- 面板里取属性用一层 `hasattr` 包住，跨版本差异不至于把面板画崩
- 新增插件：加 `.py` → README「插件一览」加行 → CHANGELOG 加节 → DEVELOPMENT 加章节
- **公开仓库红线**：不收录凭据（token / 密码）、个人信息、**本地绝对路径**、未公开的项目细节

## 迁入插件的检查清单

从别的仓库往 `addons/` 搬文件时，**逐条过一遍**（每条都对应一个真实踩过的坑）：

| 检查 | 怎么查 | 不合格的后果 |
|---|---|---|
| **无 BOM** | 文件头不是 `EF BB BF` | `SyntaxError: invalid non-printable character U+FEFF`，插件直接不加载 |
| **`bl_info` 后紧跟空行** | 找 `bl_info` 字典的**结束行** `}`，下一行须为空 | 快速扫描器读到空行才停，紧跟多行 docstring 会被截成三引号未闭合 → 插件**根本不出现在偏好设置列表**，但 `enable()` 照样成功（极具迷惑性） |
| 语法能过 | `ast.parse(src)` | 注册时炸 |
| `_CLASSES` 无遗漏 | 每个 Operator 类名都在 `_CLASSES` 里 | `register()` 不注册它，面板直接报错 |
| **UI 标签是中文** | `bl_label` / `bl_category` / `bl_info["location"]` | 违反本仓库约定（`bl_category` 才是侧栏显示名，`bl_label` 只是窗口标题） |
| **无本地绝对路径 / 凭据** | 搜 `C:\` `D:\` `/Users/` `ghp_` | 公开仓库红线 |
| 无头能加载 | 见下方命令 | 装完才发现根本 import 不了 |

```bash
# 语法检查（全部插件）
for f in addons/*.py; do python -m py_compile "$f" && echo "OK $f"; done
```

**注意 `bl_info` 空行那条**：检查时要定位 `bl_info = {` 之后**第一个以 `}` 开头的行**
（字典结束），看它的**下一行**是否为空。直接看 `bl_info = {` 的下一行是错的 ——
那是字典内容的第一行（`"name": ...`），会得到假阳性。

### 无头验证：启用状态必须冷启动复查

`blender -b --python x.py` 里调 `addon_utils.enable(..., persistent=True)`，
**进程退出后启用状态会丢失**。必须在脚本里显式 `bpy.ops.wm.save_userpref()` 才真正写入
`config/userpref.blend`。验证也要**开新进程冷启动**再 `addon_utils.check()` ——
同进程内查是假阳性。


## 常用命令

```bash
# 语法检查
python -m py_compile addons/workbench_quick_render.py

# 无头启用验证（确认插件能被扫到并注册成功）
blender -b --python-expr "import addon_utils; addon_utils.enable('workbench_quick_render', default_set=False); print('OK')"

# 跑无头回归测试
blender -b --python <测试脚本>
```

> 测试脚本要**自己把结果落盘**（`open(report.txt, 'w', encoding='utf-8')` 逐行 flush），
> 不要指望 shell 重定向抓输出。

## 详细规则（按需 @引用）

> 本文件超过 150 词后，把「关键坑」按主题拆到 `rules/` 下，此处只留核心约束 + @引用列表。
> 目前尚未触发拆分阈值。
