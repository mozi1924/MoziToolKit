# Changelog

All notable changes to the **MoziToolKit** extension will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### 🧭 材质替换与网格重构边界收紧
- 新增 `mtk:geometry_origin` 网格来源标记（`EXTERNAL` / `SAVE` / `SYNC_WORLD` / `SYNC_SECTION` / `VOXEL` / `POINT_CLOUD`），在存档导入、Live Sync 世界网格与独立体素网格创建时写入；旧文件按 `mtk:is_save_mesh`、`mtk:is_yefira_mesh`、`mtk:is_section_mesh`、`mtk_is_voxel_cloud` 与命名约定回退推断。
- **替换材质仅对外部导入网格可用**：MTK 生成的网格（存档 / Live Sync / 体素）在右键菜单与 Voxel & Mesh Tools 面板中自动置灰，并显示“请编辑点云后重建”的上下文提示。
- **重建体素网格收紧来源要求**：存档容器与离线 Live Sync 必须存在伴生体素点云；活跃 Live Sync 会话仍可直接从内存 storage 重建，无需等待点云；仅有材质来源属性（provenance）的外部网格不再被误判为可重建对象。
- 修复存档复用已有网格时未补齐 `mtk:is_save_mesh` 标记的问题，并同步写入来源标记。

### 🐛 草方块侧面 Overlay 染色修复
- 图集基色与其 `_overlay` 伴生层共享同一个 `texture_id`；反向 id→key 表此前是 last-write-wins，会把 `grass_block_side` 解析成 `grass_block_side_overlay`，使该面拿到 base tint weight = 1，整个泥土侧面被草色染色。
- 现在反向解析优先选择非 `_overlay` 的基色 key（与 sprite 顺序无关）；再次执行替换材质时会自动纠正旧网格中被写错的 provenance。
- 新增回归测试覆盖纹理顺序、`remap_face_materials_and_uvs` 的 key 解析与 `[0, 1, 1, 1]` overlay-only tint 权重。

### 🎞️ 外部网格动画材质修复 (Animated Materials for Imported Meshes)
- **修复外部导入网格即使启用 `enable_animated_textures` 也始终使用静态图集的问题**：
  动画偏好现在会传入 Rust 图集路由；动画面映射到 `MTK:Atlas:*:anim:*`，静态面保留 Frame-0 基线。
- 外部网格现在注入完整的 `mtk_anim_timing` / `mtk_anim_frame_size` /
  `mtk_anim_total_frames` / `mtk_anim_frametime` / `mtk_anim_interpolate` /
  `mtk_anim_frame_width` / `mtk_anim_frame_height` face 属性，动画调度器与帧混合节点可获得真实帧数/帧时长。
- **动画偏好切换可逆**：Restore 路径新增 `reconcile_animation`，在静态/动画 chunk 之间
  反解并重投影已有 Atlas UV，无需重新导入外部网格。
- 修复 provenance 只索引静态 `sprites` 导致动画面 source key 退化为 `mozi:fallback` 的问题；
  现在同时索引 `anim_sprites`，后续 Restore / Biome 解析保持正确。
- 新增 Blender 宿主回归测试 `tests/test_external_material_animation.py`，覆盖 开→关→开 与关闭动画两种路径。

### 🧬 Host-Agnostic 胶水下沉 (Rust Core Downshift)
- **Rust 统一图集动画路由**：`mtk-material` 新增 `resolve_animated_sprite` /
  `resolve_routed_sprite` / `extract_animation_metrics` /
  `remap_mesh_multi_uvs_parallel_with_options`，`mtk-voxel` mesher 改为复用同一策略。
- **静态↔动画 UV 重路由**：新增 `resolve_mesh_material_routes` 与 `reroute_mesh_animation`，
  供 Blender / C4D 等宿主复用，不再依赖宿主侧保留原始局部 UV。
- **Live Sync 持久化状态下沉**：`mtk-sync::PersistedSessionState` 负责 JSON、UUID hex、bounds 与
  HELLO 构造；Blender 仅存 `mtk_sync_state_json` 不透明字符串，删除 Python 侧手写解析。
- **进度语义下沉**：新增 `normalize_stream_progress`，修正 meshing 阶段被二次加 50% 的问题；
  Python 只显示 Rust 返回的 `percent`。
- **握手决策语义修复**：`SyncEvent::Handshake` 新增 `decision_code`，修复 Python 将字符串
  `VERIFIED_SKIP_REBUILD` 与数字 `0` 比较导致 0ms 重连分支永不触发的问题。
- 修复 3 个 Live Sync timer 测试在真实 Blender 下的顺序隔离失败。

### ⚡ 即时 Biome 更新下沉与 DNA/foreach 边界（Instant Biome Recolor）
- **Biome 即时切换下沉 Rust**：新增 `mtk-material::reapply_uniform_biome_tint_flat`，
  并行计算逐面 tint type / color / colormap UV，并以扁平 `Vec<f32>` 输出。
- **零拷贝 memoryview**：PyO3 返回 3 个 Rust 持有的 memoryview，Python 直接 `foreach_set`，
  不再构造逐面 Python 对象，也不额外复制。
- **避免无谓读取**：仅当网格存在 `TINT_TYPE_HARDCODED` 面时才读取旧 `mtk_biome_tint_color`。
- 实测 498,436 faces：即时群系切换 **6.3–8.0 ms → ~2.1 ms**（约 3 倍）。
- **DNA 与 `foreach_set` 实测结论**：500k faces 三个 face 属性写入均为 ~0.52 ms，DNA 无实质收益；
  且 DNA 直写不会被 evaluated mesh 感知，必须手动 `mesh.update()`。因此 DNA 继续用于
  拓扑/位置/法线/UV/顶点色/体素点云，通用 face 属性继续 `foreach_set`。
  详见 [`docs/mesh/direct_mesh.md`](docs/mesh/direct_mesh.md) §7。

### 🧵 外部网格材质提取向量化（External Mesh Extraction）
- `extract_face_material_context` 改为 `foreach_get` + NumPy object-array 索引，
  移除逐 polygon RNA 访问；159k faces 从 0.317 s 降到 0.050 s。
- `face_source_keys` 改为 texture-id 稠密表 + NumPy 索引，移除逐面 dict/append 循环。
- 删除 `inject_mesh_provenance_attributes` 的逐面 `clean_keys` decode/str 循环。
- 新增 `compute_flat_material_props_memoryview`：Rust 直接返回零拷贝 memoryview；
  `inject_face_attribute_float4` 识别 buffer，跳过 `np.ascontiguousarray` 复制。
- UV transform 改为 `np.asarray(...).ravel()`，避免逐面 Python `extend`。
- 500k faces 外部 replace 实测 **2.65 s → 1.70–1.85 s**。

### 🚀 Palette-Native 材质管线与 P2 基础设施
- **Palette-native 外部网格 remap**：`remap_mesh_multi_uvs_paletted_with_options` 直接消费
  `palette + u32 indices`，返回 source-key palette/indices 与全部 id/metric 的零拷贝 memoryview；
  500k faces replace **2.65 s → ~0.95 s**。
- **提取与槽位向量化**：`extract_face_material_palette_context`、`np.unique` + `searchsorted`
  材质槽映射、buffer-aware 的 `inject_face_attribute_*`。
- **Live Sync 事件合并**：`LiveSyncSession::poll_events_coalesced()` 在 Rust 侧只保留最新
  `WORLD_MESH_READY` generation；Blender bridge 默认使用 `coalesce_meshes=True`。
- **资产缓存解析下沉**：`libmtk::prebake::resolve_active_cache_package` + PyO3；
  Python 优先使用 Rust 的 fingerprint/header/mtime 解析，保留测试沙箱 fallback。
- **C-ABI 首批**：`mtk-ffi` 新增 `mtk_resolve_material_routes`、
  `mtk_sync_state_is_reconnect_candidate`、`mtk_biome_reapply_uniform_tint`。

### 🐛 Live Sync 稳定性修复 (Realtime Sync Stability)
- **修复大选区/多生物群系基线永久校验失败（卡在 75%）**：Rust 基线组装器此前使用全局 Quart 索引 `qx & 3` 写入 Section-local 生物群系，未考虑选区 `min_pos` 非 16 对齐的情况，导致 Canonical State Hash 与 Minecraft 端失配并无限重同步。现改为按 `(world >> 2) & 3` 的 Section-local Quart 坐标写入，并新增非对齐选区回归测试。
- **修复刷新后偶发提示“未连接”**：终态 `DISCONNECTED` 事件不再因原生 worker 已退出而被丢弃；Blender 面板连接状态统一以原生 `LiveSyncSession` 的 `is_connected` / `status` 为准，中间态传输告警（解码/发送错误）不再误判为断线。Refresh 会先同步真实状态并给出精确提示。
- **修复多次移动大选区后重连卡死/不再收到体素**：
  - Minecraft 端基线扫描与推流改为**按客户端代际 (generation) 单流化**，新选区/刷新/重同步会协作中止旧扫描，杜绝多流交错与重复大内存分配；
  - `/yefira refresh` 与握手/重同步路径全部异步化，不再阻塞游戏主线程；
  - 扫描器支持协作取消，超出协议 32M 体素硬限制的选区直接在服务端拒绝并回传 `ERROR`；
  - 基线期间延迟发送 Delta，确保 Delta 调色板与客户端即将安装的快照调色板一致；
  - 客户端忽略过期快照的 BEGIN/CHUNK/END，新增基线看门狗、重同步限流与连续失败熔断（点击 Refresh 或更换选区即可重试）；
  - 重连复用原生会话时彻底重置生命周期/序列号/半截基线并清空遗留网格事件，连接时重置 `mtk:client_generation`，避免 `.blend` 中遗留的高 generation 导致新网格被当作过期数据丢弃。
- **协议文档与实现对齐**：
  - 将 RFC v3.1 纳入 `docs/live_sync/live_sync_protocol.md`，补充 Section-local Quart 契约、Delta 16,384 分片、代际栅栏、看门狗/熔断、快速重连持久化与 10 项已知偏差矩阵；`mtk-sync` / Yefira README 增加权威链接。
  - Delta 广播按 16,384 条/批切分，每批独立单调 `sequence`，消除 uint16 计数溢出风险；基线期间延迟 Delta，确保调色板与快照栅栏一致。
  - 持久化 `mtk_sync_server_uuid` / `mtk_sync_state_hash` 等快速重连属性；服务端在任何方块变更后使 `cachedStateHash` 失效。Blender 端暂时保持 `HELLO.cached_*` 为零（等待原生 `VoxelStorage` 持久化），连接始终走安全的全量基线。

---

## [2.0.0] - 2026-10-16

### 🚀 Major Architectural Leap (Rust Core Integration)
- **Rust Core Offloading (`libmtk`)**:
  - Migrated all computation-heavy mesh processing, voxelization, face culling, texture packing, and colormap math to the host-agnostic Rust engine `libmozitoolkit`.
  - Replaced legacy Python algorithms with zero-copy/low-copy flat buffer streaming (`PyMeshData`, `PyVoxelStorage`).
  - Native image decoding, atlas packing, and WebSocket streaming are now handled natively inside Rust without external Python package dependencies.
- **Dual-Mode Dev/Release Architecture**:
  - **Development Mode**: Dynamic direct-link bootstrap via `dev/loader.py` linking directly to `target/release/liblibmtk_py.so`, eliminating wheel rebuilding and Blender cache lockups.
  - **Release Packaging**: Unified `python3 build.py` builder that bundles precompiled ABI3 wheels into platform-isolated distributions following the Blender 5.0+ Extensions Platform specification.

### 🌐 Minecraft Live Sync (Real-Time World Synchronization)
- Full-duplex WebSocket connection to Minecraft world servers and Fabric clients (`Yefira`).
- Incremental delta meshing with smooth 4-corner ambient occlusion (AO) and animated texture routing.
- Real-time viewport streaming with non-blocking modal operators and asynchronous progress bars.
- Empty root container hierarchy with companion Voxel Point Clouds for fast carving, editing, and lossless remeshing.

### 🎨 Material & Shader Pipeline
- **Atlas & Standalone PBR Pipelines**:
  - High-performance atlas stitching engine with dynamic padding and bleeding prevention.
  - Full PBR shader generation supporting LabPBR (normal, roughness, metallic, emissive, subsurface) and OldPBR specs.
  - CTM (Connected Textures Mod) full 47-tile state resolution and custom tint layers.
- **Authoritative Biome Tinting (SSOT)**:
  - 66 canonical vanilla Biomes with hardware-accurate temperature/humidity colormap sampling.
  - Authoritative Perlin noise-based swamp grass dual-color interpolation centralized in `mtk-material`.
  - Sub-millisecond instant biome switching via mesh face attribute injection.
- **Blender 5.x / 6.0 Forward Compatibility**:
  - Deprecated API removal (eliminated direct `use_nodes = True` assignments).

### 🛠️ Modeling, UV & Geometry Tools
- **Smart Extrusion & UV Repair**:
  - Continuous pixel-boundary extrusion with automatic side face UV rectification and quad-preserving topology.
- **Adaptive Pixel Grid Slicing**:
  - Exact planar grid face subdivision with bilinear property interpolation (normals, vertex colors, weights).
- **Hard Edge & Normal Tools**:
  - Operator to select hard & sharp edges based on angle thresholds and edge tags.
  - Operator to strip invalid `custom_normal` attributes and clear split normal data.

### 🧹 Code Cleanliness & Boundary Enforcement
- **Eliminated Python Shadow Fallbacks**:
  - Removed mock `_FallbackBiomeResolver`, `_FallbackMaterialResolver`, and local tint constants from `bridge/material.py`.
  - Replaced duplicate tint definitions with authoritative SSOT constants exported from Rust.
- **Layering & Inverted Dependency Fixes**:
  - Eliminated reverse imports from `bridge/` into `utils/` (`bridge.extrude` now provides authoritative pixel steps).
  - Enforced strict unidirectional dependency topology: `ui` / `operators` → `utils` → `bridge` → `libmtk_py`.
- **Operator Modularization**:
  - Modularized `operators/op_mesh.py` into dedicated `operators/mesh/` package (`op_select_hard_edges.py`, `op_clear_normals.py`, `op_rebuild_mesh.py`) while preserving backward-compatible import stubs.
- **Memory & Lifecycle Safeguards**:
  - Added `clear_biome_updater_cache()` registered to `bpy.app.handlers.load_pre` to prevent memory leaks and stale VoxelStorage collisions across `.blend` file sessions.
- **Removed Deprecated Shims**:
  - Cleaned up obsolete `is_hard_edge`, `sync_voxel_point_cloud_for_world`, multi-tier fallback exception ladders, and legacy format decoders.

---

## [1.1.0] - Prior Release
- Initial material replacement pipeline for Mineways and jmc2obj world exports.
- Basic UV scale and closest interpolation operators.
- Dynamic right-click context menu configuration.
