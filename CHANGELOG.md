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

## workbench_quick_render v1.6.0（2026-09-30）

**按审计计划做一轮受控重构**（用户要求「架构清晰吗，不要想当然，需要搜索调研得出结论」
→ 先给判断与计划 → 批准后「按照计划 修复问题」）。

### 背景

v1.5.0 之后用 **AST 调用图 + radon + difflib + 无头探测**做了一次客观审计（不是「我觉得乱」）：
分层单向、反向依赖 0、循环 0、死代码 0 —— **结构本身没问题**。
但量出 3 处「改动成本热点」，见 [`docs/技术债与重构计划.md`](./docs/技术债与重构计划.md)。

当时的结论是**不改**：4 个渲染 Operator 里有 3 个在无头下**结构性不可测**
（`render.opengl` 在 `-b` 下必失败），重构等于在没有护栏的地方动刀。
本版先补护栏，再动刀。

### 消除的 3 项技术债

**债 1 · 渲染流程骨架重复 → `_render_with_restore()`**

- 原来 4 个渲染 Operator 各写一遍「快照 → 渲染 → `try/finally` 还原」，
  公共骨架 14 条语句 ×4，两两相似度最高 **0.74**（业内重复率标准 <5%）
- 新增 `_render_with_restore(scene, body, restore_engine=False)`：统一编排，
  `body` 里**只放那一行真正无法无头测试的渲染调用**
- 关键切法：**没有**把整个流程抽成一个 `_run_render()` —— 那样会把不可测的那行一起包进去、
  等于**扩大**不可测面积。现在的做法把不可测面积从「4 份骨架」压到「4 行调用」

**债 2 · `_PREVIEW` 重置手写 3 遍 → `_reset_preview_state()`**

- 原来 4 个字段在 3 处各写一遍（闲置 / 卸载 / 换文件），加字段漏改一处**不会报错**
  —— v1.5.0 新增 `"display"` 字段时正好踩过这里
- 现在统一走 `_reset_preview_state()`（连「打开失败」算上共 4 条路径），
  函数文档里写明「往 `_PREVIEW` 加字段必须同步改本函数」

**债 3 · `draw()` 116 行 / 圈复杂度 15 → 拆成 5 个盒子函数**

- 依据 Blender 官方 Best Practice：*"If you need more code for the layout declaration
  than for the actual properties, then you are doing it wrong."*
  官方 `io_scene_fbx` / `io_scene_gltf2` 同样把 `draw()` 拆成多个辅助函数
- 拆为 `_draw_status_box` / `_draw_render_box` / `_draw_preview_box` /
  `_draw_shading_box` / `_draw_footer` + 一个 `_prop()` 守卫；
  `draw()` 只剩分发 + 末尾的预览同步钩子
- 意外收获：拆出的函数**只调 `layout` 的方法** ⇒ 可以用假 layout（记录调用了哪些控件）
  在无头下测 —— 面板布局从「不可测」变成「可断言」

### 验证

- **新增 `test_ops.py`（69 项）**，第一次把渲染 Operator 纳入护栏：
  - 3 个 `render.opengl` Operator 在无头下**必然失败**，恰好用来断言失败路径的
    `finally` 还原（分辨率百分比 / 帧范围 / 输出路径全部写回）
  - `wqr.render_engine` 在无头下**能真跑通**：渲染 1 帧到临时目录、断言产出了文件、
    断言引擎切回原值
  - `_reset_preview_state` / `_render_with_restore`（含异常路径与 `restore_engine`）单元覆盖
  - 5 个盒子函数 + `_prop` 的控件存在性断言
- 回归全绿：`test_preview.py` 90 + `test_final.py` 21 + `test_api.py` 13 + `test_ops.py` 69
  = **193 项，全部 `FAILS 0 []`**（v1.5.0 时是 124 项）

### 指标（radon 实测，改造前 → 后）

| 指标 | 改造前 | 改造后 |
|---|---|---|
| 圈复杂度 > 10 的函数 | 2 个（`WQR_PT_panel` 16、`draw` 15） | **0 个**（`radon cc -n C` 无输出） |
| `WQR_PT_panel.draw` | 116 行 / CC 15 | 约 18 行 / **CC 3** |
| `WQR_OT_still.execute` 类 | CC 6 | **CC 4** |
| 4 个渲染 `execute` 合计行数 | 114 | 94 |
| 渲染骨架两两相似度 | 0.50 ~ 0.74 | 0.17 ~ 0.73（多数 ≤0.48） |
| `_snapshot(scene)` 调用点 | 5 | 2 |
| `scene.wqr.restore_settings` 读取点 | 4 | 1 |
| `_PREVIEW` 触点 | 27 | 11 |
| 可维护性指数 MI | 13.26 (B) | **15.56 (B)** |

> 层间矩阵复核：`L4 UI → L2` 由 23 次降为 15 次（编排收敛）；反向依赖仍 0、死代码仍 0。

### 说明

- 这一版**只动结构、不动行为**：所有用户可见的行为（按钮文案、还原语义、记忆优先级）
  与 v1.5.0 **完全一致**，测试断言也是照 v1.5.0 的行为写的
- 审计与重构的判据（「该不该重构」三条：触发条件是否出现 / 改完能否被自动化接住 /
  收益是「防未来」还是「解当下痛点」）已提炼进技能 `python-arch-audit`

---

## workbench_quick_render v1.5.0（2026-09-30）

**外观记忆补全：抗锯齿也存得住**（用户追问：「阴影那些列出来可以选择的参数，都是可以记忆的对吗」，
并明确要求「工作台外观的参数，都是可以存到的；打开实时预览就能调用上次记录的」）。

### 问题

v1.4.0 的记忆只覆盖 `scene.display.shading` 上的 16 个属性，而**「抗锯齿」`render_aa`
根本不长在 shading 上** —— 它是 `scene.display` 本体的属性（`View3DShading` 里查无此物）。
结果：面板上「抗锯齿」看着和别的控件一样，**却既不进记忆、也不参与还原**。

### 新增

- 常量 `_DISPLAY_ATTRS = ("render_aa",)`：`scene.display` 本体的外观清单
- 函数 `_snapshot_display(display)`：冻结 display 层外观
- 记忆体改成**两层结构**：`{"shading": {...}, "display": {"render_aa": "..."}}`
  （`_dump_profile(scene)` 生成，`_load_profile()` 解析）
- 实时预览的 `_PREVIEW` 状态新增 `"display"` 字段，与 `"shading"` 一起快照、一起还原

### 兼容

- `_load_profile()`**认旧格式**：v1.4.0 及更早存下的整份 dict 会被自动包成
  `{"shading": <旧数据>, "display": {}}` ⇒ 老 `.blend` 打开后记忆照样生效，不会因为升级而失效

### 验证

- `test_preview.py` **90 项全过**（比 v1.4.0 多 6 项），新增断言：
  开关一次后 `render_aa` 正确还原、重开预览时 `render_aa` 从记忆还原成 `'16'`、
  记忆体确为两层键（`["display", "shading"]`）、旧格式能被规范化并正常套用
- 回归 `test_final.py` 21 项、`test_api.py` 13 项，均 `FAILS 0 []`

### 说明

- 抗锯齿**不影响视口显示**（视口的 AA 由 Blender 偏好设置控制），它只决定
  `render.opengl` 出图的边缘平滑度 ⇒ 记忆它的意义是「下次出图沿用上次的取舍」，而非实时可见
- 教训：**往面板加外观控件前，先确认这个属性挂在哪个 Struct 上**，再决定进 `_SHADING_ATTRS` 还是 `_DISPLAY_ATTRS`

---

## workbench_quick_render v1.4.0（2026-09-30）

**预览外观记忆**（用户反馈：「关闭预览之后，再次预览，之前的设置又会清零，
希望是可以自动保存关闭预览之前的设置」）。

### 问题

原来关预览会把场景外观还原到打开之前，而下次开预览又走 0.3 出厂预设 ——
**用户在预览期间辛苦调好的样子两次都被冲掉**。

### 新增

- 属性 `remember_preview`（**默认开**）：关预览时自动把当时的「工作台外观」存下来
- 属性 `preview_profile` / `preview_profile_time`：记忆本体（JSON 字符串）与时间戳，
  挂在 `Scene` 上 ⇒ **随 `.blend` 保存**，关掉 Blender 再打开也还在
- 操作符 `wqr.forget_preview_profile`：忘记记住的外观
- 面板在预览框内新增一行状态：「已记住 09-30 12:30」+ 垃圾桶按钮；未记住时显示「还没记住外观（用出厂预设）」

### 行为（优先级）

打开预览时按这个顺序取外观：

1. **有记忆** → 套用记忆里的外观（用户上次调好的样子）
2. 无记忆 且勾了「无记忆时套用预设」→ 套用腔体预设 0.3
3. 都没有 → 用当前场景外观（等于不额外改动）

关预览时：**先保存记忆，再还原场景外观**。所以「关掉还原」这条老规矩没变，
但下次打开能拿回自己的样子。

### 修复

- **闲置时不得写记忆**：`_stop_preview` 只在 `state["active"]` 为真时才保存 ——
  否则「预览没开时误触 / 卸载插件」会把还原后的值当成记忆存进去，污染下一次预览
- **记忆损坏要优雅回退**：`preview_profile` 不是合法 JSON 时返回 `None`，走预设分支，不抛异常

### 验证

- `test_preview.py` **84 项全过**，新增 20 项覆盖：默认值、图标 `TRASH`、
  首次开预览走预设、调好外观→关（场景还原 + 记忆已存）→再开（**外观 == 调好的样子**，
  且不是预设 0.3、也不是还原后的原值）、忘记记忆后回到预设、关掉「记住外观」不保存、
  闲置调用不污染、损坏 JSON 优雅回退
- 回归 `test_final.py` 21 项、`test_api.py` 13 项，均 `FAILS 0 []`

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
