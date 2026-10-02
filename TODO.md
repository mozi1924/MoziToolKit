# 📋 MoziToolKit (Blender Addon) 开发计划与 TODO 清单

本文档为 `MoziToolKit` Blender 插件前端的功能演进与任务清单。底层核心算法与体素/几何流计算见 [`libmozitoolkit/TODO.md`](../libmozitoolkit/TODO.md)。

---

## 阶段一：小三样核心网格与 UV 工具库（Blender 前端集成 - ✅ 已完成）
- [x] **自适应像素网格切分前端 (`operators/op_pixel_split.py`)**
  - [x] 封装 `bridge/subdivide.py`，与 Rust 后端 `adaptive_pixel_split_mesh` 零拷贝通信。
  - [x] UI 侧边栏参数绑定（像素密度、最大切分数、微距焊接阈值）。
  - [x] 自动保留顶点色、UV、Deform 蒙皮权重等原生 Blender 属性。
- [x] **智能挤出与 UV 修复系统前端 (`operators/extrude/`)**
  - [x] 模块化重构为子包架构（`properties.py`, `watcher.py`, `op_extrude.py`, `op_random_extrude.py`）。
  - [x] 封装 `bridge/extrude.py`，支持 SMART / INWARD / OUTWARD 模式。
  - [x] Blender 4.2+ 实时编辑模式 Depsgraph 动态监听与 UV 即时修复。
  - [x] 3D 噪声与随机高度挤出操作符及 UI 控制面板。
  - [x] 自动标记锐边 Crease，保持边缘硬朗着色。
- [x] **外部网格面遮挡剔除前端 (`operators/op_cull.py`)**
  - [x] 封装 `bridge/cull.py`，调用 Rust 6 向邻域遮挡分析。
  - [x] 一键清理 Mineways / MiEx 导入资产的内部重叠废面。

---

## 阶段二：Minecraft 存档与体素世界直接导入（Blender 宿主端接入 - 🚧 规划中）
- [ ] **存档选择与流式切片导入 UI**
  - [ ] Java 原版 (MCA/NBT) 与基岩版 (LevelDB) 世界路径选取器与版本自动探测。
  - [ ] 3D 视口世界包围盒切片框选择器（支持按坐标范围、维度 Dimension、高度区间导入）。
- [ ] **Bridge 接入与网格流极速灌入**
  - [ ] 对接 `bridge/voxel.py`，消费 `libmtk` 解包产出的统一体素流。
  - [ ] 使用 `b_mesh.vertices.foreach_set` 与 `b_mesh.loops.foreach_set` 批量快速生成原生网格。
- [ ] **多材质槽与 Biome Tint 节点注入**
  - [ ] 依据体素元数据自动创建并分配材质槽。
  - [ ] 自动化构建 Blender Principled BSDF 节点树与生物群系线性调色板混合节点。

---

## 阶段三：网格重构（Mesh Reconstruction）与高精度资产替换（🚧 规划中）
- [ ] **导入网格体素化重构操作符 (`op_reconstruct.py`)**
  - [ ] 提供 UI 操作符，调用 `libmtk` 的 Voxel Guesser 从已有低精网格中逆向生成体素。
- [ ] **材质包（Resourcepack）模型动态重载**
  - [ ] 自定义材质包目录挂载与高精度 Block Model JSON 替换。
  - [ ] 彻底替换旧版基于外部贴图脚本的脆弱管线，改为 Rust 无头预烘焙图集极速加载。

---

## 阶段四：Live Sync 实时双向网络协同（🚧 规划中）
- [ ] **Live Sync 交互面板与会话生命周期 (`operators/sync/`)**
  - [ ] 完善 WebSocket 客户端连接、心跳状态指示灯与端口/Token 配置面板。
  - [ ] 后台异步轮询 Handler，接收游戏内方块更新与相机/玩家位置。
- [ ] **增量式视口对象更新与元数据持久化**
  - [ ] 利用 Blender 几何节点 / 属性域（Attributes / Point Cloud）高效承载体素元数据。
  - [ ] 实现非破坏性局部区块差量刷新。
