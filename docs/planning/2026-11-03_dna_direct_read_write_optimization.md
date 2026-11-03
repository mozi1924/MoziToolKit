# 2026-11-03 DNA 内存直读与全通道直写架构设计方案

> **文档性质**：架构设计 RFC & 实施路线图 (RFC / Technical Spec)  
> **基线环境**：Blender 4.2 LTS ~ 5.2.3 LTS (`/Volumes/Data/code_projects/mtk/blender`)  
> **涉及仓库**：`MoziToolKit` (Blender Addon) 与 `libmozitoolkit` (Rust Core / Host Adapters)  
> **状态**：**已全部实现并通过完整测试门禁验证 (All Gates Passed)**  

---

## 1. 背景与核心价值

当前 MTK 已建立基于 `libmtk_blender_dna` 的 **Fast-Path 内存直写**机制，在网格与点云注入时显著降低了耗时。但在反向提取网格（如网格切分、点云反向解析、流体 UV 修复、网格重构、Live Sync 协同回传）时，系统仍全量依赖 Python 层的 `foreach_get`，面临如下瓶颈：

1. **Python 堆分配开销**：单次 `extract_mesh_data` 需要分配 7+ 个独立的 NumPy 缓冲；
2. **RNA 遍历开销**：Blender CPython 胶水层需要在 C 层面逐项解包遍历；
3. **交互延迟高**：处理 25 万顶点 / 25 万面网格时，仅“读取网格”阶段就耗费 **20 ~ 30 ms**，导致实时操作符存在肉眼可见的顿挫。

通过引入 **DNA 内存直读 (Fast-Path Read)** 并修复现有**直写的残留慢通道**，可将读取耗时压至 **0.3 ms 以内**（吞吐量提升 18x ~ 180x），使网格读写延迟全面减半。

---

## 2. 权威实测数据基准 (Blender 5.2.3 LTS)

测试样本：**251,001 顶点，1,000,000 角点 (Loops)，250,000 面 (Polygons)**

| 数据操作通路 | 单层属性耗时 (ms) | 全网格耗时估算 (ms) | 性能倍率 | 内存分配与零拷贝特性 |
| :--- | :---: | :---: | :---: | :--- |
| **Safe-Path (`foreach_get`)** | **4.25 ms** | **20 ~ 30 ms** | $1\times$ (基准) | 经由 RNA getter 循环转换，堆分配 NumPy 缓冲 |
| **DNA Copy (安全直读)** | **0.23 ms** | **1.2 ~ 1.5 ms** | **$18\times$ 快** | 绕过 RNA 开销，直接从 C++ 内存块抓取数据 |
| **DNA Zero-Copy (零拷贝视图)** | **0.02 ms** | **0.1 ~ 0.3 ms** | **$180\times$ 快** | 零内存分配，直接借用 Blender 内部 C++ 连续数组 |

---

## 3. Blender 4.2 LTS ~ 5.2 LTS 源码事实源对照 (SSOT)

通过对本地 `/Volumes/Data/code_projects/mtk/blender/` 中全部 Release 分支（`v4.2`、`v4.3`、`v4.4`、`v4.5`、`v5.0`、`v5.1`、`v5.2`）的逐行审查，确认以下关键契约在跨版本间 **100% 稳定通用**：

### 3.1 核心数据结构指针映射表

| 几何属性 | Blender C++ 事实源 | RNA / Attribute 指针路径 | 内存布局与类型 | 跨版本兼容性 (4.2 ~ 5.2) |
| :--- | :--- | :--- | :--- | :--- |
| **顶点 3D 位置** | `mesh->vert_positions()` | `mesh.attributes["position"].data[0].as_pointer()` 或 `mesh.vertices[0].as_pointer()` | 连续 `[f32; 3]`，4 字节对齐 | 绝对一致 (`float3 *`) |
| **角点顶点索引** | `mesh->corner_verts()` | `mesh.attributes[".corner_vert"].data[0].as_pointer()` 或 `mesh.loops[0].as_pointer()` | 连续 `int32` / `uint32` | 绝对一致 (`int *`) |
| **面角点偏移 (CSR)** | `mesh->face_offsets()` | **`mesh.polygons[0].as_pointer()`** | 连续 `int32`，长度为 `poly_count + 1` | **绝对一致 (`face_offset_indices`)** |
| **循环 UV 坐标** | `corner_data` / `CD_PROP_FLOAT2` | `mesh.attributes[uv_name].data[0].as_pointer()` | 连续 `[f32; 2]` | 绝对一致 (`float2 *`) |
| **面材质槽索引** | `material_index` Face 属性 | `mesh.attributes["material_index"].data[0].as_pointer()` | 连续 `int32` | 绝对一致 (`int *`) |
| **循环/顶点颜色** | `FLOAT_COLOR` 属性 | `mesh.attributes[col_name].data[0].as_pointer()` | 连续 `[f32; 4]` | 绝对一致 (`float4 *`) |
| **体素点云坐标/状态** | Generic Attributes | `cloud.attributes[name].data[0].as_pointer()` | 连续 `int32` / `float32` | 绝对一致 |

### 3.2 重点突破：面拓扑偏移 (`face_offset_indices`)
- **源码事实**：在 `rna_mesh.cc` 中：
  ```cpp
  static int rna_MeshPolygon_loop_total_get(PointerRNA *ptr) {
    const int *data = static_cast<const int *>(ptr->data);
    return *(data + 1) - *data; // 下一个面的 offset 减去当前面的 offset
  }
  ```
  `mesh.polygons[0].as_pointer()` 返回的 `ptr->data` 就是底层连续的 `mesh->face_offset_indices`！
- **实测验证**：
  直接向 `mesh.polygons[0].as_pointer()` 写入 `[0, 4, 8, ...]` 并调用 `mesh.update(calc_edges=True)`，`mesh.validate()` 报 0 错误，面与边拓扑 100% 正确生成。**读写皆可直接使用此指针！**

### 3.3 破除误区：面材质索引 (`material_index`)
- **旧注记误区**：旧代码误认为材质槽是“紧凑结构体中的窄整型无法直写”。
- **源码事实**：Blender 4.2+ 早已将 `material_index` 抽象为 Face 域的通用属性（`lookup_or_default<int>("material_index", Face)`）。只要该属性存在，其底层就是标准的连续 `int32` 数组，完全支持 DNA 直写与直读。

### 3.4 5.1/5.2 AttributeStorage 演进透明性
- Blender 5.1 引入 Commit `8adba33029f`（Mesh 从 `CustomData` 切换到 `AttributeStorage`）。
- 该重构仅为 C++ 内部容器调整，其 RNA 接口依然使用 `rna_iterator_array_begin` 导出 `ArrayData.data`。Python 层拿到的裸指针完全不变。

---

## 4. 现有写入实现审查与待修复项

### 4.1 现有写操作体检表

| 写入函数 | 现状判定 | 源码比对分析 | 改造建议 |
| :--- | :--- | :--- | :--- |
| `inject_vertex_positions_dna` | **完全稳健** | 对齐、长度校验完备，末尾有 `mesh.update()` | 保持 |
| `inject_topology_dna` | **半直写半降级** | 顶点与角点直写成功；但 Polygon 的 `loop_start` 和 `loop_total` 回退了 2 次 `foreach_set` | **改造为直写 `face_offset_indices`**，消除 NumPy 分配与遍历 |
| `inject_uvs_dna` | **完全稳健** | Corner 域 `FLOAT2`，连续安全 | 保持 |
| `inject_color_attributes_dna`| **完全稳健** | `FLOAT_COLOR` 连续 16 字节对齐 | 保持 |
| `inject_custom_attribute_dna`| **完全稳健** | 多类型步长与内存尺寸完全对齐 | 保持 |
| `inject_face_materials_standard`| **未接入 DNA** | 受旧注释影响走慢速 `foreach_set` | **新增 `inject_materials_dna`**，直写 `material_index` 属性 |
| `inject_vertex_normals_dna` | **空转失效** | 查找了不存在的 Point 域 `"normal"` 属性 | 清理空转逻辑；依赖 Blender 自动法线或写入 Corner `custom_normal` |
| `inject_point_cloud_dna` | **极稳，个别回退** | 核心 6 属性直写；实体索引有个别 NumPy 回退 | 将 `entity_idx` 全面补齐至直写解析器 |

---

## 5. 新增“内存直读”候选模块与收益分析

```
MoziToolKit 内存直读改造图谱
├── [核心基础设施] bridge/mesh/extract.py
│   └── extract_mesh_data: 7+ 次 foreach_get -> 1 次全指针解析 + 零拷贝 MemoryView 构建
├── [交互操作符] operators/op_pixel_split.py
│   └── AdaptivePixelSplit: 读网格 (20ms) -> 算切分 -> 写网格 (0.5ms)；读阶段提速 50x，交互无感
├── [点云反向提取] bridge/point_cloud/extract.py
│   └── extract_point_cloud: 6 次 foreach_get -> 纯指针批量读入 VoxelPointCloud
├── [流体算子] utils/mesh/fluid_uv.py
│   └── repair_mesh_fluid_uv_inplace: 原位读拓扑/UV -> Rust 修复 -> 原位写回
├── [网格重构] operators/mesh/op_rebuild_mesh.py
│   └── 重构前读取当前网格自定义属性与材质分布
└── [协同上报] operators/sync/ (Live Sync RFC v3.1)
    └── 向 Yefira 上报用户在 Blender 中的选区编辑增量
```

---

## 6. 双通道架构与安全降级规范 (Rule 3 & Rule 8)

依据项目全局开发规范，所有改造必须遵循**严格双通道与无缝降级**：

```
                    ┌──────────────────────────────────────┐
                    │    extract_mesh_data / inject_...    │
                    └──────────────────┬───────────────────┘
                                       │
                       is_dna_enabled() 判定
                       ┌───────────────┴───────────────┐
                       │                               │
            [Fast-Path (DNA 直读/直写)]     [Safe-Path (Bpy 官方批量)]
        1. BaseDnaResolver 解析连续指针       1. 分配 NumPy 缓冲
        2. safe_as_pointer 对齐/地址门禁     2. 官方 foreach_get / set
        3. libmtk_blender_dna 内存直连       3. 保证 100% 官方 API 兼容
        4. (遇异常或指针无效，自动回退)       4. 用户关闭 DNA 加速时首选此路径
                       │                               │
                       └───────────────┬───────────────┘
                                       ▼
                       数据比特级 100% 一致 (POD 契约)
```

1. **用户自主开关**：与首选项 `enable_dna_acceleration` 及环境变量 `MTK_DISABLE_DNA=1` 完全绑定；
2. **零假降级 (No Fake Fallbacks)**：指针获取失败或校验不通过时，自动进入 Safe-Path，严禁报错中断用户流程。

---

## 7. 详细实施路线图 (Action Plan)

### Phase 1: 底层原生扩展更新 (`libmozitoolkit`)
- [x] **`mtk-host-memory`**：
  - 新增 `read_ptr_to_slice<T>`：从 host 裸指针安全读取到目标切片；
  - 增加指针连续性与只读内存安全防护。
- [x] **`mtk-blender-dna-py`**：
  - 增加直读函数：`read_f32`, `read_i32`, `read_u32`, `read_u8`；
  - 增加只读内存视图导出：`as_memoryview_f32(src_ptr, count)` 等（利用 `PyMemoryView_FromMemory` 实现零拷贝）。
- [x] **`libmtk_py` (`PyMeshData`)**：
  - `MeshData.from_flat_polygons` 优化对通用 Buffer Protocol 的零拷贝借用；
  - 增加对直接传入 `face_offset_indices` 的原生构造支持（避免 Python 拆分 `loop_start` 与 `loop_total`）。

### Phase 2: DNA 解析器增强 (`MoziToolKit/bridge/dna`)
- [x] 在 `BaseDnaResolver` 及 `DnaResolverV42` / `V50` 中增加：
  - `resolve_polygons_offset_ptr(mesh)` -> 返回 `mesh.polygons[0].as_pointer()`；
  - `resolve_materials_ptr(mesh)` -> 返回 `mesh.attributes["material_index"].data[0].as_pointer()`。

### Phase 3: 现有写入实现修复 (`MoziToolKit/bridge/mesh/dna.py`)
- [x] **拓扑写入改造**：在 `inject_topology_dna` 中，将 `mesh.polygons.foreach_set("loop_start/total")` 替换为直写 `face_offset_indices`；
- [x] **材质写入改造**：新增 `inject_face_materials_dna`，打通材质槽索引直写；
- [x] **法线写入清理**：清理空转的 `inject_vertex_normals_dna`；
- [x] **点云写入补齐**：补齐 `entity_idx` 直写逻辑。

### Phase 4: 网格直读通道构建 (`MoziToolKit/bridge/mesh/extract.py`)
- [x] 重构 `extract_mesh_data`：
  - 增加 `extract_mesh_data_dna` 分支；
  - 一键提取 `position`、`.corner_vert`、`UVMap`、`face_offset_indices`、`material_index` 指针；
  - 指针校验失败时无缝回退原 `foreach_get` 逻辑；
- [x] 重构 `bridge/point_cloud/extract.py`：实现点云属性直读。

### Phase 5: 验证与自动化测试门禁
- [x] 编写 `test_dna_read_consistency.py`：对比网格与点云在 Fast-Path 与 Safe-Path 下提取的 `MeshData`，断言顶点、UV、索引、面属性 100% 比特级一致；
- [x] 运行三道门禁：
  - `cargo test --workspace` (全绿)
  - `python -m pytest tests/ -q` (428 passed, 0 failure)
  - `blender --background --python tests/run_tests.py` (497 passed, 0 failure)。
