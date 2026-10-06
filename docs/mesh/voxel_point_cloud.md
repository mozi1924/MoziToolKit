# 体素点云网格持久化存储规范 (Voxel Point Cloud Storage & Hierarchy Contract)

本文档规范 `MoziToolKit` 中基于 `VoxelPointCloud` 的全量无剔除体素点云存储、Blender 场景层级关系及 API 契约。

---

## 1. 核心架构契约与设计哲学

在 3D 渲染与编辑中，表面多边形网格（Surface Mesh）往往经过了激进的 6 向邻域遮挡剔除（Face Culling）、顶点焊接（Weld Vertices）与图集映射，内部实心方块的多边形全部被剔除。如果用户需要在 DCC 中进行**二次体素雕刻（Carving）、内部挖空、方块重选或重新网格化（Remeshing）**，必须有忠实保存原始 3D 空间所有方块（包括内部实心方块）的无损体素数据源。

### 统一铁律 (Golden Rule)
> **无论体素数据来源于 Live Sync 实时流、Minecraft 存档导入（.mca / Anvil）、离线测试世界、还是未来的 Schematic / Litematica / NBT 结构，只要是从体素构建的网格对象，都必须且只能通过 `ensure_voxel_child_cloud` 在其主物体的子级（Child）下构建/同步一个体素点云网格对象。**

---

## 2. Blender 场景主从拓扑结构 (Hierarchy Contract)

```
┌─────────────────────────────────────────────────────────────┐
│  主物体 Parent World Object (例如 "MC_World" / "Yefira_World") │
│  - 承载表面几何多边形网格 (Quads, AO, Biome Tinting)          │
│  - 承载 Atlas Chunk PBR 材质槽与 Shader 节点树               │
│  - 自定义属性: mtk_voxel_cloud = "<Parent>_VoxelCloud"      │
└──────────────────────────────┬──────────────────────────────┘
                               │ parent (Local Transform 归零)
                               ▼
┌─────────────────────────────────────────────────────────────┐
│  子物体 Child Voxel Cloud Object ("<Parent>_VoxelCloud")     │
│  - 纯顶点点云网格 (len(vertices) == 全量非空体素数)           │
│  - 1:1 本地绝对对齐:                                        │
│      location = (0, 0, 0), rotation = (0, 0, 0), scale = 1  │
│      matrix_parent_inverse.identity()                       │
│  - 与主物体位于同一 Collection (绝不创建凌乱多余集合)           │
│  - 默认绑定 Blender 原生 Mask Modifier:                      │
│      - 顶点组 "MTK_Voxel_Storage" (全顶点权重 1.0)           │
│      - 默认 invert=True (视口默认隐蔽内部点，不遮挡表面网格)   │
│      - 一键显现/进入雕刻模式 (mozi.toggle_voxel_cloud)        │
│  - 挂载点级属性 (Point Attributes):                          │
│      - mtk_block_x, mtk_block_y, mtk_block_z (INT)          │
│      - mtk_block_state (STRING)                             │
│      - mtk_biome (STRING)                                   │
│  - 自定义属性:                                               │
│      - mtk_is_voxel_cloud = True                            │
│      - mtk_world_mesh = parent.name                         │
│      - mtk_bounds = [min_x, min_y, min_z, max_x, ...]       │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. 桥接 API 规范 (`bridge/point_cloud.py`)

### 3.1 统一创建与同步入口
```python
def ensure_voxel_child_cloud(
    parent_obj: bpy.types.Object,
    storage: Optional[VoxelStorage] = None,
    cloud_data: Optional[VoxelPointCloud] = None,
    origin_centered: bool = True,
    initial_hidden: bool = True,
) -> Optional[bpy.types.Object]:
    """在 parent_obj 的子级构建或同步体素点云网格。
    
    保证严格的父子挂载、本地空间 1:1 对齐、同集合放置、Mask 遮罩配置与双向属性标记。
    """
```

### 3.2 双向查询与寻回
- **`get_associated_voxel_cloud(parent_or_mesh)`**：解析主物体关联的体素点云子物体。
- **`get_associated_parent_mesh(cloud_or_mesh)`**：解析体素点云对应的父级主世界物体。

### 3.3 废弃接口声明
- `sync_voxel_point_cloud_for_world` 已标记为 `@deprecated`，因其 `sync` 命名前缀具有误导性（让人误以为只属于 Live Sync）。当前保留别名并自动转发至 `ensure_voxel_child_cloud`，同时抛出 `DeprecationWarning`。

---

## 4. 用户交互与算子管线 (Operators Flow)

1. **显隐切换与雕刻 (`mozi.toggle_voxel_cloud`)**：
   - 切换子物体 Mask Modifier 的反转状态。
   - 可一键进入 Edit Mode 并开启透视（X-Ray），方便框选删除内部/外部体素。
2. **体素反向重构表面网格 (`mozi.remesh_from_voxel_cloud`)**：
   - 从子物体的点云属性中零拷贝提取 `VoxelPointCloud`；
   - 转化为 `VoxelStorage` 重新调用 Rust 端网格化核心（`SectionMesher` / `VoxelWorld`）；
   - 将重新计算的外露多边形直接灌回父级主物体，保留雕刻空腔。
