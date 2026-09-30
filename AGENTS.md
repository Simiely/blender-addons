# AGENTS.md · 项目规则

> 📌 **文档基线**：2026-09-30（commit `cf67688`）完成四件套重写
> **更新文档/代码后，请更新此行**（日期 + 新 commit hash），并在 CHANGELOG 追加版本

## 技术栈

- Blender **4.0 ~ 5.x**（验证环境：Blender 5.2.2 LTS，内置 Python 3.13）
- 纯 Python + Blender 内置 `bpy` / `mathutils`；**无任何第三方依赖**
- **单文件 legacy addon**（完整 `bl_info`，不用 `blender_manifest.toml`）
- 交付路径：`addons/<插件名>.py`，**文件名 = 模块名**（`workbench_quick_render.py` → `workbench_quick_render`）

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

## 约定

- 注释用中文；UI 标签 / 按钮 / 面板名 / `bl_info` 用中文
- 版本号写在 `bl_info["version"]`，三段元组（如 `(1, 3, 0)`）
- 插件的 `bl_idname` 统一用小写模块前缀（`wqr.preview`、`wqr.render_still`）
- 涉及临时改场景状态的操作（引擎、输出路径、格式、分辨率、帧范围）一律 `try/finally` 还原
- **新增 Operator 后记得同步加进 `_CLASSES`**，否则 `register()` 不会注册它（面板上直接报错）
- 面板里取属性用一层 `hasattr` 包住，跨版本差异不至于把面板画崩
- 新增插件：加 `.py` → README「插件一览」加行 → CHANGELOG 加节 → DEVELOPMENT 加章节
- **公开仓库红线**：不收录凭据（token / 密码）、个人信息、**本地绝对路径**、未公开的项目细节

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
