---
id: docs.generated.index
title: 生成索引
summary: 从 frontmatter 自动生成的导航；勿手改。
type: reference
kind: index
status: active
owner: "@platform"
source_type: doc
source: schema/taxonomy.json
last_reviewed: 2026-11-11
related: []
---

# 生成索引

> 生成文件，勿手改。运行 `python tools/repo-kit/generate.py --root . --write` 重建。

## 按 type

### explanation

| 页面 | kind | status | owner | tier | source |
|---|---|---|---|---|---|
| [架构说明 · 工作台快渲](../架构.md) | note | active | @simiely | normal | `addons/workbench_quick_render.py` |
| [插件装好了，偏好设置里却找不到](../问题记录/插件扫描不到-bl_info空行.md) | note | active | @simiely | normal | `addons/workbench_quick_render.py` |
| [换了 cavity 类型，预设值就跳回旧数字](../问题记录/腔体-两组系数预设.md) | note | active | @simiely | normal | `addons/workbench_quick_render.py` |
| [无头测试断言浮点属性永远失败](../问题记录/无头测试-浮点断言.md) | note | active | @simiely | normal | `addons/workbench_quick_render.py` |
| [无头 -b 模式下能不能测视口相关的功能](../问题记录/无头-视口可测性.md) | note | active | @simiely | normal | `addons/workbench_quick_render.py` |
| [取消实时预览后，枚举属性没还原、数值属性却还原了](../问题记录/预览还原-枚举属性丢失.md) | note | active | @simiely | normal | `addons/workbench_quick_render.py` |
| [关掉预览再打开，调好的外观又被重置了](../问题记录/预览记忆-保存顺序与优先级.md) | note | active | @simiely | normal | `addons/workbench_quick_render.py` |
| [打开预览时套用预设，把用户的原始值永久覆盖了](../问题记录/预览预设-快照顺序.md) | note | active | @simiely | normal | `addons/workbench_quick_render.py` |
| [面板上的「抗锯齿」，别的参数能记住，它记住不了](../问题记录/外观参数-分散在两个Struct上.md) | note | active | @simiely | normal | `addons/workbench_quick_render.py` |

## Reports

| 页面 | status | owner | tier | source |
|---|---|---|---|---|
| [技术债与重构计划 · workbench_quick_render](../技术债与重构计划.md) | active | @simiely | normal | `addons/workbench_quick_render.py` |

## 全部页面

| id | 标题 | type | kind | status |
|---|---|---|---|---|
| `docs.architecture` | [架构说明 · 工作台快渲](../架构.md) | explanation | note | active |
| `docs.issues.bl-info-blank-line` | [插件装好了，偏好设置里却找不到](../问题记录/插件扫描不到-bl_info空行.md) | explanation | note | active |
| `docs.issues.cavity-preset-groups` | [换了 cavity 类型，预设值就跳回旧数字](../问题记录/腔体-两组系数预设.md) | explanation | note | active |
| `docs.issues.headless-float-assert` | [无头测试断言浮点属性永远失败](../问题记录/无头测试-浮点断言.md) | explanation | note | active |
| `docs.issues.headless-viewport` | [无头 -b 模式下能不能测视口相关的功能](../问题记录/无头-视口可测性.md) | explanation | note | active |
| `docs.issues.preview-enum-restore` | [取消实时预览后，枚举属性没还原、数值属性却还原了](../问题记录/预览还原-枚举属性丢失.md) | explanation | note | active |
| `docs.issues.preview-restore-order` | [关掉预览再打开，调好的外观又被重置了](../问题记录/预览记忆-保存顺序与优先级.md) | explanation | note | active |
| `docs.issues.preview-snapshot-order` | [打开预览时套用预设，把用户的原始值永久覆盖了](../问题记录/预览预设-快照顺序.md) | explanation | note | active |
| `docs.issues.shading-antialiasing` | [面板上的「抗锯齿」，别的参数能记住，它记住不了](../问题记录/外观参数-分散在两个Struct上.md) | explanation | note | active |
| `docs.tech-debt` | [技术债与重构计划 · workbench_quick_render](../技术债与重构计划.md) | explanation | report | active |
