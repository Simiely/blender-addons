# CHANGELOG.md

仓库级变更记录，**按插件分节**。版本号跟各插件 `bl_info["version"]` 一致。

---

## 仓库 · 2026-09-30

**建库**：把原先「一个插件一个仓库」的做法收敛为**一个仓库管全部插件**。

- 目录：`addons/` 下每个插件一个单文件 `.py`
- 文档：按 knowledge-base 的**单项目规范**配齐四件套（README / AGENTS / DEVELOPMENT / CHANGELOG）
- 首个迁入插件：`workbench_quick_render`（v1.3.0），由包目录形式拍平为单文件
- 原独立仓库 `blender-workbench-quick-render` 的规划取消（从未创建）

---

## workbench_quick_render v1.3.0（2026-09-30）

**把腔体预设值 0.3 写进插件默认值**（用户要求「需要你帮我写出默认0.3」）。

### 新增

- 属性 `apply_cavity_preset`（默认开）、`cavity_preset_ridge`（**默认 0.3**）、`cavity_preset_valley`（**默认 0.3**）
- 函数 `_apply_cavity_preset(scene)`：一次写**世界与屏幕两组**系数（`cavity_*` + `curvature_*`），
  并顺带打开 `show_cavity`
- 操作符 `wqr.apply_cavity_preset`（面板按钮「套用这个预设」）

### 行为

- 打开「实时预览」时，若勾着「开预览时套用」，会**自动**把腔体设成预设值
- **顺序很关键**：先快照、后套用 ⇒ 关掉预览能把外观（含腔体）还原到打开前的原值
- 「套用这个预设」按钮**不走快照**，点它写入的值会永久留在场景里

### 验证

- 无头回归三套全过（`FAILS 0 []`）：预览开关 + 腔体预设 72 项、面板与输出往返 22 项、快照还原 13 项
- 测试里不硬编码版本号（改为读源码声明的版本），避免升版本后报假失败

### 说明

- 实测纠正一个常见误解：Blender 5.2 里腔体相关默认值**都是 1.0**（不是 0.3），
  `show_cavity` 默认**关**，`cavity_type` 默认 `SCREEN`；用户看到的 0.3 是某个工程文件里存的值

---

## workbench_quick_render v1.2.0（2026-09-30）

**补齐 cavity（腔体）参数**（用户问「cavity 也可以设置吗，默认都是0.3」）。

### 新增

- 把 4 个系数加进 `_SHADING_ATTRS`：`cavity_ridge_factor` / `cavity_valley_factor`（世界）、
  `curvature_ridge_factor` / `curvature_valley_factor`（屏幕）
  ⇒ 自动参与实时预览同步与还原
- 面板按 `cavity_type` 条件显示：「世界 脊 / 谷」只在该显示时出现，「屏幕 脊 / 谷」同理
- 顺带把「阴影强度」也做成显示阴影时才出现的滑条

---

## workbench_quick_render v1.1.0（2026-09-30）

**加「实时预览」开关**（用户要求：打开后改参数能立刻反映到界面，取消则还原到打开前的设置）。

### 新增

- 属性 `preview_on` / `preview_camera`；操作符 `wqr.toggle_preview`
- 打开 = 把 `scene.display.shading` 同步到所有 3D 视口的 `space.shading`（并切 SOLID + 可选相机视角）
- 打开期间每次面板 `draw()` 末尾推送一次（**只写有差异的值**，避免重绘死循环）
- 关闭 = 视口快照 + 外观快照一起还原；`unregister()` 若开关还开着也会自动还原
- 另挂 `load_post` 处理器作废快照（换文件后快照会失真）

### 修复

- **取消预览后枚举属性不还原**：快照时对字符串枚举做了 `tuple()`，还原时 `setattr` 抛 `TypeError`
  又被 `except: pass` 吞掉。改为只对非 `str/bool/int/float` 做 `tuple()`，
  并新增 `_assign_attrs()` 把写失败的属性名报出去

---

## workbench_quick_render v1.0.0（2026-09-30）

**首个版本**：设好相机后一键出工作台（Workbench）风格的预览图 / 动画，**不用切引擎再切回来**。

### 新增

- 面板 `WQR_PT_panel`（3D 视口 → 侧栏 `N` → **「快渲」** 标签）
- 操作符：
  - `wqr.preview` 看一眼（不存盘）
  - `wqr.render_still` 渲染当前帧（PNG）
  - `wqr.render_anim` 渲染动画（MP4 / PNG 序列）
  - `wqr.render_engine` 引擎式渲染（切 Workbench，`try/finally` 保证切回）
  - `wqr.open_folder` 打开输出目录
- 输出设置自动还原：路径、格式、分辨率、帧范围渲染后回退，不污染 Cycles 的正式输出设置
- 输出目录默认 `//output/快渲/`

### 依据

- `bpy.ops.render.opengl(view_context=False)` 用**场景设置**渲染，与 `scene.render.engine` 无关
- 内置菜单那三个「视口渲染」入口在 `bl_ui/space_view3d.py` 里没有任何引擎判断
