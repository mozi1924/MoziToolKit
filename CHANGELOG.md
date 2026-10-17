# Changelog

All notable changes to the **MoziToolKit** extension will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

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
