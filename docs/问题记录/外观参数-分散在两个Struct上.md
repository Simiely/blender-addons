# 问题：面板上的「抗锯齿」，别的参数能记住，它记住不了

**TL;DR**：面板外观参数里，「抗锯齿」不在 `scene.display.shading` 上，而在 `scene.display` 本体上 ——
记忆与还原收集的都是 shading 的属性，它自然被漏掉。

- **问题**：用户问「阴影那些列出来可以选择的参数，都是可以记忆的对吗」。
  逐个核对后发现：阴影、腔体、描边、颜色、光照等 16 项都能记住，**唯独最后的「抗锯齿」不行** ——
  调完关预览再开，它回到原值，面板上却看不出任何区别（行为长得跟别的控件一样）
- **根因**：属性**挂错了层**。外观控件看着都在同一块面板里，实际分属两个不同的 Struct：

  | 控件 | 属性 | 所属 Struct | 进哪个清单 |
  |---|---|---|---|
  | 光照 / 颜色 / 阴影 / 腔体 / 描边 … | `light`、`color_type`、`show_shadows` … | `scene.display.shading`（`View3DShading`） | `_SHADING_ATTRS` |
  | **抗锯齿** | **`render_aa`** | **`scene.display`（`SceneDisplay`）** | `_DISPLAY_ATTRS` |

  验证（`-b` 下可直接跑）：

  ```python
  hasattr(scene.display, "render_aa")          # True
  hasattr(scene.display.shading, "render_aa")  # False
  "render_aa" in View3DShading.bl_rna.properties  # False
  scene.display.render_aa                       # '8'（ENUM：OFF/FXAA/5/8/11/16/32）
  ```

  ⇒ v1.4.0 的记忆体是一份扁平 dict（就是 shading 快照），
  `_assign_attrs(shading, profile)` 里根本没有 `render_aa`，**它连"写失败"都不会报，因为压根没被收集**

- **解决**：把「外观」拆成两层分别收集，记忆体也跟着变成两层

  ```python
  _DISPLAY_ATTRS = ("render_aa",)   # 挂在 scene.display 本体上的外观

  def _snapshot_display(display):
      data = {}
      for name in _DISPLAY_ATTRS:
          if not hasattr(display, name):
              continue
          try:
              data[name] = getattr(display, name)
          except Exception:
              continue
      return data

  def _dump_profile(scene):
      return json.dumps({
          "shading": _snapshot_shading(scene.display.shading),
          "display": _snapshot_display(scene.display),
      }, ensure_ascii=False, sort_keys=True)
  ```

  打开预览时两层一起写；关预览时两层一起还原（`_PREVIEW["display"]` 与 `"shading"` 并列）。

- **预防**：
  1. **往面板加外观控件前，先确认属性挂在哪个 Struct 上** —— 用
     `hasattr(scene.display, name)` / `hasattr(scene.display.shading, name)` 各测一次，
     别靠"看起来在同一个面板里"推断
  2. **收集清单要显式**（`_SHADING_ATTRS` / `_DISPLAY_ATTRS`），不要用「遍历 shading 所有属性」的写法 ——
     那样会把不属于外观的字段也存进去，跨版本更容易坏事
  3. **改了记忆结构就要写兼容**：`_load_profile()` 认旧格式（整份 dict 即 shading 快照），
     自动包成 `{"shading": <旧数据>, "display": {}}` —— 否则老 `.blend` 一升级记忆就全废

## 配套要点

- **`render_aa` 不影响视口显示**：视口的抗锯齿由 Blender 偏好设置决定，
  这个属性只作用于 `render.opengl` 出图 ⇒ 记忆它的意义是「下次出图沿用上次的取舍」，
  调它时视口**不会**实时变化，这是正常的，不是同步坏了
- **它也不进视口同步**：`_push_shading` 只推 `_SHADING_ATTRS`，
  `space.shading` 上没有 `render_aa`（同属 `SceneDisplay`，视口与出图共用同一个值）
- **测试要覆盖"还原"和"重开"两侧**：只测一侧的话，
  「存进去了但没写回」或「能写回但没存」这两种半成品都会漏网
