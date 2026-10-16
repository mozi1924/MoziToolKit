# Changelog

All notable changes to the **MoziToolKit** extension will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
