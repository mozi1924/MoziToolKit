# 2026-10-20 2.0 删除与暴露面收敛计划

> 状态：**B1–B6 已执行，B7 独立宿主内存适配层实施中；B0 分支/快照与 Blender 冒烟待做**
> 基线：`MoziToolKit@210a9e2`、`libmozitoolkit@3e08dc4`
> 范围：`MoziToolKit`（Blender 前端）与 `libmozitoolkit`（Rust 核心）两个仓库
> 前提：2.0 与 1.0 的网格激活/数据模型不兼容；2.0 没有第三方用户；不再为不存在的旧 wheel、旧 `.blend`、旧菜单配置保留兼容层。

---

## 1. 总原则

1. **删除优先，不写迁移**：没有真实消费者的 API、格式、菜单项直接删，不新增 shim。
2. **只保留真正的运行时兜底**：贴图缺失、模型缺失、资源包缺层、DNA 写入失败等运行期安全网保留；旧版本/旧格式/旧配置兼容一律删除。
3. **每个批次可独立回滚**：按“UI → Python 胶水 → Rust 零调用方 → 旧格式 → 数据模型 → 架构归位 → DNA 独立库”分批，不把跨仓库改动混在一个提交里。
4. **先量后改**：每批开始前记录基线测试与符号快照，结束后做 `rg` 零残留检查。

---

## 2. 基线与环境准备

### 2.1 当前基线

- 原生模块：`MoziToolKit/dev/lib/libmtk_py.so` 指向 `libmozitoolkit/target/release/liblibmtk_py.dylib`。
- 测试入口：
  - Rust：`cargo fmt --all -- --check`、`cargo clippy --workspace --all-targets -- -D warnings`、`cargo test --workspace --no-fail-fast`（基线 **323 passed, 0 failed**）
  - Python：`cd MoziToolKit && ../libmozitoolkit/.venv/bin/python -m pytest tests/ -q`（当前收集 344 项；基线 **271 passed, 73 skipped, 6 subtests passed**）
- 原生 API 快照命令（执行前先跑一次）：

```bash
cd MoziToolKit
../libmozitoolkit/.venv/bin/python - <<'PY'
import sys
sys.path.insert(0, 'dev/lib')
import libmtk_py as m
print(m.version())
for n in sorted(dir(m)):
    if not n.startswith('_'):
        print(n)
PY
```

### 2.2 分支与提交

- 每个批次一个分支：`refactor/2.0-delete-b1` … `refactor/2.0-delete-b7`。
- 每个批次至少两个提交：一个 Rust、一个 Python（如该批只涉及单仓库则一个）。
- 提交信息统一：`refactor(2.0): delete <batch> <subject>`。
- 不修改 `blender_manifest.toml` 版本号，除非该批涉及 wheel 重打包。

### 2.3 执行前检查

- [ ] `dev/lib` 原生库为最新构建，包含 `VoxelWorld`、`VoxelPointCloud`、`compute_flat_material_props_paletted_memoryview`、`process_flat_mesh_extrude_repair`、`inspect_minecraft_save`。
- [ ] 记录 `get_all_operators()` 当前 ID 列表，作为 UI 批次的对照。
- [ ] 备份本地 `context_menus.json`（仅用于回滚，不入库）。
- [ ] 确认两个仓库工作区干净；没有未提交的第三方改动。

---

## 3. 删除总表

> 行号是基线参考；执行时以符号名搜索为准。

### 3.1 Python Bridge（胶水层）

| ID | 位置 / 符号 | 删除内容 | 依赖 | 批次 |
|---|---|---|---|---|
| P-01 | `bridge/extrude.py` `repair_mesh_extruded_side_faces_batch` | `hasattr(process_flat_mesh_extrude_repair)` 的 `else` 嵌套列表回退（约 L201–L230） | 无 | B2 |
| P-02 | `bridge/material.py` `compute_biome_tint_attributes` | `mtk is None or not hasattr(...)` 的假数据分支（L134–L144） | 无 | B2 |
| P-03 | `bridge/material.py` `compute_mesh_biome_attributes_from_storage` | 缺 API 时转调 `compute_biome_tint_attributes` 的委托分支（L230–L231） | 无 | B2 |
| P-04 | `bridge/material.py` `compute_mesh_material_props` / `compute_flat_material_props` | 缺 API 返回全零的分支（L367–L370、L384–L386） | 无 | B2 |
| P-05 | `bridge/material.py` `compute_flat_material_props_buffer` / `_paletted_buffer` | memoryview/paletted 缺失时的 list + `np.asarray` / 逐面字符串展开回退（L400–L441） | 无 | B2 |
| P-06 | `bridge/point_cloud/extract.py` `extract_voxel_point_cloud` | `from_arrays` 回退、`ATTR_BLOCK_STATE` 逐点字符串路径（L140–L186） | 依赖 D-01 | B5 |
| P-07 | `bridge/point_cloud/standard.py` `inject_point_cloud_standard` | `positions` / `block_x/y/z` / `block_states` / `biomes` 属性回退（L58–L145） | 无 | B2 |
| P-08 | `bridge/mesh/attributes.py` | legacy STRING `mtk_source_texture_key` 读取/写入与 `dict.fromkeys` 回退（L39–L61、L89–L105、L128–L137、L167–L177） | D-04/D-05 | B6 |
| P-09 | `bridge/mesh/standard.py` | `get_flat_*` list 回退（保留 memoryview 主路径） | 无 | B2 |
| P-10 | `bridge/world.py` / `bridge/debug.py` | `SectionMesher.mesh_world` 回退（world L678、debug L123）与 `hasattr(VoxelWorld)` 门控（L592/L650）；改用 `VoxelWorld` | R-01 | B3 |
| P-11 | `bridge/world.py` | 4 处 broad `TypeError` 重试（L628/L646/L660/L673） | 无 | B2 |
| P-12 | `bridge/save.py` | `inspect_minecraft_save` 假 metadata 回退（L50–L75） | 无 | B2 |
| P-13 | `bridge/save.py` | `load_and_mesh_minecraft_save` 的 callback `TypeError` 回退（L165–L176） | 无 | B2 |
| P-14 | `bridge/sync.py` / `bridge/world.py` / `operators/sync/*` | `set_unified_mesh` / `unified_mesh` 传参（sync L259–L260、world from_storage 调用等） | R-05/R-06 | B4 |
| P-15 | `bridge/material.py` | 无调用方的 `remap_mesh_multi_uvs`、`resolve_mesh_material_routes` 包装 | R-23 | B3 |
| P-16 | `bridge/material.py` | `compute_mesh_material_props` / `compute_flat_material_props` 包装（保留 memoryview/paletted） | R-22 | B3 |
| P-17 | `bridge/mesh/dna.py` / `bridge/point_cloud/dna.py` | `direct_copy_*` method 级 DNA 兜底 `elif` 分支；只保留独立 `libmtk_blender_dna` 适配器 | R-08/R-09 | B3/B7 |

### 3.2 Python UI / 右键菜单

| ID | 位置 / 符号 | 删除内容 | 依赖 | 批次 |
|---|---|---|---|---|
| U-01 | `operators/op_voxel_cloud.py` `MOZI_OT_remesh_from_voxel_cloud` | 删除重复算子、`@register_menu_item`、`OPERATOR_CLASSES` 项；**保留右键“Rebuild Voxel Mesh”入口**，统一由 `mozi.rebuild_mesh` 的 CLOUD 分支执行（如需“Remesh from Voxel Cloud”文案，只改 label，不加第二个算子） | 无 | B1 |
| U-02 | `operators/op_voxel_cloud.py` `MOZI_OT_rematerialize_from_voxel_cloud` | 整个算子（`execute` 只调用 remesh） | 无 | B1 |
| U-03 | `operators/op_materials.py` `MOZI_OT_update_material_shading_adaptation` | 整个算子、`@register_menu_item`、`OPERATOR_CLASSES` 项；保留 `update_materials_render_engine_adaptation` utility | 无 | B1 |
| U-04 | `operators/op_materials.py` `MOZI_OT_clean_empty_material_slots` | **整个算子、`@register_menu_item`、`OPERATOR_CLASSES` 项删除**；Blender 已有 `object.material_slot_remove_unused`，不再自定义用户操作符。网格构建中的自动槽位压缩走现有材质重建 + `remap_indices_lut` | 无 | B1 |
| U-05 | `ui/menu_select.py` `MOZI_MT_select_uv_menu` | 空菜单类、`draw_uv_select_workspace_menu_func`、注册/反注册、`ui/__init__.py` 导出 | 无 | B1 |
| U-06 | `utils/system/menu_registry.py` | `mozi.replace_materials` legacy alias、`is_legacy` 字段与过滤 | 无 | B1 |
| U-07 | `utils/system/menu_registry.py` | `register_operator_menu_item` 自动生成 `object.mozi_*` / `mesh.mozi_*` 旧 ID 的分支 | 无 | B1 |
| U-08 | `utils/config/models.py` `normalize_operator_id` | `mozi.replace_materials`、`restore_materials_from_*` 等旧别名特殊处理 | 无 | B1 |
| U-09 | `utils/config/models.py` `is_valid_operator_id` | 只检查 `mozi.` 前缀的实现；改为“必须存在于 `ALL_OPERATORS` 且非 internal” | U-06/U-07 | B1 |
| U-10 | `utils/config/models.py` | `MENU_SCHEMA_VERSION`、`MENU_SCHEMA_CHANGELOG`、`reconcile_views_with_canonical_presets`、`from_dict` 的 schema 推断 | 无 | B1 |
| U-11 | `utils/system/menu_registry.py` `draw_dynamic_menu` | 未注册/legacy ID 未过滤；增加 `op_id in _REGISTERED_MENU_ITEMS` 检查 | U-09 | B1 |
| U-12 | `tests/test_menu_registration.py`、`docs`、i18n | 迁移/删除 remesh、rematerialize、sync shading、clean slots、空 UV 菜单相关断言与文案 | U-01…U-05 | B1 |
| U-13 | `utils/materials/cleaner.py` | 删除仅被已删算子/测试使用的 `clean_object_material_slots`、`clean_scene_material_slots`、`compact_mesh_material_slots`；保留 `bridge/world.py` 仍在用的 `remap_indices_lut` | U-04 | B1 |

### 3.3 Rust Core / Bindings

| ID | 位置 / 符号 | 删除内容 | 依赖 | 批次 |
|---|---|---|---|---|
| R-01 | `bindings/mtk-py/src/mesher.rs` | 整个 `PySectionMesher`（`mesh_world` / `mesh_sections_split` / `rebuild_dirty_sections`）及注册 | 无 | B3 |
| R-02 | `crates/libmtk/src/pipeline.rs` | 整个 `process_mesh` 管线、`MeshPipelineConfig`、`ProcessMeshOutput`、`MeshProcessStats`、`ResolvedMaterialInfo` | 无 | B3 |
| R-03 | `bindings/mtk-py/src/lib.rs` | `process_mesh` PyO3 函数与注册；对应 Rust 单测 | R-02 | B3 |
| R-04 | `crates/mtk-material/src/remap/batch.rs` | `remap_mesh_multi_uvs_parallel` legacy static Frame-0 包装（保留 `_with_options` / paletted） | R-02 | B3 |
| R-05 | `crates/mtk-voxel/src/world/mod.rs` | `unified_mesh` 字段、构造参数、`set_unified_mesh`、`assemble_world_mesh` 的 false 分支 | 无 | B4 |
| R-06 | `crates/mtk-sync/src/session/mod.rs` | `LiveSyncSession::new(..., _unified_mesh)` 参数、`set_unified_mesh` no-op | R-05 | B4 |
| R-07 | `bindings/mtk-py/src/voxel/world.rs`、`bindings/mtk-py/src/sync.rs` | `unified_mesh` 构造参数、`set_unified_mesh` 方法 | R-05/R-06 | B4 |
| R-08 | `bindings/mtk-py/src/mesh/mod.rs` | 6 个 `direct_copy_*` method 级 DNA 入口 | 无 | B3 |
| R-09 | `bindings/mtk-py/src/point_cloud.rs` | `direct_copy_*` method 级 DNA 入口 | 无 | B3 |
| R-10 | `bindings/mtk-ffi/` | 整个 crate、workspace member、CI 引用、文档 | 无 | B3 |
| R-12 | `crates/mtk-package/src/header.rs` | `CompressionType::Lz4`、`ChecksumType::XxHash64`、`HeaderFlags::EXTERNAL_REF`（注：`SceneInterchange` 作为轻量场景交换包 `.mtkscene` 的核心规划予以保留） | 无 | B4 |
| R-13 | `crates/mtk-model/src/baker/baked_model/legacy.rs` | 未压缩 bincode、models-only HashMap 两种回退；文件改名 `binary.rs` | 无 | B4 |
| R-14 | `crates/mtk-model/src/baker/baked_model/database.rs` | `#[serde(alias = "multi_variants")]` 旧字段别名 | R-13 | B4 |
| R-15 | `crates/libmtk/src/prebake/reader.rs` | `ASSET_CACHE_FORMAT_VERSION` 2 → 3；旧缓存不再兼容 | R-13 | B4 |
| R-16 | `crates/mtk-save/src/loader.rs` | 仅删除 `DIM-1/region`、`DIM1/region` pre-1.18 路径；**Gzip（region type 1）保留**，补一个 Gzip chunk 读取测试 | 无 | B4 |
| R-17 | `crates/mtk-sync/src/protocol/constants.rs` | `0x01 REPLAY_DELTAS` 降级分支 | 无 | B4 |
| R-18 | `crates/mtk-sync/src/session/dispatcher.rs` | tokenless HELLO `unwrap_or` fallback；`initial_hello` 改为必需 `Packet` | 无 | B4 |
| R-19 | `crates/mtk-core/src/lib.rs` | `pub use extrude as extrude_mesh` 别名；更新 `bindings/mtk-py/src/extrude.rs` | 无 | B4 |
| R-20 | `crates/mtk-voxel/src/world/mod.rs` | `pub use crate::storage::world::*` 向后兼容再导出；更新导入 | 无 | B4 |
| R-21 | `bindings/mtk-py/src/extrude.rs`、`lib.rs` | `process_mesh_extrude_repair`、`process_random_extrude_mesh` 嵌套 list 入口与注册 | 无 | B3 |
| R-22 | `bindings/mtk-py/src/material/biome.rs`、`lib.rs` | `compute_mesh_material_props`、`compute_flat_material_props`（list 版）；保留 memoryview/paletted | P-16 | B3 |
| R-23 | `bindings/mtk-py/src/material/resolver.rs`、`lib.rs` | `remap_mesh_multi_uvs` 逐面字符串入口；保留 paletted | P-15 | B3 |
| R-24 | `bindings/mtk-py/src/point_cloud.rs` | `from_arrays`、`get_block_states`、`get_biomes`、`to_mesh_data`/`from_mesh_data` 的字符串路径 | D-01 | B5 |
| R-25 | `bindings/mtk-py/src/voxel/storage.rs` | 零调用 snapshot/CRC/manifest 方法（`set_full_snapshot`、`apply_delta_update`、`validate_manifest`、`calculate_and_store_section_crc` 等） | 无 | B6（延后，先做测试审计） |
| R-26 | `bindings/mtk-py/src/voxel/world.rs` | 零调用 `set_full_snapshot`、`apply_delta_update`、`compact_world_mesh_materials`、`load_from_point_cloud` | 无 | B3（已完成） |
| R-27 | `bindings/mtk-blender-dna/src/mesh.rs`、`lib.rs` | 无生产调用的 `copy_face_materials_to_ptr`、`copy_loop_starts_to_ptr`、`copy_loop_totals_to_ptr`、`copy_buffer_to_ptr`（`copy_buffer` 仅测试） | 无 | B3 |
| R-28 | `bindings/mtk-py/src/resource.rs`、`lib.rs` | `create_test_cache_package` 生产导出；移到 `mtk-testkit` / dev 或 feature gate | 无 | B6（延后，测试仍在使用） |
| R-29 | `bindings/mtk-py/README.md` | 不存在的 `tint_indices_memoryview`、`flags_memoryview`、`get_face_tints`、`list_attributes`，错误的 extrude/process_mesh/SectionMesher 签名 | 全部 | B6 |
| R-30 | `docs/BINDINGS_DESIGN.md`、`docs/ARCHITECTURE.md` | `mtk.h`/cbindgen、`.mtkscene`、`mtk-blender` 独立扩展等未实现描述 | 全部 | B6 |
| R-31 | `bindings/mtk-py/src/mesh/mod.rs` | 仅测试/旧 fallback 使用的 `get_flat_positions/normals/uvs`、`get_indices`、`get_quad_indices`、`get_face_materials`、`set_buffers`、`append_unit_cube_face`、`weld_spatial_vertices`；迁移测试后删除或 feature gate | P-09/D-07 | B5 |

> 注：原 R-11（`bindings/mtk-wasm`）已从删除表移除；WASM 保留并继续维护，见 §8.1 W-01。

### 3.4 规模估计

- Python bridge / UI：约 600–900 行（含被删算子、legacy 注册与测试）。
- Rust bindings：约 1000–1500 行（含 `PySectionMesher`、`process_mesh`、FFI、direct copy、零引用方法；WASM 保留，不计入删除量）。
- Rust core 旧格式/协议：约 300–500 行。
- 一个 crate 整体移除：`bindings/mtk-ffi`；`bindings/mtk-wasm` 保留并继续维护。
- DNA 从 805 行、带 `mtk-core`/`mtk-voxel` 依赖，重构为无核心依赖的 leaf crate；目标独立 wheel 体积控制在数百 KB 量级。
- 数据模型重构（B5）另计，预计净减 300–600 行，但主要收益是内存与正确性，行数不是指标。

### 3.5 测试 / 配置 / 文档

| ID | 位置 | 处理 | 批次 |
|---|---|---|---|
| T-01 | `tests/test_voxel_point_cloud.py` | 删除/迁移 `remesh_from_voxel_cloud` 用例到 `rebuild_mesh` | B1 |
| T-02 | `tests/test_asset_bake_guard.py` | 删除/迁移 remesh stale-cache 用例 | B1 |
| T-03 | `tests/test_menu_registration.py` | 删除 legacy schema 用例；增加内部算子黑名单、未知 ID 过滤、空菜单不存在断言 | B1 |
| T-04 | `tests/test_clean_empty_material_slots.py` | 已删除；`remap_indices_lut` 测试迁移到新建 `tests/test_material_index_remap.py` | B1 |
| T-05 | `.blender-test-config/MoziToolKit/context_menus.json` | 重置为 canonical presets（无 legacy/schema 字段） | B1 |
| T-06 | `docs/mesh/voxel_point_cloud.md` | 删除 `mozi.remesh_from_voxel_cloud` 流程，改为 `rebuild_mesh` | B1/B6 |
| T-07 | `TODO.md`（两个仓库） | 勾掉已完成项；把“保留稳定 C-ABI”改为“无消费者 API 可删” | B6 |

---

## 4. 非删除但必须收口的重构

这些不在“直接删”范围，但会决定删除后系统是否仍正确：

| ID | 目标 | 说明 |
|---|---|---|
| D-01 | `VoxelPointCloud` 改 palette + indices | 删除逐点 `Vec<String>`，`from_indexed_arrays` 不再展开字符串；`to_mesh_data` 写 `mtk_state_idx` + `mtk_palette` |
| D-02 | `MeshData` UV 布局显式化 | 明确 `uvs` 是逐顶点还是逐 loop；消除 `uvs.len() == total_loops` 猜测；统一 `loop_uvs_memoryview` / DNA 展开 |
| D-03 | 两套 weld 合并 + loop 展开上收 | `MeshData::weld_spatial_vertices`（位置）与 `subdivide::weld_mesh_vertices`（UV 接缝）统一为显式策略；`loop_uvs` / `loop_starts` / `loop_totals` 展开上收到 `mtk-core`，`memoryview.rs` 与 `mtk-blender-dna` 不再各写一份 |
| D-04 | 暴露 `compute_mesh_biome_attributes_paletted_flat` | core 已有实现（`mtk-material/src/biome/batch.rs`），只差 PyO3 + 扁平 memoryview 输出 |
| D-05 | 材质 palette/provenance builder | 把 `extract_face_material_palette_context` 的逐面 object 数组 / `.tolist()` 收进 Rust |
| D-06 | random extrude flat 通道 | nested `process_random_extrude_mesh` 入口已在 B3 删除；Python 仅调用 `generate_random_extrude_heights` + flat repair |
| D-07 | `PyMeshData.from_flat_polygons` | 复用 `FlatPolygonMesh`，共享顶点 + 逐 loop UV，替代 `from_raw_buffers` 的 4 倍角点复制 |
| D-08 | `API_VERSION` / 能力握手 | `libmtk_py` 暴露整数 API 版本；`bridge/engine.py` 启动时校验，失败给出重装/重编译提示 |
| D-09 | 宿主内存适配层独立 | 通用复制下沉到 `mtk-host-memory`，`mtk-blender-dna` 只保留 raw slice 语义包装；独立 `libmtk_blender_dna` wheel 通过 Buffer Protocol 接收核心 `memoryview`。核心 `libmtk_py` 不依赖也不认识适配器 |
| A-01 | `ensure_world_materials` 归位 | 从 `bridge/world.py` 移到 `utils/materials/builder/world_binding.py`；`bridge` 只保留取 metadata / texture buffer 的职责 |
| A-02 | `apply_imported_save_to_blender` 归位 | 从 `bridge/save.py` 移到 `operators/save/hierarchy.py` 或 `utils/save/`；`bridge/save.py` 只保留 `mtk-save` 调用中继 |
| A-03 | 文档单一事实源 | README/API 清单从代码生成或加符号存在性测试；删除 `mtk.h`、`.mtkscene`、独立 `mtk-blender` 等未实现描述 |

### 4.1 DNA 独立库方案（D-09 细化）

现状问题（已解决）：`mtk-blender-dna` 曾依赖 `mtk-core` + `mtk-voxel`；而 `mtk-voxel` 又拉入 `mtk-material`、`mtk-model`、`mtk-resource`、`mtk-texture`、`rayon` 等。结果这个“DNA 库”实际把大半套核心静态链接了进去，和 `libmtk_py` 形成“两个核心”。

目标形态：

- **`crates/mtk-host-memory`**：宿主无关的 raw slice → pointer 复制原语，只依赖 `thiserror`；负责空指针、对齐、`max_bytes` 容量守卫。
- **`bindings/mtk-blender-dna`**：Blender 语义包装（positions / indices / UV / colors / point cloud），只接受 `&[f32]` / `&[u32]` / `&[i32]` / `&[u8]`，不依赖任何 `mtk-*` 核心 crate。
- **`bindings/mtk-blender-dna-py`**：独立 `libmtk_blender_dna` ABI3 wheel，通过 Python Buffer Protocol 从核心 `memoryview` 取指针，再调用 Blender 适配层。
- **核心 `libmtk_py`**：只导出 `memoryview`；不链接、不导入、不知道 `libmtk_blender_dna` 的存在。
- **组合根**：`bridge/engine.py` + `bridge/mesh/dna.py` / `bridge/point_cloud/dna.py` 负责选择适配器；缺失或版本不匹配时回退标准 `foreach_set`。
- **未来宿主**：可替换为 `libmtk_maya_dna` 等独立适配器，核心与 `.mtkscene` / `.mtkstate` 不变。

安全边界：

- 适配器不缓存源或目标指针；只在一次调用内使用。
- 源 `memoryview` 在调用期间保活，核心 buffer 不可扩容/修改。
- 目标指针必须在 Blender 拓扑分配后解析；适配器只做 `copy_nonoverlapping`。
- 第一版保持 GIL，优先正确性；后续有数据再评估 `allow_threads`。

体积与依赖门禁：

- `cargo tree -p mtk-blender-dna` / `-p mtk-host-memory` 不得出现 `mtk-core` / `mtk-voxel`。
- `libmtk_blender_dna` 独立 wheel 体积 < 1.5 MB（当前约 187 KB）。
- CI 同时校验 6 平台 `libmtk_py` 与 `libmtk_blender_dna` wheel。

## 5. 执行批次（B0–B7）

### B0：基线与护栏（0.5 天）

- [ ] 记录 `get_all_operators()` 与原生 API 快照（可保存为 `tests/fixtures/` 或临时文件）。
- [x] 跑一遍 Rust/Python 基线测试并记录结果（Rust 323 passed；Python 271 passed / 73 skipped）。
- [ ] 建两个仓库的 `refactor/2.0-delete-b*` 分支。
- [ ] 准备 `rg` 检查脚本（见 §6）。

### B1：UI / 右键菜单收敛（0.5–1 天，独立；即此前讨论的 P0.5）

顺序：

1. 删除 `remesh_from_voxel_cloud` / `rematerialize_from_voxel_cloud` 算子与注册；保留右键 `rebuild_mesh` 的 Voxel 重构入口。
2. 删除 `update_material_shading_adaptation` 算子；**删除 `clean_empty_material_slots` 算子**（Blender 已有原生清理操作符），并裁掉 `cleaner.py` 中仅该算子使用的函数。
3. 删除空 `MOZI_MT_select_uv_menu`。
4. 删除 legacy alias / category-prefixed ID / `is_legacy` / schema 迁移。
5. `is_valid_operator_id` 改为 `ALL_OPERATORS` 成员校验；`draw_dynamic_menu` 跳过未注册 ID。
6. 重置 `context_menus.json`；更新测试/i18n/docs。

验收：

- [x] `get_all_operators()` 不含内部算子黑名单。
- [x] 手写 `mozi.ghost` 配置不会渲染。
- [x] 右键菜单仍保留 `Rebuild Voxel Mesh`（Voxel 重构入口），但没有重复的 remesh/rematerialize 项。
- [x] 空 `MOZI_MT_select_uv_menu` 已删除。
- [x] `pytest tests/test_menu_registration.py -q` 通过。
- [ ] Blender 内右键菜单/注册冒烟（待宿主环境）。

### B2：Python 胶水层假回退 / 旧 wheel 回退（1 天）

删除 P-01…P-05、P-07、P-09、P-11…P-13；P-10/P-14 留到 B3/B4。

验收：

- [x] `rg "expanded = \\["` 无命中；`compute_flat_material_props_buffer` 只剩直接 native 调用。
- [x] compute/save/extrude 路径不再返回假数据；缺失 native API 直接抛 `RuntimeError`。
- [x] 全量 Python 测试通过（271 passed / 70 skipped）。
- [x] `bridge/world.py` 不再吞 `TypeError`，参数错误会直接暴露。

### B3：Rust 零调用方 API（1–2 天）

删除 R-01…R-03、R-08…R-10、R-21…R-23、R-26、R-27；R-25/R-28 延后到 B6。同步 P-10/P-15/P-16/P-17。WASM 不删。

验收：

- [x] `libmtk_py` 不再导出 `SectionMesher`、`process_mesh`、`direct_copy_*`、嵌套 extrude。
- [x] `cargo check --workspace` 通过；Rust 测试 317 passed。
- [x] Python 测试中 `SectionMesher` 全部迁移到 `VoxelWorld` 测试 helper。
- [x] 全量 Python 测试 268 passed / 70 skipped。
- [ ] `PyVoxelStorage` 零引用方法与 `create_test_cache_package` 延后到 B6。

### B4：旧格式 / 旧协议 / unified_mesh（1 天）

删除 R-05…R-07、R-12…R-20；同步 P-14。

验收：

- [x] 全仓库无 `unified_mesh=False` 调用。
- [x] `ASSET_CACHE_FORMAT_VERSION = 3`；旧 models.bin 加载失败并给出明确错误。
- [x] `mtk-package` 不再声明 Lz4/XxHash64（保留 `SceneInterchange` 作为 `.mtkscene` 核心规划）。
- [x] `mtk-save` 不再寻找 `DIM-1`/`DIM1`；Gzip chunk 测试保留。
- [x] `mtk-sync` 不再接受 0x01 decision / tokenless HELLO。
- [x] `cargo test --workspace` 通过。

### B5：数据模型收敛（3–5 天，风险最高）

执行 D-01、D-02、D-03、D-07；随后 P-06/R-24。

验收：

- [x] 1M 点云 `from_indexed_arrays` 不再分配逐点 `String`；峰值内存回落到“位置 + 索引”量级（本机 1M 点进程峰值 ~85 MB）。
- [x] `to_mesh_data` / `from_mesh_data` 只使用 `mtk_state_idx` + `mtk_palette`。
- [x] `MeshData` 的 UV 布局有显式字段/枚举，不再用 `uvs.len()` 猜。
- [x] `MeshData::weld_spatial_vertices` 与 `weld_mesh_vertices` 合并为一个显式策略 API（`weld_vertices` + `UvLayout`）。
- [x] 外部网格导入不再 4 倍顶点复制，且 UV 接缝保留（`from_flat_polygons`）。

### B6：能力接出与架构归位（2–3 天）

执行 D-04、D-05、D-06、D-08；P-08；A-01 `ensure_world_materials`、A-02 `apply_imported_save_to_blender` 迁移；R-29/R-30/A-03/T-06/T-07 文档收尾。

验收：

- [x] Python 1M 面 biome 路径使用 palette + flat memoryview，不再逐面字符串（`compute_biome_tint_attributes_paletted` + `build_material_palette`）。
- [x] `ensure_world_materials` 只剩桥接职责；材质编排在 `utils/materials/builder/world_binding.py`。
- [x] `apply_imported_save_to_blender` 的场景层级/UUID/隐私清洗在 `utils/save/hierarchy.py`。
- [x] README/API 文档不再列出不存在的符号；新增 native API surface contract 测试。
- [x] `API_VERSION` 校验生效（native `api_version()` + `bridge/engine.py` 握手）。
- [x] WASM CI 仍为绿；Gzip chunk 测试通过。

### B7：独立宿主内存适配层（2–3 天）

执行 D-09 与 §4.1：

1. 新增 `crates/mtk-host-memory`，提供无核心依赖的 typed raw copy + 边界守卫。
2. `mtk-blender-dna` 改为 raw slice 语义包装，移除 `mtk-core` / `mtk-voxel` 依赖。
3. 新增独立 `bindings/mtk-blender-dna-py` wheel（`libmtk_blender_dna`），只依赖 `mtk-blender-dna` + `pyo3`。
4. 从 `mtk-py` 删除 `unstable.blender_dna`，核心不再包含任何宿主指针写入代码。
5. Python bridge 改为从核心取 typed `memoryview`，调用独立适配器；缺失/API 不匹配时回退 `foreach_set`。
6. 更新 wheel 构建、发布、打包与下载：6 平台同时产出/验证/打包两枚 wheel。
7. 增加依赖树、wheel 体积与逐字节 parity 门禁。

验收：

- [x] `cargo tree -p mtk-blender-dna` 不含 `mtk-core` / `mtk-voxel` / `mtk-material` / `mtk-model` / `mtk-texture`。
- [x] `libmtk_blender_dna` 独立 wheel < 1.5 MB（本机 187 KB）。
- [x] 核心 wheel 不再包含 `unstable.blender_dna`，也不链接适配器。
- [x] 成功路径与 `foreach_set` 结果一致；模块缺失/API 不匹配自动回退。
- [ ] 6 平台 CI 产出两枚 wheel，Mozi 滚动包同时包含两枚 wheel 并通过 Blender 冒烟。

---

## 6. 验证矩阵

### 6.1 每个批次必跑

```bash
# Rust
cd /Volumes/Data/mtk/libmozitoolkit
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace --no-fail-fast

# Python（使用工作区 venv，不污染宿主）
cd /Volumes/Data/mtk/MoziToolKit
../libmozitoolkit/.venv/bin/python -m pytest tests/ -q
```

### 6.2 符号零残留检查

```bash
cd /Volumes/Data/mtk
rg -n --glob '!**/target/**' --glob '!**/__pycache__/**' \
  'process_mesh_extrude_repair|process_random_extrude_mesh|SectionMesher|process_mesh\(|direct_copy_|unified_mesh|remesh_from_voxel_cloud|rematerialize_from_voxel_cloud|update_material_shading_adaptation|mozi\.replace_materials|MENU_SCHEMA_VERSION|Lz4|XxHash64|DIM-1|DIM1|REPLAY_DELTAS'
```

预期：B3 后只剩 `mtk-core` 内部合法的 nested extrude、`mtk-voxel::SectionMesher` 内部调用；B4 后旧格式/协议全部消失；B6 后菜单/文档不再命中。

### 6.3 Blender 冒烟

- [ ] 安装/链接插件，打开 Blender，注册无异常。
- [ ] 对象模式右键 → MoziToolKit：无空项、无未知算子。
- [ ] 网格编辑模式右键：同上。
- [ ] UV 编辑器右键/选择菜单：不再出现空子菜单。
- [ ] 加载 debug world → `Rebuild Voxel Mesh` → 正常出网格。
- [ ] 点云雕刻 → `Rebuild Voxel Mesh` → 空腔保留。
- [ ] 偏好设置 → Context Menu：Available 列表不含内部算子。

### 6.4 原生 API 快照

每批后重复 §2.1 的 API 列表，对比预期：`SectionMesher`、`process_mesh`、`direct_copy_*`、`from_arrays`、`get_block_states`、`get_biomes` 消失；`compute_mesh_biome_attributes_paletted_flat`、`from_flat_polygons` 在 B6 出现。

---

## 7. 风险与回滚

| 风险 | 影响 | 缓解 |
|---|---|---|
| 删除 `SectionMesher` 后测试/调试工具仍在用 | 测试失败、debug 面板不可用 | B3 前先提供 `VoxelWorld.get_section_cache()` / `rebuild_dirty()` 替代；批量迁移测试 |
| 点云 palette 化破坏旧 `.blend` | 旧点云无法读取 | 2.0 明确不兼容；加载时给“请重新导入”错误，不做字符串回退 |
| UV 布局改动影响 Blender 注入 | 接缝/法线错误 | 先加显式布局与断言，再切换消费者；用 debug world + 外部网格双回归 |
| 删除 FFI 影响未来 C4D | 未来需重写 | 代码在 git 历史；真有消费者时按该消费者 ABI 重建 |
| WASM 与 mtk-py 2.0 API 漂移 | Web 端功能落后 | WASM 保留在 workspace/CI；新增 `VoxelWorld`/palette 路径的跟进任务，不再把 WASM 当删除项 |
| DNA 独立 wheel 重新打包核心 | wheel 体积膨胀 | DNA crate 必须零 `mtk-core`/`mtk-voxel` 依赖；CI 增加 wheel 体积上限检查 |
| 菜单配置重置丢失用户自定义 | 用户需重配 | 2.0 无第三方用户；升级说明写清楚；配置过滤未知 ID |
| broad `TypeError` 删除暴露真实错误 | 启动失败 | 先加 API 版本校验，失败信息指向重装/重编译 |

回滚策略：

- 每批独立提交，直接 `git revert <commit>`。
- 不涉及数据库/资产格式的批次可无损回滚。
- B4/B5 涉及缓存格式与点云布局，回滚时需同时回滚 `ASSET_CACHE_FORMAT_VERSION` 与测试 fixture。
- `context_menus.json` 在 B1 前备份到仓库外；回滚时恢复文件即可。

---

## 8. 开放决策

执行前仍需确认：

1. **`toggle_voxel_cloud`**：保留在右键默认预设，还是只留在 Voxel 面板？
2. **DNA 分发形态**：已选定独立 `libmtk_blender_dna` wheel；核心 `mtk-py` 不包含宿主适配器。
3. **WASM 2.0 覆盖范围**：先保证现有 `WasmMeshData`/`WasmSectionMesher` 编译与 CI，还是本轮就补 `WasmVoxelWorld` / palette point cloud？

### 8.1 保留项维护

- **W-01 WASM**：保留 `bindings/mtk-wasm` 在 workspace 与 CI；B3 不删除。后续补 `WasmVoxelWorld` 或把 `WasmSectionMesher` 对齐 2.0 统一世界网格；palette point cloud / material 能力按 Web 端实际需求排期。
- **W-02 Gzip**：`mtk-save` region type 1 保留；补一个 Gzip chunk 读取测试，避免未来误删。
- **W-03 DNA 体积**：CI 增加 DNA crate 依赖树检查与 wheel 体积上限；若超过预算，优先删未使用 copy 函数，而不是重新引入核心依赖。

---

## 9. 进度跟踪

| 批次 | 状态 | 主要产出 | 验证 |
|---|---|---|---|
| B0 基线 | 进行中 | 基线测试已跑通（Rust 323 / Python 271+73skip）；分支、API/菜单快照待做 | 测试全绿 |
| B1 UI/菜单 | 已完成（自动化） | 删 4 个算子 + 空菜单 + 旧 registry；Python 271 passed / 70 skipped | menu 测试 |
| B2 Python 胶水 | 已完成（自动化） | 删 extrude/material/point-cloud/mesh/save/world 假回退与 TypeError 重试 | 全量 pytest |
| B3 Rust 零调用方 | 已完成（自动化；少量零引用方法延后 B6） | 删 SectionMesher/process_mesh/FFI/direct_copy/嵌套 extrude/字符串材质 API；WASM 保留 | Rust 317 / Py 268 |
| B4 旧格式/协议 | 已完成（自动化） | 删 unified_mesh、旧 package 枚举、pre-v3 models、DIM 路径、0x01/tokenless HELLO、extrude 别名与 storage 再导出 | Rust 321 / Py 268 |
| B5 数据模型 | 已完成（自动化；Blender 冒烟待 B0） | 点云 palette/indices、`UvLayout`、统一 weld、`from_flat_polygons` 共享顶点 | Rust 323 / Py 267 / 1M 点 ~85 MB |
| B6 架构/文档 | 已完成（自动化；Blender 冒烟待 B0） | palette biome、material palette builder、API_VERSION、A-01/A-02 归位、R-25/R-28、docs | Rust 323 / Py 270 / WASM 绿 |
| B7 独立适配层 | 实施中（本机通过） | `mtk-host-memory`、`mtk-blender-dna` 无核心依赖、独立 `libmtk_blender_dna` wheel、Python bridge 重接、打包/CI 双 wheel | Rust 323+ / Py 272 / Blender 331 |

---

## 10. 明确不删的运行时兜底

以下不属于“旧版本兼容”，保留：

- `bridge/mesh/__init__.py`、`bridge/point_cloud/__init__.py` 的 DNA → 标准 RNA 回退（跨 Blender 版本安全网）。
- `bridge/assets/cache.py` 的 `MOZI_CACHE_DIR` 测试沙箱分支。
- `mtk-texture` 的 atlas fallback（缺失贴图落到 fallback sprite）。
- `mtk-model` 的 builtin chest/bell 模型回退。
- `mtk-voxel` 的 fluid unit-cube fallback。
- `mtk-resource` 的 pack stack 逐层 fallback。
- `mtk-material` 的外部工具材质别名（Mineways / Jmc2Obj / Ice-Cube），除非确认外部网格导入功能下线。
- `mtk-cull` 的方块名目录与运行时剔除规则。
- `mtk-core::random` 的 Java Random 兼容实现（这是正确性，不是旧版本兼容）。
- `mtk-cli`、`mtk-bench`、`mtk-testkit`。
- `bindings/mtk-wasm`：保留并继续维护，不移出 workspace/CI。
- `mtk-blender-dna`：保留，但重构为无核心依赖的 leaf crate；Blender 版本不匹配/写入失败时回退 `foreach_set`。
- `mtk-save` 的 Gzip region type 1 读取路径。
- `utils/materials/cleaner.py::remap_indices_lut`（`bridge/world.py` 仍在使用）。
