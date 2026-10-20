# B0 基线与 Blender 冒烟报告

日期：2026-10-20  
分支：`refactor/2.0-b0-baseline`  
Blender：5.2.1 LTS  
Addon：2.0.0

## 1. 机器可读快照

- [`tests/fixtures/b0_operators.json`](../../tests/fixtures/b0_operators.json) — `get_all_operators()` 的 12 个公开 ID。
- [`tests/fixtures/b0_blender_smoke.json`](../../tests/fixtures/b0_blender_smoke.json) — 注册、右键菜单、debug world、carving remesh 的逐项结果。
- [`tests/fixtures/b0_native_api.json`](../../tests/fixtures/b0_native_api.json) — `libmtk_py` + `libmtk_blender_dna` API 表面与禁用符号检查。

重新生成：

```bash
cd /Volumes/Data/mtk/MoziToolKit

# Native API snapshot
../libmozitoolkit/.venv/bin/python tools/b0_native_snapshot.py

# Blender registration / menu / debug world / carving smoke
MTK_TEST_SITE_PACKAGES=/tmp/mtk-blender-site \
  /Applications/Blender.app/Contents/MacOS/blender \
  --background --python tools/b0_blender_smoke.py

# Retired symbol guard
python3 tools/check_legacy_symbols.py
```

## 2. Blender 冒烟结果

| 检查 | 结果 |
|---|---|
| 插件注册，无异常 | ✅ |
| `mozi.rebuild_mesh` 已注册 | ✅ |
| 对象模式右键菜单非空 | ✅ 5 项 |
| 网格编辑模式右键菜单非空 | ✅ 11 项 |
| 菜单只包含已注册算子 | ✅ |
| 两个菜单都保留 `Rebuild Voxel Mesh` | ✅ |
| 菜单不含内部/已删除算子 | ✅ |
| 空 `MOZI_MT_select_uv_menu` 不存在 | ✅ |
| Preferences 可用算子不含内部 ID | ✅ |
| Debug world 生成网格 | ✅ 385 voxels / 5,448 verts / 4,066 polys |
| 点云雕刻后 `Rebuild Voxel Mesh` | ✅ 54 → 60 polygons，空腔暴露 |
| 操作符返回 | `{"FINISHED"}` |

右键菜单快照：

```text
object: rebuild_mesh, replace_material, toggle_voxel_cloud,
        clear_custom_normals, set_texture_interpolation_closest

mesh:   adaptive_pixel_split, replace_material, rebuild_mesh,
        toggle_voxel_cloud, auto_extrude_repair, random_extrude,
        select_hard_edges, select_transparent_faces, repair_fluid_uv,
        clear_custom_normals, set_texture_interpolation_closest
```

## 3. 原生 API 快照

- `libmtk_py.version() = 0.1.0`
- `libmtk_py.api_version() = 1`
- `libmtk_blender_dna.api_version() = 1`
- `libmtk_py.unstable.blender_dna` 不存在
- `MeshData.from_flat_polygons` 存在
- 禁用符号 `SectionMesher` / `process_mesh` / `direct_copy_*` / `from_arrays` /
  `get_block_states` / `get_biomes` 均不在公开 API
- `libmtk_blender_dna` 只暴露 `copy_f32` / `copy_i32` / `copy_u32` / `copy_u8`

## 4. 零残留扫描

`tools/check_legacy_symbols.py` 扫描两个仓库的 715 个代码/配置文件：

```text
0 violations
29 allowed hits
```

允许项只有：

- `mtk-core` 内部合法的 nested extrude 实现
- `mtk-voxel` / `mtk-wasm` / `mtk-bench` 内部 `SectionMesher`
- 导入面板和 i18n 中的 `DIM-1` / `DIM1` 展示文案

## 5. 自动化基线

- Python：**274 passed / 70 skipped / 6 subtests**
- Blender 5.2.1：**335 passed / 10 skipped / 6 subtests**
- Rust workspace：**全部通过**
- `cargo fmt --all -- --check`：通过
- `cargo clippy --workspace --all-targets -- -D warnings`：通过
- `cargo check -p mtk-wasm --target wasm32-unknown-unknown`：通过

## 6. 结论

B0 的注册、右键菜单、debug world、雕刻空腔重建、原生 API 快照和零残留扫描均已闭环。
后续批次如果重新引入旧符号，`tools/check_legacy_symbols.py` 会直接失败。
