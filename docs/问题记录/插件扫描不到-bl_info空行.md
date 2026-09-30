# 问题：插件装好了，偏好设置里却找不到

**TL;DR**：`bl_info` 后面紧跟了多行 docstring，快速扫描器把代码截成三引号未闭合，`ast.parse` 失败，
`addon_utils.modules()` 直接不收录它。

- **问题**：插件文件放进 `scripts/addons/` 后，偏好设置的插件列表里**完全看不到它**
- **根因**：Blender 的**快速扫描器**从 `bl_info` 那一行往下读，**读到第一个空行就停**，
  再把这截片段 `ast.parse` 一遍。若 `bl_info` 后面紧跟多行 docstring，截出来的是未闭合的三引号 → 语法错误
- **解决**：`bl_info` 后面**立刻空一行**；说明文字改成 `#` 注释挪到 `bl_info` **前面**

```python
# 说明文字写在这里（注释），不要写成 docstring
bl_info = {
    "name": "...",
    "version": (1, 3, 0),
}                      # ← 这之后必须立刻空行

import os
import bpy
```

- **预防**：验证时用 `[m.__name__ for m in addon_utils.modules()]` 确认**被扫到**，
  别只用 `addon_utils.enable()` 判断 —— **后者在扫描失败时依然会成功**，极具迷惑性。
  ```
  modules_count 18 → 19   # 修好前后对比
  ```
