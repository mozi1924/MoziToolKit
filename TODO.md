# 📋 开发计划与 TODO 清单

## 阶段一：小三样核心网格与 UV 工具库（Rust 后端加速与算子化）
- [x] **自适应像素网格切分系统 (Adaptive Pixel Split)**
  - [x] Rust 核心四边形像素细分算法、自适应行列数推算、双线性插值（UV、Deform 蒙皮权重、顶点色、自定义属性）。
  - [x] 动画长条贴图单帧正方形安全截断机制（防面数爆炸）。
  - [x] 拓扑微距焊接与流形缝合清理。
  - [x] PyO3 绑定与 Blender `bridge/subdivide.py`、`op_pixel_split.py`。
- [x] **智能挤出与 UV 修复系统 (Auto Extrude Repair & Random Extrude)**
  - [x] 侧面 UV 塌陷判定与 SMART / INWARD / OUTWARD 三种模式几何重构。
  - [x] Atlas 图集安全边界裁剪（Safe Padding Clamp）。
  - [x] 3D Perlin 连续噪声、Voronoi 细胞噪声与 Uniform Random 随机挤出高度生成器。
  - [x] Crease 锐边保护标记。
  - [x] PyO3 绑定与 Blender `bridge/extrude.py`、`op_extrude.py`。
- [x] **已导入外部网格面剔除工具 (Mesh Face Culling)**
  - [x] 基于 `mtk-cull` 空间邻域分析与 2D 矩形投影差集，对导入的外部模型执行 6 向内部遮挡剔除。
  - [x] PyO3 绑定与 Blender `bridge/cull.py`、`op_cull.py`。


---

## 阶段二：Minecraft 存档直接读取（多版本/多格式支持）
- [ ] **Java 原版存档读取**
  - [ ] 支持 Anvil/MCA 格式及 NBT 解析，读取方块、调色板（Palette）与区块（Chunk）数据。
- [ ] **Java 模组（Modded）世界支持**
  - [ ] 支持扩展方块ID与自定义 BlockState 解析（兼容 Forge/Fabric/NeoForge 等生态数据）。
- [ ] **基岩版（Bedrock Edition）存档读取**
  - [ ] 支持 LevelDB 存储格式解析与基岩版独特的方块属性/SubChunk 结构。
- [ ] **统一输入适配层**
  - [ ] 将各版本存档数据统一转化为内部通用的体素源（Voxel Source）接口。

---

## 阶段三：网格重构（Mesh Reconstruction）与材质包模型替换
- [ ] **体素反向逆向推算（Voxel Guesser/Inference）**
  - [ ] 从已有导入来源的网格（Geometry/UV/材质）中反向提取空间占位并推算对应体素信息。
- [ ] **基于体素的世界重构生成器**
  - [ ] 根据推算出的体素数据重新构建网格世界。
  - [ ] 对接材质包资源（Resourcepack Models/Blockstates/Textures），在重构时直接套用高精度/自定义模型与贴图。
- [ ] **下线与迁移**
  - [ ] 平滑替换并移除旧版的纯材质替换逻辑。

---

## 阶段四：实时同步与体素元数据存储系统
- [ ] **体素元数据架构设计**
  - [ ] 设计支持完整世界还原的体素数据结构（包含方块ID、状态/State、方向、附加属性等）。
  - [ ] 建立基于**点云（Point Cloud）**与**网格属性（Mesh Attributes/Vertex Data）**的双向元数据映射机制。
- [ ] **实时同步管线完善**
  - [ ] 保证在场景变动/更新时，点云与网格的元数据能高效、无损地实时同步并可持久化。

