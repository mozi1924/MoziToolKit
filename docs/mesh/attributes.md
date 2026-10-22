# 网格属性契约 (Mesh Attribute Contract)

本文件描述 MoziToolKit 与 `libmtk` 之间的面属性契约。权威定义不在 Python 侧，而在 Rust 核心：

- `mtk_core::attributes::MESH_ATTRIBUTE_SPECS`：所有允许写入的活跃属性（名称、域、类型、`material` / `metadata` 角色）。
- `mtk_core::attributes::RETIRED_MESH_ATTRIBUTES`：已退役、只允许清理、禁止再次写入的属性。

## 1. 单一事实源与生成流程

```text
mtk-core::attributes (Rust SSOT)
        │  mesh_attribute_schema() / retired_mesh_attributes()
        ▼
tools/sync_attribute_schema.py
        ▼
bridge/mesh/_attribute_schema_generated.py  (checked-in mirror)
        ▼
bridge/mesh/attribute_schema.py             (typed helpers)
        ▼
bridge/mesh/attributes.py / utils/materials/*
```

- 新增或删除属性时，只修改 `mtk-core/src/attributes.rs`，然后执行：
  ```bash
  cd ../libmozitoolkit && cargo build-py
  cd ../MoziToolKit && python tools/sync_attribute_schema.py
  ```
- `tests/test_attribute_schema.py` 会在原生扩展可用时逐项比对镜像与 `libmtk_py` 导出的 schema；CI 因此能拦住忘记重新生成的情况。
- Python 侧禁止再手写 `EXCLUDED_MESH_ATTRIBUTES` / `CANONICAL_MESH_FACE_ATTRIBUTES` 一类的名单。

## 2. 活跃属性

| 属性 | 域 | 类型 | 角色 | 消费者 |
| :--- | :--- | :--- | :--- | :--- |
| `mtk_source_texture_key` | FACE | STRING | metadata | 调色板来源、Biome 重算、材质替换 |
| `mtk_source_texture_idx` | FACE | INT | metadata | 宿主生成的来源调色板索引 |
| `mtk_atlas_chunk_id` | FACE | INT | metadata | 图集 Chunk 材质路由 |
| `mtk_uv_transform` | FACE | FLOAT4 | material | UV 缩放/偏移着色器 |
| `mtk_uv_rotation` | FACE | FLOAT | material | UV 旋转着色器 |
| `mtk_anim_timing` | FACE | FLOAT3 | material | 动画时序着色器 |
| `mtk_anim_frame_size` | FACE | FLOAT3 | material | 动画帧尺寸着色器 |
| `mtk_biome_tint_color` | FACE | FLOAT4 | material | 已解算的 Linear RGBA 染色 |
| `mtk_biome_tint_data` | FACE | FLOAT4 | material | 染色权重与类型 |
| `mtk_block_x/y/z` | FACE | INT | metadata | 3D Biome 采样 |

## 3. 已退役属性

以下属性不再由 Rust 生成，宿主只负责从旧 `.blend` 中清理：

- 图集/材质元数据：`mtk_material_slot`、`mtk_material_id`、`mtk_atlas_texture_id`、`mtk_uv_mode`、`mtk_source_origin`、`mtk_is_opaque`、`mtk_alpha_mode`
- 发光与朝向：`mtk_emission`（发光已由预解码 ORM Alpha 承载）、`mtk_face_dir`（与面法线重复）
- Biome 旧字段：`mtk_colormap_uv`、`mtk_tint_weight`、`mtk_base_tint_weight`、`mtk_overlay_tint_weight`、`mtk_tint_color`、`mtk_tint_type`、`mtk_hardcoded_color`、`mtk_use_hardcoded`、`mtk_biome_temperature`、`mtk_biome_humidity`、`mtk_biome_coords`
- 标量动画拆分：`mtk_anim_total_frames`、`mtk_anim_frametime`、`mtk_anim_interpolate`、`mtk_anim_frame_width`、`mtk_anim_frame_height`
- 旧 UV Tiling：`mtk_uv_tiling_scale`、`mtk_uv_tiling_location`、`mtk_uv_tiling_transform`
- 旧属性表/点云字符串/无前缀遗留名：`mtk_material_props`、`mtk_block_state`、`mtk_biome`、`atlas_chunk_id`、`atlas_texture_id`、`material_id`

清理入口：`utils/materials/cleaner.py::clean_obsolete_mesh_attributes`，其名单直接来自生成镜像。
