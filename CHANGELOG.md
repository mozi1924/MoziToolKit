# Changelog

All notable changes to the **MoziToolKit** extension will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### 🧩 资源包 / JAR 内容识别与自动分类
- 新增 `utils/pack_detect.py`：只读 ZIP 中央目录（元数据读取上限 64KB，不解压任何资源）判定输入是**原版客户端 / 原版服务端 / 模组（Fabric/Quilt/Forge/NeoForge）/ 资源包 / 数据包 / 整合包**，取代原先仅凭扩展名与 `fabric`/`forge`/`mod` 关键字的启发式。`26.2-Fabric.jar`（内容实为原版客户端）不再被判为 `MOD_JAR`，以 `.jar` 分发的 CTM 材质包不再被判为 `VANILLA`。
- 判定采用**根路径精确匹配 + 加权打分**：原版 JAR 内部的 `data/minecraft/datapacks/*/pack.mcmeta` 与根 `pack.png` 不参与资源包计分；Forge universal JAR 的 `pack.mcmeta` 不会盖过 `META-INF/mods.toml`。单层包裹目录（`MyPack/...`）可被识别并提示 Minecraft 无法直接加载。
- 偏好设置新增 `pack_type_source`（AUTO/MANUAL）与 `detected_kind`：用户手动改过类型后自动识别不再覆盖；新增 `mozi.pack_detect`「重新识别」按钮，详情面板展示识别结果、置信度与「不提供贴图」告警。配置模型、JSON 后端、Blender Preferences 后端与导出/导入均持久化这两个字段，旧配置缺省为 AUTO。
- 调度采用「150ms 防抖 + 工作线程判定 + `bpy.app.timers` 主线程写回」：路径回调实测 1.3 ms 返回，31,709 条目的 39 MB 原版 JAR 判定约 37–49 ms 且不阻塞 UI；结果按 `(realpath, size, mtime_ns)` 缓存，面板 `draw` 只查内存缓存。无 `bpy.app.timers` 的宿主自动退化为同步执行。
- 新增 `tests/test_pack_detect.py`、`tests/test_pack_type_autodetect.py`，以及设计文档 `docs/packs/pack_type_detection.md`。
- 「默认材质替换设置」（Pack Textures / Connected Textures / Animated Textures）从「资源包与基础包」选项卡迁移到「材质与着色」选项卡；资源包页仅保留堆栈缓存维护按钮，避免同一组开关出现在两处。
- 新增包条目改为插入列表**最顶部**（最高优先级）并自动选中，不再追加到同层末尾，与 Minecraft 原版「新包覆盖其下所有包」的堆叠模型一致；检测出为原版/模组后仍按三层规则自动归位。

### 🧪 CI 与发布校验修复
- 修复 `blender_manifest.toml` 的 `tagline` 超过 Blender 扩展规范 64 字符上限，导致 `build.py --validate-only` 与发布构建失败；`bl_info.description` 同步收敛为同一文案。
- `compute_flat_material_props_buffer` / `compute_flat_material_props_paletted_buffer` 在旧版 `libmtk_py` 缺少 memoryview 入口时不再静默返回全零，而是回退到列表 API（paletted 路径展开为逐面 key），保留 emission / thin wall / transmission 等物理属性。
- CI 移除无效的 `Swatinem/rust-cache`：MoziToolKit 仓库没有 `Cargo.toml`，该 action 的 `cargo metadata` 探测会以 101 退出；Rust 工具链仍保留，用于 `ci-latest` wheel 不可用时的源码回退构建。
- 材质属性测试显式加载 `configs/material_properties.json`，不再依赖前序测试留下的全局注册表状态。

### 🌍 3D World Biome 预设与面板显示修复
- **修复 WORLD → 其他预设 → WORLD 后草方块永久失去染色**：Live Sync 网格此前为省内存跳过逐面 `mtk_source_texture_key`，但调色板注入也藏在该字符串分支里，导致网格既没有字符串也没有 `mtk_source_textures` + `mtk_source_texture_idx`；Biome 重算只能从 Atlas Chunk 材质名反推来源，把所有面的 tint type 写成 `0`。现在来源贴图统一为 palette 契约：Rust 新增 `MeshData.source_texture_palette_indices()`，`inject_custom_attributes` 无论 `skip_string_attributes` 取值都会写入调色板 + INT 索引，逐面字符串仅保留为 ≤256 面的兼容层。存档导入与 Live Sync 的属性集合因此完全一致。
- 删除“从 Atlas Chunk 材质名推导来源键”的破坏性回退；当网格没有任何真实 provenance 时拒绝覆盖 tint，避免旧文件被二次写坏。
- 存档导入、Live Sync 与体素重建现在统一写入 `mtk:biome_preset="WORLD"`，并把 `VoxelStorage` 缓存到内存注册表；修复实时同步完成后生物群系面板回落 Plains、与网格真实 3D 群系染色不一致的问题。
- 生物群系面板在对象缺少预设属性时会根据 `mtk:geometry_origin`（`SAVE` / `SYNC_WORLD` / `SYNC_SECTION` / `VOXEL`）与 `mtk_biome_tint_data` 推断 `WORLD`，兼容旧 `.blend`；外部导入网格仍保持 Plains 默认。
- `WORLD` 不再复用 Plains 的温度/草地/树叶信息行，改为显示真实的逐面 3D 采样说明，避免“下拉框是 World Biome、数值却是 Plains”的误导。
- **从伴生点云恢复 WORLD**：内存缓存失效后（重开 `.blend`、Live Sync 断开且无存档），重新选择 `WORLD` 会从 `.blend` 内持久化的体素点云重建 `VoxelStorage`（保留逐体素 3D biome），存档导入与实时同步离线场景均可恢复，不再需要重读 `.mca`。
- 无 storage 且 tint 属性已被统一预设覆盖时，拒绝把对象伪标为 `WORLD`，避免把 Plains 颜色静默当成 3D 群系颜色；没有 biome 数据的旧点云也不会被当成 Plains 静默回填。
- 修复 Live Sync storage 回退调用了不存在的 `get_live_sync_session` 的死代码，改为使用 `get_sync_bridge_session()` 的活跃会话。

### 🧭 材质替换与网格重构边界收紧
- 新增 `mtk:geometry_origin` 网格来源标记（`EXTERNAL` / `SAVE` / `SYNC_WORLD` / `SYNC_SECTION` / `VOXEL` / `POINT_CLOUD`），在存档导入、Live Sync 世界网格与独立体素网格创建时写入；旧文件按 `mtk:is_save_mesh`、`mtk:is_yefira_mesh`、`mtk:is_section_mesh`、`mtk_is_voxel_cloud` 与命名约定回退推断。
- **替换材质仅对外部导入网格可用**：MTK 生成的网格（存档 / Live Sync / 体素）在右键菜单与 Voxel & Mesh Tools 面板中自动置灰，并显示“请编辑点云后重建”的上下文提示。
- **重建体素网格收紧来源要求**：存档容器与离线 Live Sync 必须存在伴生体素点云；活跃 Live Sync 会话仍可直接从内存 storage 重建，无需等待点云；仅有材质来源属性（provenance）的外部网格不再被误判为可重建对象。
- 修复存档复用已有网格时未补齐 `mtk:is_save_mesh` 标记的问题，并同步写入来源标记。

### 🧵 外部网格多 UV 与无损重贴
- 外部导入网格首次替换材质时保留原始 `UVMap`，新建 `MTK_Atlas` 并自动切换为活动/渲染 UV；Atlas 材质只引用 `MTK_Atlas`，原始 local UV 不再被覆盖。
- 新增 `mtk:local_uv_layer` / `mtk:atlas_uv_layer` / `mtk:atlas_layout_hash` 网格属性。布局哈希只覆盖 UV 相关字段（sprite `uv_bounds`、atlas 路由、chunk 几何），贴图像素变化不会使 UV 失效。
- **复用优先**：图集布局未变化时直接复用现有 `MTK_Atlas` UV，仅重绑材质/重载贴图；布局变化时才从保留的 local UV 重新映射。`Reuse Atlas UVs` 开关可强制重贴。
- **不再支持旧版单 UV atlas 网格**：这类网格的 local UV 已被历史版本覆盖，Replace 会明确拒绝并提示重新导入，避免用错误 UV 静默重贴。
- 材质新增 `mtk_uv_map_name` 校验，旧材质在 UV Map 名称变化时自动重建 UV Map 节点，避免继续采样错误的 UV 层。
- 外部网格的 Atlas 材质使用独立命名空间 `MTK:Atlas:Ext:*`，避免与 MTK 网格共享的 `MTK:Atlas:*` 材质因 UV Map 名称不同而互相覆盖。
- 新增 `tests/test_uv_layers.py` 与 Blender 宿主多 UV 回归测试。

### 🧹 旧机制清理
- **移除公开的 `Restore Materials from Attributes` 算子**：外部网格的材质修复统一走 `Replace Material`（同布局复用 / 布局变化重贴），MTK 网格统一走 `Rebuild Voxel Mesh`。
- **移除 Rebuild 的 `ATTRIBUTES`（仅 provenance）分支**：没有体素源的外部网格不再出现在 Rebuild。
- **移除单 UV atlas-only 兼容路径**：不再自动识别/复用旧版 atlas UV，也不再为旧网格做包指纹兜底。
- 同步移除菜单注册表、配置归一化与 i18n 中的旧 Restore 条目。

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

### 🧹 代码库与文档清理
- 删除陈旧兼容层：`operators/op_mesh.py`、`utils/extrude_repair/`、
  `utils/mesh/subdivide.py`，以及 `ui/panel_voxel_storage.py` / `ui/panel_sync.py` /
  `operators/op_materials.py` 中的旧类名别名。
- 删除 `inject_face_materials_dna` 死分支；`material_index` 统一走标准 RNA 写入。
- 删除废弃 Live Sync API：`send_full_sync_request` / `send_repair_request` /
  `send_sync_config` / `export_manifest` / `import_manifest` 及旧 `cached_*` 启动参数；
  统一使用 `cached_state_json`。
- 删除 Python 侧旧 list-based 材质提取/重映射路径，只保留 palette-native 管线。
- 简化 `bridge/assets/cache.py` 的旧 glob/direct 搜索，保留 Rust resolver 与测试沙箱 fallback。
- 修复 `docs/` 下 41 处死链至 0，重写失效的 Step Pipeline 文档为当前
  `AsyncTask` / `ModalTaskRunner` 架构。

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
