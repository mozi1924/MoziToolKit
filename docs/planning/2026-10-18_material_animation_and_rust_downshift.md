# 2026-10-18 工作清单：外部网格动画材质修正 + 胶水层逻辑下沉

> 状态：**P0 动画材质修复已完成；第一批 Host-Agnostic 下沉已完成；剩余迁移项待排期。**
> 本次改动跨越 `MoziToolKit`（Blender 前端）与 `libmozitoolkit`（Rust 核心），两个仓库需分别提交。

---

## 1. 结论先行

### 1.1 外部网格动画材质失效（已修复）

根因不是 shader，也不是偏好设置没读到，而是**外部网格材质替换链路从来没有把“动画开启”传进 Rust 路由**：

1. `bridge/material.py::remap_mesh_multi_uvs` 没有 `enable_animated_textures` 参数；
2. Rust `remap_single_face_multi_uvs` 使用 `MaterialResolver::resolve` → `AtlasAddressMap::lookup`，
   该查找**静态 Frame 0 优先**，`anim_sprites` 永远排在后面；
3. 因此 `face_chunk_ids` 始终是静态 chunk，`assign_atlas_chunk_materials` 自然只会创建
   `MTK:Atlas:blocks:001`，不会创建 `MTK:Atlas:blocks:anim:001`；
4. 即使强行创建了动画材质，外部网格也**没有注入** `mtk_anim_timing` /
   `mtk_anim_frame_size` 两个 face 属性，`MC_Animation_Scheduler_Default` 只能拿到 0，
   表现为“动画材质节点在，但时间线不播放”。

修复方式（保持 v2.0 frozen 的兼容性，新增 API 而不是改旧签名）：

- `mtk-material` 新增统一动画路由策略 `resolve_animated_sprite` / `resolve_routed_sprite`，
  voxel mesher 与外部网格 remapper 共用同一套 static/anim 选择逻辑；
- 新增 `remap_mesh_multi_uvs_parallel_with_options(..., enable_animated_textures)`，
  旧函数保持静态 Frame 0 行为；
- 返回值新增 `face_is_animated` / `face_anim_timing` / `face_anim_frame_size`；
- 新增 `resolve_mesh_material_routes`（仅路由，不碰 UV）与
  `reroute_mesh_animation`（把已有 Atlas UV 从旧 sprite 反解并投影到新 sprite）；
- Python `replace_materials` 读取 `prefs.enable_animated_textures` 并注入全部动画属性；
- Python restore 路径新增 `reconcile_animation`：切换偏好后不必重新导入网格，
  也能把静态 chunk 与动画 chunk 双向重路由，且不依赖已经丢失的原始局部 UV；
- 修复 `face_source_keys` 只从 `sprites` 建表、不包含 `anim_sprites` 的问题
  （否则动画面的 provenance 会退化成 `mozi:fallback`，后续 restore 无法再解析）。

### 1.2 胶水层下沉（第一批已完成）

本次优先把**跨 DCC 可复用、且含有领域规则**的逻辑移入 Rust，而不是移动 Blender 专用对象装配：

| 逻辑 | 原位置 | 新位置 | 价值 |
| :--- | :--- | :--- | :--- |
| static/anim 图集路由 + 动画元数据 | Python/Rust 各一份 | `mtk-material::resolver` | C4D/其他宿主复用，避免两套策略漂移 |
| 外部网格动画重路由 | 无（缺失） | `mtk-material::remap::routes` | 不依赖原始 UV，可幂等切换 |
| Live Sync 持久化状态 schema | `op_sync_connect.py` 手写 UUID/hex/bounds 解析 | `mtk-sync::PersistedSessionState` | JSON 进出，宿主只存字符串 |
| 两阶段进度归一化 | `op_sync_connect.py` 50/50 手算 | `mtk-sync::normalize_stream_progress` | 修正 meshing 阶段被二次加 50 的 bug |
| 握手 decision 语义 | Python 拿字符串和 `0` 比较（永不成立） | `SyncEvent::Handshake.decision_code` | 0ms reconnect 分支可被正确识别 |

---

## 2. 已完成清单

### 2.1 Rust

- [x] `crates/mtk-material/src/resolver/mod.rs`
  - `resolve_animated_sprite`：raw → parsed → cleaned → alias → canonical resolver 五级动画查找；
  - `resolve_routed_sprite`：按 `enable_animated_textures` 选择 static/anim；
  - `extract_animation_metrics`：统一输出 `[frames, frametime, interpolate]` 与 `[w, h, 0]`。
- [x] `crates/mtk-material/src/remap/batch.rs`
  - `remap_mesh_multi_uvs_parallel_with_options`；
  - 结果新增 `face_is_animated` / `face_anim_timing` / `face_anim_frame_size`；
  - 旧 `remap_mesh_multi_uvs_parallel` 保持静态行为。
- [x] `crates/mtk-material/src/remap/routes.rs`
  - `resolve_mesh_material_routes`；
  - `reroute_mesh_animation`：旧 sprite 反解 → 新 sprite 投影，无法定位旧 sprite 时保留 UV 并计数。
- [x] `crates/mtk-voxel/src/mesher/shading/anim.rs`
  - 删除本地重复实现，改为委托 `mtk-material`（避免 mesher 与外部网格两套动画策略）。
- [x] `crates/mtk-sync/src/events.rs`
  - `Handshake.decision_code`；
  - `normalize_stream_progress`（download 0–50，meshing 50–100，不再二次加 50）。
- [x] `crates/mtk-sync/src/session/persisted.rs`
  - `PersistedSessionState` JSON 序列化/反序列化；
  - UUID hex 解码、HELLO 构造、`user_modified` 失效逻辑；
  - `export_persisted_state_json` / `start_with_persisted_state_json`；
  - 单元测试覆盖 roundtrip、HELLO、user_modified。
- [x] `bindings/mtk-py`
  - `MaterialResolver.remap_mesh_multi_uvs(..., enable_animated_textures=False)`；
  - `MaterialResolver.resolve_mesh_routes` / `reroute_mesh_animation`；
  - `LiveSyncSession.export_persisted_state_json` / `start_with_persisted_state`；
  - `STREAM_PROGRESS.percent` 改为 Rust 归一化值；`HANDSHAKE.decision_code` 透传。

### 2.2 Blender / Python

- [x] `bridge/material.py`
  - 新增 `resolve_mesh_material_routes`、`reroute_mesh_animation` 封装；
  - `remap_mesh_multi_uvs` 新增动画开关。
- [x] `utils/materials/pipeline.py`
  - `animated_textures_enabled(prefs)`；
  - `replace_materials` 读取偏好并注入动画属性；
  - `inject_mesh_provenance_attributes` 注入 `mtk_anim_timing`、`mtk_anim_frame_size`
    以及 `mtk_anim_total_frames` / `frametime` / `interpolate` / `frame_width` / `frame_height`；
  - `assign_atlas_chunk_materials` 现在会因动画 chunk 创建 `MTK:Atlas:*:anim:*`；
  - `restore_materials_from_provenance(..., reconcile_animation=..., enable_animated_textures=...)`
    支持静态/动画双向重路由并回写 UV；
  - `face_source_keys` 同时索引 `sprites` 与 `anim_sprites`。
- [x] `operators/op_materials.py`
  - 根据 `mtk_enable_animated_textures` 标记与当前偏好决定是否需要 reconcile；
  - 显式 Restore 操作符同样遵循该规则。
- [x] `bridge/sync.py`
  - `start(..., cached_state_json=...)`，优先调用 Rust 持久化状态入口；
  - `export_persisted_state_json()`。
- [x] `operators/sync/hierarchy.py`
  - 只负责把 Rust 返回的 JSON 字符串写入/读出 root container 自定义属性；
  - 删除 Python 侧 UUID/hex/bounds 解析。
- [x] `operators/sync/op_sync_connect.py`
  - 连接直接传递 `cached_state_json`；
  - 进度使用 Rust `percent`；
  - 握手使用 `decision_code`；
  - 世界网格就绪后持久化 Rust 状态 JSON。
- [x] 测试
  - Rust：`test_animated_routing_toggle_and_metrics`、`test_resolve_routes_and_reroute_animation`、
    `progress_phases_are_normalized_without_double_weighting`、
    `persisted_state_roundtrip_and_hello`、`user_modified_state_is_not_a_reconnect_candidate`；
  - Blender：`tests/test_external_material_animation.py` 覆盖 开→关→开 的完整 replace/restore 循环，
    以及关闭动画时的静态基线。

---

### 2.3 P1 Biome 即时更新下沉（✅ 本轮完成）

- [x] `mtk-material::biome::reapply_uniform_biome_tint_flat`：
  - 输入 `base_tint_types`、现有 packed tint data、旧 hardcoded 颜色、目标群系颜色；
  - Rayon 并行输出扁平 `packed_tint_data` / `tint_colors` / `colormap_uvs`；
  - 自定义 grass/foliage/dry 覆盖仍按原语义路由到 `TINT_TYPE_HARDCODED`，但保留新颜色。
- [x] PyO3 `reapply_uniform_biome_tint`：
  - 接受 C-contiguous `uint8` / `float32` buffer；
  - 返回 3 个零拷贝 memoryview（Rust 持有 Vec）；
  - Python 直接 `foreach_set`，没有逐面 Python 对象。
- [x] `utils/materials/biome/updater.py`：
  - fast path 改为 Rust 计算；
  - 仅当存在 `TINT_TYPE_HARDCODED` 面时才读取旧颜色；
  - 属性写入仍用 `foreach_set`（实测与 DNA 等价，见 §2.4）。
- [x] 实测（Blender 5.2.1，498,436 faces）：
  - 原 Python 快速路径：**6.3–8.0 ms**
  - 新 Rust 路径：**~2.1 ms**（约 3 倍）

### 2.4 DNA vs `foreach_set` 实测结论

- 500k faces、3 个 face 属性：
  - `foreach_set` 0.53 ms；
  - DNA `copy_buffer_to_ptr` 0.52 ms；
  - **没有可测性能差异**。
- DNA 直写后 evaluated mesh 仍是旧值，必须显式 `mesh.update()`；
  `foreach_set` 会自动标记更新。
- 结论：DNA 继续用于拓扑/位置/法线/UV/顶点色/点云；通用 face 属性继续
  `foreach_set`；即时 Biome 的收益来自 **Rust 并行计算 + 扁平 buffer**，不是 DNA。
- 详细基准与适用范围见 [`docs/mesh/direct_mesh.md`](../mesh/direct_mesh.md) §7。

---

## 3. 剩余待办（按优先级）

### P1 — 外部网格材质提取批量化（部分完成，剩余 palette-native 改造）

`utils/materials/pipeline.py::extract_face_material_context` 原先逐 polygon 读取
`poly.material_index` / `loop_start` / `loop_total`，并逐面拼 `clean_keys`。

本轮已完成：

- [x] `extract_face_material_context` 改为 `foreach_get` + NumPy object-array 索引；
  159k faces 从 **0.317 s → 0.050 s**。
- [x] `face_source_keys` 改为 texture-id → key 稠密表 + NumPy 索引；
- [x] `inject_mesh_provenance_attributes` 删除逐面 `clean_keys` decode/str 循环；
- [x] `compute_flat_material_props_memoryview`：Rust 直接返回零拷贝 memoryview，
  `inject_face_attribute_float4` 识别 buffer，不再 `np.ascontiguousarray` 复制；
- [x] UV transform 由 Python 逐面 `extend` 改为 `np.asarray(...).ravel()`；
- [x] 500k faces 外部 replace 实测 **2.65 s → 1.70–1.85 s**（约 1.5 倍）。

仍待完成：

- [ ] **palette-native remap**：`face_materials` 仍以 `Vec<String>` 传入 Rust，
  且 `face_texture_ids` / `face_chunk_ids` 仍以 Python list 返回；应改为
  `palette + u32 indices`，避免每面字符串与 list 转换。
- [ ] `compute_biome_tint_attributes` 增加 palette 版本，避免逐面 `Vec<String>`。
- [ ] `face_chunk_ids` / `face_texture_ids` 以 memoryview 返回，直接喂给 `foreach_set`。
- [ ] 目标：1M faces 外部 replace < 1.2 s（当前 500k ~1.7 s，尚未达标）。

### P2 — Live Sync 事件合并/代际栅栏下沉

`_sync_timer_tick` 目前仍在 Python 侧做：

- `WORLD_MESH_READY` 只保留最新 generation；
- 与 container 上 `mtk:client_generation` 比较并丢弃 stale mesh；
- 点云 sparse/storage 安全屏障。

建议：

- [ ] `LiveSyncSession::poll_latest_world_mesh()` 或在 `poll_events` 内合并旧 generation，
      只向宿主交付最新 mesh；
- [ ] 事件批量结构体 `SyncEventBatch { events, latest_world_mesh, latest_generation }`，
      宿主一次轮询即可拿到“状态事件 + 最新网格”；
- [ ] Python 只保留 UI 文案与 Blender 对象注入。

### P2 — 资产缓存解析下沉

`bridge/assets/cache.py` 的 `get_active_cache_package_path` 仍包含指纹匹配、glob、mtime、
测试沙箱 fallback 等策略。C4D 需要同样的 `.mtkcache` 选择逻辑。

- [ ] `mtk-package::CacheResolver::resolve(cache_dir, fingerprint) -> Option<PathBuf>`；
- [ ] PyO3 暴露 `AssetCache.resolve_active`；
- [ ] Python 只负责读取 prefs 并传入 cache_dir/fingerprint；
- [ ] 保留 `MOZI_CACHE_DIR` 测试隔离语义在宿主侧。

### P2 — C-ABI / C4D 导出面

本次新增的 Rust API 目前只通过 PyO3 暴露；C4D 若走 C++/C-ABI，需要：

- [ ] `bindings/mtk-ffi` 增加 `MtkMaterialRoute` / `mtk_resolve_mesh_material_routes`；
- [ ] `mtk_sync_export_persisted_state_json` / `mtk_sync_start_with_state`；
- [ ] 在 `bindings/mtk-ffi/README.md` 更新函数表与调用示例。

### P3 — 文档/一致性

- [ ] `mtk-material/README.md` 公共 API 表补新函数；
- [ ] `mtk-sync/README.md` 补 `PersistedSessionState` 与 `decision_code`；
- [ ] `bindings/mtk-py/README.md` 补新 PyO3 方法；
- [ ] 评估是否为旧场景做 `mtk_sync_server_uuid` → `mtk_sync_state_json` 迁移；
      当前旧属性不再参与快速重连，旧场景会自动走全量基线（安全但慢一次）。

---

## 4. 验证记录（2026-10-18）

### Rust

```bash
cd libmozitoolkit
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
cargo build-py
```

结果：fmt / clippy 通过；workspace tests 全部通过；`libmtk_py` release 构建成功。

### Python Mock

```bash
cd MoziToolKit
../libmozitoolkit/.venv/bin/python -m pytest tests/ -q
```

结果：**241 passed / 71 skipped**（新增 Blender-only 用例在 mock 下 skip）。

### Blender 5.2.1 LTS

```bash
BLENDER_USER_CONFIG="$PWD/.blender-test-config" \
MTK_TEST_SITE_PACKAGES="$(../libmozitoolkit/.venv/bin/python -c 'import site; print(site.getsitepackages()[0])')" \
  blender --background --factory-startup --python tests/run_tests.py -- -q
```

结果：**302 passed / 10 skipped**（修复了 3 个已知的 sync timer 隔离失败与
`tests/test_mesh_ownership.py` 中 5 个 `root.children = [...]` 非法赋值 / fake datablock
造成的测试自身失败）。

### 手工验收（建议在真实资源包下再跑一次）

1. 导入外部 OBJ/FBX（材质名 `water_still` / `lava_still` / `fire`）；
2. Preferences 开启 Animated Textures → Replace Material；
3. 期望：材质 `MTK:Atlas:blocks:anim:001`，`mtk_anim_timing` 的 X > 1，时间线播放；
4. 关闭偏好 → Replace Material（或 Restore）→ 期望：`MTK:Atlas:blocks:001`，
   `mtk_anim_timing` 回落 `[1,1,0]`，视口无动画开销；
5. 再开启 → Restore → 期望恢复动画材质与 UV，无需重新导入。

---

## 5. 风险与注意事项

- **旧场景快速重连**：持久化属性 schema 从多个 `mtk_sync_*` 属性收敛为
  `mtk_sync_state_json`。旧场景没有该属性时会走全量基线（正确但慢一次）；
  如用户反馈需要，可加一次迁移。
- **`mtk-material` 公共结构体新增字段**：`MeshMultiUvRemapResult` 增加 3 个字段，
  对 Rust 下游的结构体字面量构造是编译期破坏；本次按 v2.1 加法处理，Blender 端已同步。
- **restore 重路由依赖旧 chunk 属性**：若第三方工具清除了 `mtk_atlas_chunk_id`，
  旧 sprite 可能无法定位，UV 会保留并计入 `uv_unmapped_faces`（不会崩溃）。
- **并行开发**：`MoziToolKit` 工作树中仍有 mesh ownership / rebuild 相关的未提交改动；
  提交时请按主题拆分，不要把本次材质/同步改动混进 ownership 提交。
