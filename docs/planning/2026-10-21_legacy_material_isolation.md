# 2026-10-21 旧材质实现隔离与删除计划

> 状态：**草案，待评审**。确认后再拆分到具体版本任务。
> 基线：`MoziToolKit@aa7fcbe`、`libmozitoolkit@df06886`（canonical PBR 路径已提交）。
> 范围：`MoziToolKit`（Blender 前端）与 `libmozitoolkit`（Rust 核心）两个仓库。
> 前提：新 `MtkPackedV1` 路径已上线；没有已知第三方消费者；旧 `.blend` 里的
> `LabPBR 1.3 Decoder` 是**嵌入的 node group datablock**，删除 Python 生成器不会让它失效。

---

## 1. 结论

1. **隔离边界**：
   - Python：`utils/legacy/materials/`，只允许迁移器、旧 `.blend` 兼容和 legacy 测试导入。
   - Rust：`mtk-material` 的 `legacy-material` feature；v2.2 默认开启，v3.0 默认关闭并删除。
2. **v2.2 只做三件事**：停止写入、停止消费、隔离 + 迁移器。新路径不改。
3. **v3.0 删除代码/数据/API**，而不是继续保留 shim。
4. **旧 `.blend` 的兼容策略**：嵌入的 decoder 仍然能渲染；我们只删除“重新生成/迁移”的能力。
   生成型 atlas 材质通过 provenance 重建；用户手改过的材质保留嵌入组，并给出明确提示。
5. **旧网格/旧配置**：`mtk_material_props` / `mtk_emission` 变成惰性数据，不影响渲染；
   旧配置里的未知字段被忽略；旧 `.mtkcache` 因 `ASSET_CACHE_FORMAT_VERSION = 4` 自动失效。

---

## 2. 现状盘点

### 2.1 已经在新路径上的

- `mtk-material::pbr`：LabPBR 解码、`_n` / `_orm` / `_aux`、`PbrMeta`。
- `ASSET_CACHE_FORMAT_VERSION = 4`，预编译期解码并丢弃 raw `_n` / `_s`。
- Blender 端 `pbr_graph.py` + `atlas_builder.py` 只消费标准 Principled。
- `has_orm` / `has_aux` / `pbr` 元数据、`uv_layers` layout hash。
- 逐面游戏语义已从材质图、Python 配置和 UI 中移除。

### 2.2 仍然存在的旧面

| # | 组件 | 位置 | 当前消费者 | v2.2 动作 | v3.0 动作 |
| :- | :--- | :--- | :--- | :--- | :--- |
| L1 | LabPBR 解码器生成器 | `utils/node_groups/labpbr.py` | legacy 测试、旧 `.blend` 迁移 | 移到 `utils/legacy/materials/labpbr_decoder.py`；`node_groups/labpbr.py` 仅 re-export | 删除 re-export 与原文件 |
| L2 | 解码器形状契约常量/断言 | 同 L1 | 旧测试 | 随 L1 移入 legacy；测试移到 `tests/legacy/` | 删除 |
| L3 | `mtk_material_props` Python 注入/API | `bridge/material.py`、`bridge/__init__.py`、`utils/materials/__init__.py` | 旧测试、`b0_native_api` fixture | 标记 deprecated；fixture 分组到 legacy | 删除 `compute_*_material_props*`、`get_material_props` |
| L4 | `mtk_material_props` Rust 字段/写入 | `mtk-core` `FaceAttributes.material_props`、`mesh/attributes.rs`、`mtk-voxel` shading、`mtk-model` `to_mesh.rs` | Rust 网格化运行时 | **停止调用 `get_material_props`**，字段先填默认值；去掉运行时开销 | 删除字段、常量、写入与相关测试 |
| L5 | `mtk_emission` 属性/写入 | `mtk-core` `ATTR_EMISSION`、`FaceAttributes.emission`、`mtk-model`/`mtk-voxel` | redstone 烘焙测试 | 保留（红石仍有真实用途），材质不再消费 | 评估后删除或降级为纯几何属性 |
| L6 | Rust 材质物理属性注册表 | `mtk-material/src/properties/`、`assets/material_properties.json` | L4/L5、`mtk-py` catalog API | 移到 `mtk-material/src/legacy/properties/`，`legacy-material` feature 默认开 | 删除模块、asset、feature |
| L7 | Python 外部属性配置 | `utils/materials/properties_config.py`、`configs/material_properties.json`、`__init__.py` 启动加载 | 启动时注册到 Rust、legacy 测试 | 移到 `utils/legacy/materials/`；**移除启动时自动加载** | 删除模块与 JSON |
| L8 | 渲染引擎适配 no-op | `utils/materials/builder/adaptation.py`、`__init__.py`、`ui/preferences.py`、`tests/test_realtime_engine_adaptation.py` | 启停 handler、偏好变更回调 | 删除（已无实际适配） | — |
| L9 | 旧缓存 raw 字段/访问器 | `BakedAtlasChunk.normal/specular`、`get_chunk_specular_f32` | 旧 in-memory 路径、mtk-py | 标记 deprecated；保留一个版本 | 删除 raw 字段与 specular 访问器；`get_chunk_normal_f32` 改名 `get_chunk_normal_gl_f32` |
| L10 | 旧配置字段 | `MaterialSettings` 的 `enable_game_semantics` / `transmission_mode` / `thin_wall_mode` | 旧 JSON | 已移除；`from_dict` 忽略未知键 | 删除文档/迁移说明中的最后引用 |
| L11 | Legacy 测试/fixture | `tests/test_labpbr_emission_and_thinwall.py`、`tests/test_material_config_driven.py`、`b0_native_api.json` 条目 | 默认 CI | 移到 `tests/legacy/` + `@pytest.mark.legacy` | 删除 |
| L12 | 旧文档 | `material_pipeline.md` 旧段、`docs/README` legacy 行 | 文档 | 标注 “legacy / 仅迁移参考” | 删除或归档 |

---

## 3. 隔离架构

### 3.1 Python

```text
MoziToolKit/
├── utils/materials/                  # 活跃路径，禁止 import legacy
├── utils/node_groups/                # 活跃节点组
└── utils/legacy/
    └── materials/
        ├── __init__.py
        ├── labpbr_decoder.py         # 从 node_groups/labpbr.py 迁移
        ├── properties_config.py      # 从 utils/materials/ 迁移
        ├── material_props_api.py     # bridge 的 deprecated 薄封装
        └── migrate.py                # 检测/升级旧材质
```

- `utils/node_groups/labpbr.py` 在 v2.2 只保留：
  ```python
  from ..legacy.materials.labpbr_decoder import *  # noqa: F401,F403
  ```
  v3.0 直接删除该文件。
- 活跃模块（`utils/materials/builder/*`、`utils/node_groups/__init__.py` 等）**不得**导入
  `utils.legacy.*`。新增 `tests/test_legacy_boundaries.py` 静态检查。
- 旧 API 的 `bridge/material.py` 包装保留函数名，但内部委托到 legacy 模块；v3.0 删除函数与
  `bridge/__init__.py` / `utils/materials/__init__.py` 的导出。

### 3.2 Rust

```text
libmozitoolkit/
├── crates/mtk-material/src/pbr/      # 活跃
└── crates/mtk-material/src/legacy/
    └── properties/                   # 从 src/properties/ 迁移
```

- `mtk-material/Cargo.toml`：
  ```toml
  [features]
  default = ["parallel", "zip", "legacy-material"]
  legacy-material = []
  ```
- v2.2：`lib.rs` 的 `pub mod legacy;` 与 re-export 受 `#[cfg(feature = "legacy-material")]` 保护；
  `mtk-voxel` / `mtk-model` 不再调用 `mtk_material::properties`，`FaceAttributes.material_props`
  先填默认值，运行时不再查属性表。
- v3.0：删除 `legacy` 模块、feature、`mtk-py` 的 catalog 函数，以及 `mtk-core` 的字段/常量。
- CI 增加 `cargo check/test --no-default-features --features legacy-material` 与
  “clean” 配置（不带 legacy）两套。

### 3.3 运行时开关

- Python：`MTK_ENABLE_LEGACY_MATERIALS`（环境变量，v2.2 默认 `1`，v3.0 默认 `0`）。
  - 关闭时：不 import `utils.legacy.materials`；旧材质检测返回清晰错误；
    嵌入的 decoder 仍可渲染，但迁移器不可用。
- Rust：`legacy-material` feature。v2.2 默认开，v3.0 默认关并删除。
- 两者都不影响新材质路径。

### 3.4 迁移器

新增 `utils/legacy/materials/migrate.py`：

1. `load_post` 扫描材质，统计带 `LabPBR Decoder` 节点的材质，写入场景/面板提示。
2. 操作符 `mozi.migrate_legacy_materials`：
   - `MTK:Atlas*` + `mtk_atlas_chunk_id` 且缓存有效 → 用
     `restore_materials_from_provenance` / `build_atlas_chunk_material` 重建为标准 PBR。
   - 用户手改过的材质 → 跳过，提示“保留嵌入 decoder；如需标准材质请手动重建”。
3. 迁移后写入 `mtk_pbr_layout = "mtk_packed_v1"`，不删除旧 node group datablock
   （由 Blender 的 orphan purge 处理）。
4. 可选：清理旧网格的 `mtk_material_props` 属性，减少存档体积。

---

## 4. 版本计划

### v2.1（当前提交）

- 新 canonical 路径生效；旧 decoder 保留，用于旧 `.blend` 和视觉回归 oracle。
- Rust 仍写入 `mtk_material_props`（惰性），Python 已不消费。
- `properties_config` 仍在启动时加载（供旧 catalog / `mtk_emission` 使用）。
- 视觉回归通过后，才能进入 v2.2 的删除阶段。

### v2.2（下一个清理版本）

1. `mtk-voxel` / `mtk-model` 停止 `get_material_props` 调用；`material_props` 填默认值。
2. 移除 `__init__.py` 启动时 `load_material_properties_config()`。
3. `labpbr.py` / `properties_config.py` / `adaptation.py` 移入 `utils/legacy/`；
   `adaptation.py` 直接删除（no-op，无迁移价值）。
4. 加 `tests/test_legacy_boundaries.py`、`MTK_ENABLE_LEGACY_MATERIALS`、`legacy-material` feature。
5. 加 `mozi.migrate_legacy_materials` 与旧材质检测；legacy 测试移到 `tests/legacy/`。
6. 文档标注 legacy；CHANGELOG 写 deprecation window。

### v3.0（彻底删除）

1. 删除 `utils/legacy/materials/labpbr_decoder.py`、`node_groups/labpbr.py`、legacy 测试。
2. 删除 Rust `legacy/properties`、`assets/material_properties.json`、`mtk-py` catalog 函数。
3. 删除 `FaceAttributes.material_props`、`ATTR_MATERIAL_PROPS`、相关 `mtk-voxel`/`mtk-model` 代码。
4. 评估并处理 `ATTR_EMISSION` / `FaceAttributes.emission`（红石测试是唯一已知消费者）。
5. 删除 `bridge/material.py` 的 `compute_*_material_props*` / `get_material_props` 及包导出。
6. 删除 `BakedAtlasChunk.normal/specular`、`get_chunk_specular_f32`；`get_chunk_normal_f32`
   改名 `get_chunk_normal_gl_f32`。
7. 删除 legacy feature/开关；清理文档与 fixture。

### v3.1（收尾）

- 清理旧 `.blend`/旧配置/旧 cache 的文档说明与测试 fixture。
- 只保留“旧 `.blend` 嵌入组仍可渲染”的说明，不再保留生成/迁移代码。

---

## 5. 验证清单

### 5.1 静态边界

```bash
cd MoziToolKit
rg "utils\.legacy|node_groups\.labpbr|builder\.adaptation" utils bridge operators ui \
  --glob '!utils/legacy/**'   # 必须为空
cd ../libmozitoolkit
rg "mtk_material::properties|legacy::properties" crates bindings \
  --glob '!crates/mtk-material/src/legacy/**'   # 必须为空（v3.0）
```

### 5.2 测试矩阵

- Rust：`cargo fmt --all -- --check`、`cargo clippy --workspace --all-targets -- -D warnings`、
  `cargo test --workspace`，分别在 `legacy-material` 开/关下跑。
- Python：`pytest tests/ -q`（默认）与 `MTK_ENABLE_LEGACY_MATERIALS=0 pytest tests/ -q`。
- Blender：旧-style 材质 fixture 加载 → 迁移 → 断言 `mtk_pbr_layout=mtk_packed_v1` 且无
  `LabPBR Decoder`；新材质回归不变。
- 视觉：保留 legacy decoder 直到 v3.0 前的最后一次 legacy-vs-baked 对比；v3.0 后以 Rust
  golden 测试 + 新材质渲染基线为准。

### 5.3 零残留检查

- `rg "LabPBR 1\.3 Decoder" MoziToolKit`：v3.0 只允许出现在文档/迁移说明。
- `rg "mtk_material_props"`：v3.0 只允许出现在文档/历史 CHANGELOG。
- `rg "get_material_props|compute_flat_material_props"`：v3.0 零命中（除 CHANGELOG）。

---

## 6. 风险与边界

1. **用户手改过的旧材质**：嵌入 decoder 仍可渲染，但我们无法自动推断用户的节点修改；
   迁移器只处理生成型 atlas 材质，其余给出明确提示。
2. **`mtk_emission` 不是纯材质语义**：红石线亮度依赖它；删除前必须先确认没有其他消费者，
   或把它降级为纯几何属性。
3. **公开 bridge API**：虽然无已知第三方，但 `bridge/material.py` 的函数是事实上的公共面；
   v2.2 标 deprecated，v3.0 删除，给一个版本的缓冲。
4. **跨 crate 字段删除**：`FaceAttributes.material_props` 涉及 `mtk-core`/`mtk-voxel`/`mtk-model`/
   `mtk-py`，必须单个 PR 完成并跑 ABI/属性测试。
5. **旧 `.blend` 不因删除生成器而损坏**：这是本计划的前提；如果未来需要“重新生成旧 decoder”
   （例如做对比测试），应在 v3.0 前把参考实现冻结成测试 fixture 或 Rust golden，而不是保留
   Python 生成器。

---

## 7. 建议的第一步

先做 **v2.2 的 L4 + L7**：

- 停止 `mtk-voxel` / `mtk-model` 对 `get_material_props` 的运行时调用（性能收益立竿见影）。
- 移除 `__init__.py` 的启动时属性 JSON 加载。
- 这两步不需要删除字段，风险最低，且能验证“没有消费者也能正常工作”。

然后再做 L1/L6/L8 的模块迁移与 feature gate，最后在 v3.0 执行删除。
