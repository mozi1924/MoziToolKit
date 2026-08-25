# 模块三：原生网格实时同步构建体系 (Direct Mesh Generation)

`utils/live_sync/mesh_builder.py` 替代了传统的点云与几何节点管线，直接生成干净、可编辑、高性能的 Blender 真实原生多边形网格（Direct BMesh）。

## 1. Direct Mesh 架构与 16x16x16 Section 局部网格容器
- **分块容器管理**：在父空物体 `Yefira_World` 下按 $16 \times 16 \times 16$ 体积块划分子网格物体（`Yefira_Section_{sec_x}_{sec_y}_{sec_z}`）。
- **坐标变换与对齐**：通过 Minecraft 到 Blender 本地坐标系的精确映射：
  $$x_{blender} = x_{mc} - \text{half\_x},\quad y_{blender} = -(z_{mc} - \text{half\_z}),\quad z_{blender} = y_{mc} - \text{min\_y} + 0.5$$
- **内存预热与就绪 (Preload Data)**：在快照到达时，通过 `preload_sync_world_data` 预先将 Palette 中的所有方块模型变体与图集 UV 在 RAM 中构建缓存，消除运行时解析开销。

## 2. 6向邻域遮挡剔除 (Neighbor Culling) 与拓扑焊接 (Weld Topology)
- **严格6向不可见表面剔除**：在构建每个方块（Cube / Multipart / Fluid）的面时，检测其相邻方块的不透明度（`is_opaque`），仅生成暴露在空气或透明介质中的有效可见外表面。
- **拓扑焊接 (Weld Vertices)**：对相邻面共用的顶点进行距离阈值焊接（默认 `1e-4`），生成闭合水密或极简干净拓扑（单立方体仅 8 顶点 6 面，双连接方块仅 12 顶点 10 面）。

## 3. 毫秒级增量更新 (Incremental Delta Updates & Event Pump)
- **子毫秒局部重建 (`apply_block_delta_to_world`)**：当接收到方块放置或破坏时，仅针对受影响的方块坐标及其邻域 6 个方块所在的 16x16x16 Section 网格进行局部 BMesh 增量重构，整体耗时稳定低于 `< 1.0 ms`。
- **邻居面动态复原 (Un-culling)**：当破坏一个方块时，自动将周围被其遮挡的相邻方块原本隐藏的接触面重新烘焙并缝合进网格。
- **空 Section 自动清理**：当一个 16x16x16 区块内所有方块均被清空为空气时，自动销毁并从 Blender 场景集合中解绑该 Section 子物体。

## 4. Multi-Chunk 图集材质插槽分配与原生 UVMap 烘焙
- **标准 UVMap 原生写入**：直接在 `bm.loops.layers.uv["UVMap"]` 中写入根据图集多 Chunk 与材质映射计算的归一化 UV 坐标，彻底摆脱材质着色器节点内部进行 UV 矩阵变换的开销与兼容性问题。
- **多图集 Chunk 材质插槽映射**：根据面对应的贴图所属 Chunk ID，自动设置 `bm_face.material_index = chunk_id`，精确支持多图集（Blocks, Animated, Items, Particles 等）协同渲染。
- **着色器面属性保留**：向面域写入 `mtk_block_x`, `mtk_block_y`, `mtk_block_z`, `mtk_face_dir`, `mtk_biome_tint_color`, `mtk_biome_tint_data`, `mtk_anim_timing`, `mtk_anim_frame_size` 等原生着色属性。

## 5. Direct Mesh 同步防回归不变量契约
> [!IMPORTANT]
> 1. **原生网格可编辑性保证**：生成的网格必须为真实 Blender Mesh，支持进入 Edit Mode 编辑、UV 展开修改、细分修改器与导出为 FBX/GLTF。
> 2. **增量更新耗时约束**：对于单次 1~64 块以内的 Delta 更新，必须直接调用 `apply_block_delta_to_world` 执行局部 Section 重建，单次编辑耗时不得超过 1.5ms。
> 3. **跨 Section 边界缝合一致性**：跨 Section 边界（如 $x=15$ 与 $x=16$）放置方块时，两边 Section 的邻接面剔除状态必须同步刷新。
