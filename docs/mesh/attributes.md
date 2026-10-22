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

## 4. 材质节点消费者矩阵

材质节点树中只有以下 `ShaderNodeAttribute` 真正读取 MTK 属性（`utils/materials/builder/atlas_builder.py`）：

| 属性 | 节点 | 条件 | 用途 |
| :--- | :--- | :--- | :--- |
| `mtk_uv_transform` | `MTK UV Transform` | 始终 | UV 缩放/偏移 |
| `mtk_uv_rotation` | `MTK UV Rotation` | 始终 | 旋转 UV |
| `mtk_anim_timing` | `Face Anim Timing` | `is_animated` | 动画帧时序 |
| `mtk_anim_frame_size` | `Face Anim Frame Size` | `is_animated` | 动画帧尺寸 |
| `mtk_biome_tint_data` | `Attr Biome Tint Data` | 有 Biome Tint 组 | 基色/叠加/染色权重 |
| `mtk_biome_tint_color` | `Attr Biome Tint Color` | 有 Biome Tint 组 | 已解算 Linear RGBA |

结论：

- **实际消费**：仅 6 个 `material` 角色属性；`metadata` 属性不进入着色器。
- **近乎退役/可条件化**：`mtk_uv_rotation` 只对旋转 UV 生效；`mtk_anim_timing/frame_size` 只在动画材质上生效；`mtk_biome_tint_data` 的 Alpha 通道（`tint_type`）节点不读取，仅 Python 重着色使用，保留为元数据。
- **世界坐标**：`mtk_block_x/y/z` 只服务 `WORLD` 预设的 3D Biome 重采样，外部导入网格不需要。

## 5. 按网格来源的最小属性集

| 来源 | 必需属性 | 说明 |
| :--- | :--- | :--- |
| 外部导入（`EXTERNAL`） | 6 个材质属性 + `mtk_source_texture_key/idx` + `mtk_atlas_chunk_id` | `Replace Material` 依赖 provenance 与 chunk 路由；无 `mtk_block_*` |
| 存档 / Live Sync / 体素重建（内部） | 6 个材质属性 + `mtk_source_texture_idx`（+ `mtk_source_textures`）+ `mtk_block_x/y/z` | 材质与几何由点云/体素源重建，`mtk_source_texture_key` 字符串只是 ≤1024 面的兼容副本 |
| 点云对象 | 无 MTK 面属性 | 点云承载体素/生物群系信息，网格由重建流程生成 |

内部网格的材质重替换应优先走 `Rebuild Voxel Mesh`；`Replace Material` 的 provenance 只用于外部导入网格与同布局重绑。

## 6. 已知写入边界

- `mtk_source_texture_key` 的 STRING 层只对 ≤1024 面同步；大网格以 `mtk_source_textures` + `mtk_source_texture_idx` 为唯一权威。判断 provenance 时必须同时检查 INT 属性（现有 `op_materials` / `pipeline` 已这样做）。
- `Replace Material` 的 restore 路径现在走 palette + index 写入，不再为所有面重建 Python 字符串。
- `inject_mesh_provenance_attributes` 已移除 `poly_mat_indices` / `face_texture_ids` / `mode` 等死参数；写入尺寸不匹配会记录 warning 而不是静默失败。
- 恢复材质时若 `mtk_atlas_chunk_id` 缺失，当前会以 0 填充；这是待收敛的边界，最终应从材质槽 provenance 推导而不是默认 0。
- 动画重路由（`reconcile_animation`）只重投影 Atlas UV，不重写 `mtk_uv_transform` / `mtk_uv_rotation`；若布局或动画精灵比例变化，需要补写这两个属性。
- Blender → `MeshData` 的 `extract_mesh_data` 会把 palette + index 展开为逐面字符串（Rust 侧再压缩）；这是当前往返路径的内存热点，可后续补 palette 直传 API。

## 7. 按上下文裁剪策略

| 条件 | 保留 | 移除 |
| :--- | :--- | :--- |
| 网格无多帧动画（`mtk_anim_timing[0] <= 1`） | 其余属性 | `mtk_anim_timing`、`mtk_anim_frame_size`（Rust collector 直接不写；Python 侧 `prune_optional_mesh_attributes` 兜底） |
| 独立烘焙模型网格 | 材质/染色/来源属性 | `mtk_block_x/y/z`（`populate_standard_face_attributes(..., include_block_coords=false)`） |
| 外部导入网格（EXTERNAL，Replace Material 后） | 材质属性 + provenance + chunk 路由 | 动画残留（无动画时）与 `mtk_block_*` 残留 |
| 内部体素/存档/Live Sync 网格 | 材质属性 + palette provenance + `mtk_block_*` | 无动画时移除动画属性；世界坐标保留以支持 `WORLD` 预设切换 |

裁剪只针对“可选属性”，`mtk_source_texture_idx` + `mtk_source_textures`、`mtk_atlas_chunk_id` 与 6 个材质属性不会被裁剪。
