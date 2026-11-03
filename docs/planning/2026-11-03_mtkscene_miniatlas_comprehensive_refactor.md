# 2026-11-03 MTKScene (.mtkscene) 与 Mini-Atlas 彻底重构规划白皮书

> **文档定位**：针对当前未同步的 `.mtkscene` 场景交换与 Mini-Atlas 导出/导入机制进行系统性审查，定位严重缺陷根因，确立「自包含世界胶囊 (Self-Contained World Capsule)」核心范式，并给出跨 Rust Core (`libmozitoolkit`) 与 Blender Addon (`MoziToolKit`) 的完整重构执行规划。

---

## 1. 现状审查与核心缺陷根因剖析

经对 `libmozitoolkit`（提交 `0371e1e` / `d219876`）和 `MoziToolKit`（提交 `158269a`）的代码审查，确认当前实现存在四大导致贴图彻底崩坏、材质丢失与架构割裂的致命问题：

### 缺陷 1：UV 寻址倒置与数学公式错误（导致材质表面彻底碎裂）
- **根因代码**：[`crates/libmtk/src/scene/exporter.rs`](file:///Volumes/Data/code_projects/mtk/libmozitoolkit/crates/libmtk/src/scene/exporter.rs#L389-L393)
  ```rust
  // ❌ 错误实现：直接使用 Top-Down 图像像素坐标作为 UV 边界
  let u_min = slot.x as f32 / chunk.width as f32;
  let v_min = slot.y as f32 / chunk.height as f32;
  let u_max = (slot.x + slot.width) as f32 / chunk.width as f32;
  let v_max = (slot.y + slot.height) as f32 / chunk.height as f32;
  ```
- **物理事实**：PNG 图像在内存和磁盘中是左上角原点（Top-Left，$Y=0$ 在顶部），而 3D DCC 与 Blender 的 UV 坐标系是左下角原点（Bottom-Left，$V=0$ 在底部，$V=1$ 在顶部）。
- **连锁破坏**：在模型烘焙公式 `atlas_v = v_min + (1.0 - local_v) * v_span` 中，由于 $v_{\min}$ 被赋为上沿、$v_{\max}$ 被赋为下沿，导致不仅每个 Sprite 在 V 轴上被**强制垂直颠倒**，所有 Sprite 在图集中的相对寻址也全线错位，导入 Blender 后模型表面贴图完全碎裂颠倒。
- **规范标准**：必须严格遵循 [`static_atlas.rs`](file:///Volumes/Data/code_projects/mtk/libmozitoolkit/crates/mtk-texture/src/atlas/builder/static_atlas.rs#L157-L158) 的权威计算：
  $$\begin{aligned}
  v_{\min} &= 1.0 - \frac{y + h}{H} \quad (\text{对应底层像素 Y}) \\
  v_{\max} &= 1.0 - \frac{y}{H} \quad (\text{对应顶层像素 Y})
  \end{aligned}$$

---

### 缺陷 2：动态材质与 Overlay 被无差别丢弃
1. **Overlay（覆盖层）全链路缺失**：
   - 草方块侧面（`grass_block_side`）、覆雪泥土等依赖 `_overlay.png` 叠加群系色；
   - `SceneAtlasSource` 未定义 `get_overlay`，`SpriteCrop` 无 `overlay` 字段，导出时硬编码 `has_overlay = false`；
   - 导致草方块侧面上半部分草皮完全丢失或变黑。
2. **动态材质（水、熔岩、火、海晶石等）被粗暴压平**：
   - 导出时只裁剪了 `pixel_rect`（16x16 第一帧），完全丢弃了包含全部动画帧的垂直长条 `strip_pixel_rect`；
   - `mini_atlas_map.anim_sprites` 全空，所有 chunk 的 `is_animated` 被硬编码为 `false`；
   - 丢弃了 `frame_count`, `frame_uv_step` 及 `.mcmeta` 帧时长元数据；
   - **流体漏网**：水和岩浆在 Minecraft 中由 `FluidMesher` 单独处理，无标准 Block Model JSON。当前导出器仅扫描模型库 Elements，导致流体材质（`water_still`, `water_flow` 等）甚至未进入待裁剪列表！

---

### 缺陷 3：实体实时拼装图集（Dynamic Entity Atlas）100% 丢失
- **保留区间与用途**：Chunk ID `0xFFF0..=0xFFFF` 专用于玩家头颅皮肤（64x64 RGBA）与多层合成旗帜（Banner）。
- **丢弃过程**：
  1. `export_scene_package` 仅传入离线静态资产包 `.mtkcache`，未透传当前世界的动态图集；
  2. 导出器在静态图集映射表中查找 `minecraft:skin/...` 或自定义 `banner:...` 时命中 `None`，全部被 `continue` 静默丢弃；
  3. 导入时重新网格化生成了 `0xFFF0` 材质索引，但导入端只建了 1 个 Mini-Atlas 材质槽，**面的 `material_index = 0xFFF0` 严重越界**，在 Blender 视口中产生粉红色丢失材质或碎裂黑模。

---

### 缺陷 4：集合与材质特化违背 SSOT 架构
- **集合割裂**：[`utils/scene/hierarchy.py`](file:///Volumes/Data/code_projects/mtk/MoziToolKit/utils/scene/hierarchy.py) 私自创建名为 `MoziToolKit_Scenes` 的专属集合，违反了 Live Sync 和 Save Import 严格挂载在当前激活集合（`context.collection`）的 SSOT 规约。
- **材质特化孤岛**：[`utils/scene/materials.py`](file:///Volumes/Data/code_projects/mtk/MoziToolKit/utils/scene/materials.py) 另起炉灶写了一套简陋节点树，未接入 Biome Tint（草方块全灰）、未接入 Overlay、未支持动态动画驱动，且未执行面材质索引重映射。

---

## 2. 核心架构范式重塑：便携式自包含世界胶囊 (Self-Contained World Capsule)

我们确立 `.mtkscene` 的本质定位：**它是一种特殊的、高度精简的便携式自包含 Minecraft 微型存档**。

```
 ┌────────────────────────────────────────────────────────────────────────┐
 │                      MTK 统一世界构建三支柱架构                        │
 └────────────────────────────────────────────────────────────────────────┘
                                     │
         ┌───────────────────────────┼───────────────────────────┐
         ▼                           ▼                           ▼
   【实时协同 Live Sync】        【存档导入 Save Import】     【场景交换 Scene Capsule (.mtkscene)】
   - 依赖 Yefira 服务端推送     - 依赖本地 MCA 区域文件      - 完全自包含单文件胶囊 (.mtkscene)
   - 依赖本地全局 .mtkcache     - 依赖本地全局 .mtkcache      - 内嵌稀疏体素 + Tree-shaken 模型 + Mini-Atlas
         │                           │                           │
         └───────────────────────────┼───────────────────────────┘
                                     ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │               统一宿主装配核心 (Single Source of Truth)                │
 │  1. 激活集合挂载: context.collection (绝不新建专属集合)                │
 │  2. 统一根容器装配: Empty [Scene]/[Save]/[World] (mtk:is_container=True)│
 │  3. 伴生体素点云: ensure_voxel_child_cloud (0ms 链接，非破坏性视口遮罩)  │
 │  4. 官方安全通道/DNA直写: inject_mesh_data (双通道几何注入)            │
 │  5. 标准预解码 PBR 材质管线: ensure_world_materials / build_atlas_chunk│
 │     (Biome Tint 向量驱动 + Overlay Alpha 混合 + 动画帧 UV 驱动)       │
 └────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Mini-Atlas 动静双模与实体自包含重构方案

### 3.1 动静双卷正交装箱体系 (Dual-Volume Mini-Atlas)
无论导出时当前世界是否开启动态材质，只要场景内包含了使用动画的方块（水、熔岩、火、海晶石等），Mini-Atlas 在导出时**必须同时打包静态帧与完整动画长条**，导入端保留自由选择权：

1. **卷 1：静态图集卷 (Static Chunks, `is_animated = false`)**：
   - 包含场景内所有方块、实体皮肤、旗帜的 Frame 0（覆盖率 100%）；
   - 包含多通道：Albedo, Normal, ORM, AUX，以及 **Overlay（覆盖层）**；
   - 计算标准 UV 坐标，存入 `mini_atlas_map.sprites`。
2. **卷 2：动态长条卷 (Animated Chunks, `is_animated = true`)**：
   - 仅当场景包含动画方块时按需生成；
   - 裁剪水流、熔岩、火焰等方块的完整垂直长条（`strip_pixel_rect`）；
   - 计算动画 strip UV、`frame_0_uv_bounds` 及 `frame_uv_step`，保留 `.mcmeta` 帧时间；
   - 存入 `mini_atlas_map.anim_sprites`。

### 3.2 动态实体（玩家皮肤、旗帜）平民化自包含 (Democratized Stitching)
- 导出时由 Python 提取当前世界或网格绑定的 `dynamic_entity_atlases`（0xFFF0 动态图集内存缓冲）；
- 导出器根据 `entity_palette` 提取玩家头颅的 64x64 皮肤与合成旗帜的 64x64 布料像素；
- 将其作为普通 64x64 Sprite **直接装箱进静态 Mini-Atlas 卷**；
- 映射表中直接绑定 `"minecraft:skin/<key>"` 与 `"banner:<key>"`；
- **收益**：彻底消除 0xFFF0 材质槽越界，包体脱离网络与本地缓存后 100% 自包含离线还原。

### 3.3 流体材质自动防御收集
- 检查 `state_palette`：若包含 `water` 或 `lava`，自动将 `minecraft:block/water_still`, `minecraft:block/water_flow`, `minecraft:block/lava_still`, `minecraft:block/lava_flow` 注入待裁剪材质清单。

---

## 4. 导入端 SSOT 对齐与交互升级

### 4.1 操作符侧边栏多属性定制面板 (`op_import_scene.py`)
全面对标 `op_import_save.py`，在文件选择器右侧面板提供：
1. **Scene Info Preview 预览盒**：
   - 文件名、场景标题、作者、创建时间；
   - 体素总量（如 `12,450 blocks`）、3D 尺寸范围（`dx × dy × dz`）、唯一方块/群系/实体计数。
2. **Meshing & Shaders 选项盒**：
   - `enable_animated_textures`：**动态材质开关**（依托包内动静双卷，自由切换动静图集）；
   - `enable_ao`：平滑 4 角环境光遮蔽；
   - `mesh_fluids`：流体曲面几何计算；
   - `weld_vertices`：共面平滑顶点焊接；
   - `origin_centered`：原点居中（以选区几何中心还是绝对坐标为原点）；
   - `material_mode`：PBR 图集材质模式。

### 4.2 层级结构与材质装配规范
- **废弃专属集合**：彻底删除 `get_or_create_scene_collection`，统一链接至 `context.collection`；
- **废弃私有材质构建**：彻底废弃 `utils/scene/materials.py`，统一复用 `utils/materials/builder/world_binding.py` 的 `ensure_world_materials`；
- **严密槽位对齐**：通过 `chunk_to_compact_slot` 映射，统一执行 `mesh.polygons.foreach_set("material_index", remapped)`。

---

## 5. 跨项目落地点与文件重构清单

```
libmozitoolkit/
├── crates/libmtk/src/scene/
│   ├── exporter.rs          -> 彻底重写: UV公式修正、Overlay提取输出、静态/动态双卷装箱、动态实体缓冲提取
│   ├── package.rs           -> 确保支持多卷 ATLS (scene_atlas_xxx 与 scene_anim_atlas_xxx)
│   └── metadata.rs          -> 补充动态卷元数据标识
└── bindings/mtk-py/src/
    └── scene.rs             -> export_scene_package 增加 dynamic_entity_atlases 传参绑定

MoziToolKit/
├── bridge/scene.py          -> export_scene_package 透传当前 dynamic_entity_atlases; load_and_mesh 支持动静切换
├── operators/scene/
│   ├── op_import_scene.py   -> 增加与存档导入对齐的多属性定制面板与信息预览
│   └── op_export_scene.py   -> 提取当前网格绑定的 dynamic_entity_atlases 传给 bridge
├── utils/scene/
│   ├── hierarchy.py         -> 废弃专属集合，严格遵从 context.collection 与标准容器属性
│   └── materials.py         -> 彻底废弃/重定向至 utils/materials/builder/world_binding.py
└── docs/scene/
    └── scene_interchange.md -> 更新架构文档与规范
```

---

## 6. 验收与质量门禁

重构完成后必须通过以下硬性门禁：
1. **UV 坐标与贴图对齐验证**：从 `.mtkscene` 导入后，模型贴图各面方向绝对正确，无上下颠倒、错位或裂缝；
2. **草方块 Overlay 验证**：草方块侧面顶部覆盖草皮完整，受生物群系染色正确驱动，无黑边或透明缺失；
3. **动静切换双模验证**：导入时勾选「Animated Textures」可见水流/火焰动画长条驱动；取消勾选则无缝回退为 Frame 0 纯静态材质；
4. **动态实体自包含验证**：包含玩家头颅皮肤与自定义合成旗帜的场景导出后，在干净测试环境（清除本地皮肤缓存与网络）重新导入，皮肤与旗帜纹理 100% 正常显示，材质槽零越界；
5. **集合行为验证**：导入的新容器和网格 100% 位于用户当前激活集合，绝无多余集合生成；
6. **全套自动化测试全绿**：`cargo test --workspace` 与 `uv run pytest tests/` 零报错、零告警。
