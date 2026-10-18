# MoziToolKit 技术文档与设计规范导航

欢迎查阅 **MoziToolKit** 的模块化设计与技术规范文档。为降低阅读和开发时的上下文开销，本文档库已按功能域进行了模块化拆分。

---

## 快速导航与模块索引

### 1. 架构总览与防回归哲学 (Architecture & Principles)
- **[架构总览与设计原则](architecture/overview.md)**：包含插件的分层架构图（UI 层、Pipeline 调度层、Engine 引擎层、System 基础层）以及全项目不可违背的四大核心设计哲学。
- **[核心设计决策与防回归 FAQ 对照表](architecture/faq_anti_regression.md)**：列举了草方块侧面染色、动画贴图正方形截断、jmc2obj 连续平铺 UV 等常见易被误判为 Bug 的既定设计特征对照表。
- **[生产级动画资产、按需预烘焙与原版特性规范](architecture/animation_assets_and_prebake_spec.md)**：包含胶水层按需自动预烘焙门禁、真实 3D 生物群系 Tint 采样与平滑混合、静态悬挂实体（画/展示框/地图）以及 CTM 闭环技术规范。

---

### 2. 材质与模型烘焙系统 (Materials & Model Baking)
- **[材质解析、匹配与替换管线](materials/material_pipeline.md)**：
  - 三层物理资源包优先级栈（`RESOURCE_PACK` → `MOD_JAR` → `VANILLA`）与通道级独立级联回退。
  - 多导入器（`jmc2obj`, `Mineways`, `Ice-Cube`, `Generic`）自适应匹配。
  - 双材质构建体系：图集模式（Atlas Mode）与预编译全栈融合独立模式（Standalone Mode）。
  - 图集防溢色数学模型（Padding & Safe Clamp）、逐帧动态动画（MCMETA）驱动及验收矩阵。
  - **面属性来源追踪与材质自愈 (`mozi.restore_materials_from_provenance`)**：基于 `mtk_source_texture_key` 与 `mtk_atlas_chunk_id` 的一键材质原地无损复原。
  - **生物群系高精度染色与 UI 控制面板 (`ui/panel_biome.py`)**：65+ 种原生群系预设库、双线性三角坐标采样、Linear RGBA 转换及 `mtk_biome` 物体覆盖。
  - **着色器节点组模板库 (`utils/node_groups/`)**：`atlas_uv_decoder`, `atlas_uv_tiling`, `animated`, `biome`, `labpbr`, `parallax` 节点组。
- **[MC 方块模型烘焙引擎 (MC Baker)](materials/mc_baker.md)**：
  - Blockstate 变体与 Multipart 复合条件解析。
  - Block Model JSON 继承树展开、`#texture` 变量解析、Cullface 标记、UV 旋转与 Atlas Bridge 桥接。

---

### 3. 网格与建模工具系统 (Mesh & UV Modeling)
- **[实时同步系统架构与数据规范 (Live Sync)](live_sync/live_sync_architecture.md)**：
  - 材质约定体系与自定义属性规范（`mtk:atlas_chunk_id`, `mtk:pack_hash`）。
  - 连接握手 CRC32 差异校验与已有场景物体智能免重刷机制。
  - “刷新数据 (Refresh Data)” 与 “重建网格 (Rebuild Mesh)” 行为边界划分。
  - 内存体素模型（`VoxelStorage`）、场景持久化层级容器（`hierarchy.py`）与操作符全景。
- **[实时同步协议与架构 RFC v3.1 (Live Sync RFC)](live_sync/live_sync_protocol.md)**：
  - Minecraft ↔ Rust ↔ Blender 三端权威协议：帧头、资源硬限、全部 Opcode 与负载布局。
  - Canonical `state_hash`（xxHash64）、X→Z→Y 扫描顺序与 Section-local Quart Biome 契约。
  - HELLO/WELCOME 决策矩阵、Baseline→Delta 栅栏、Staging/Replay、缺口检测与 RESYNC。
  - Per-client 基线代际、协作取消、Delta 16,384 分片、快速重连持久化与失效规则。
  - 连接状态权威同步、看门狗/限流/失败熔断，以及 10 项已知实现偏差与 v2.0 修复索引。
- **[原生网格实时同步构建体系 (Direct Mesh)](mesh/direct_mesh.md)**：
  - 16x16x16 Section 分块容器、6 向邻域遮挡剔除、拓扑微距焊接。
  - 毫秒级增量更新（Delta Update）与原生多图集 UVMap 写入。
- **[面剔除系统与原版遮挡算法 (Face Culling)](mesh/face_culling.md)**：
  - 对齐 Minecraft 1.21+ 原版 `Block.shouldRenderFace` 与 `BlockBehaviour.skipRendering`。
  - 4 大核心分类（实心不透明、半透玻璃组、透空树叶 Fancy/SingleFace/Fast、局部台阶/楼梯 2D 几何投影裁剪）。
- **[自适应像素网格切分系统 (Adaptive Pixel Split)](mesh/pixel_split.md)**：
  - 1 面 = 1 贴图像素自适应分辨率计算。
  - 动画贴图单帧正方形边界识别（避免过度切分）。
  - 骨骼权重（Vertex Groups）与网格属性双线性插值保真。
- **[智能挤出与 UV 修复系统 (Auto Extrude Repair)](mesh/extrude_repair.md)**：
  - 侧面 UV 塌陷成因与三种修复模式（`SMART`、`INWARD`、`OUTWARD`）。
  - 图集跨界防溢色安全裁剪、边缘折痕保护（Mean Crease = 1.0）与随机挤出（Random Extrude）噪声算法。
- **[体素点云网格持久化存储规范 (Voxel Point Cloud Storage)](mesh/voxel_point_cloud.md)**：
  - 强制契约：任何从体素构建的网格对象必须在子级挂载全量点云网格（`ensure_voxel_child_cloud`）。
  - 父子 1:1 本地空间对齐、同集合挂载与原生 Mask Modifier 视口隐蔽机制。
  - 双向对象解析（`get_associated_voxel_cloud`, `get_associated_parent_mesh`）与用户雕刻反向网格化流程。
- **[网格与 UV 实用工具集 (Mesh & UV Tools)](mesh/tools.md)**：
  - 清除自定义分割法线（Clear Custom Normals）、锐边与硬边选择、UV 原地独立缩放（Scale UV Individual）、修复流体 UV、Alpha 智能选面与纹理插值模式一键切换。

---

### 4. 调度与流水线系统 (Modular Step Pipeline)
- **[异步任务与进度调度 (Async Tasks & Progress)](pipeline/step_pipeline.md)**：
  - `AsyncTask` / `ModalTaskRunner` 主线程步进与取消模型。
  - 资产门禁、预编译与状态栏/`wm.progress_*` 双通道进度反馈。

---

### 5. 偏好设置、生态与工程规范 (System & Ecosystem)
- **[偏好设置、右键菜单与工程规范](system/preferences_and_ecosystem.md)**：
  - 右键上下文动态菜单注册与自由重排（支持添加/移除/移动/导入/导出/重置）。
  - 多存储后端配置引擎（`JsonBackend`, `MemoryBackend`, `BlenderBackend`）与原子持久化。
  - Blender 5.0+ Extensions / 原生扩展隔离管理、i18n 国际化字典、自动化构建与双端自动化测试套件。

---

### 6. 底层几何与网络内核 API (libmozitoolkit / libmtk_py)
- **[Rust 内核 API 总览](../../libmozitoolkit/docs/API_REFERENCE.md)**：跨 crate 的公共 API、错误类型与数据布局。
- **[Python 绑定设计](../../libmozitoolkit/docs/BINDINGS_DESIGN.md)**：`libmtk_py` 的 Buffer Protocol、零拷贝与 DNA 直写契约。
- **Crate 级参考**：
  - [mtk-core](../../libmozitoolkit/crates/mtk-core/README.md)、[mtk-voxel](../../libmozitoolkit/crates/mtk-voxel/README.md)、[mtk-cull](../../libmozitoolkit/crates/mtk-cull/README.md)
  - [mtk-model](../../libmozitoolkit/crates/mtk-model/README.md)、[mtk-texture](../../libmozitoolkit/crates/mtk-texture/README.md)、[mtk-resource](../../libmozitoolkit/crates/mtk-resource/README.md)
  - [mtk-material](../../libmozitoolkit/crates/mtk-material/README.md)、[mtk-sync](../../libmozitoolkit/crates/mtk-sync/README.md)、[mtk-save](../../libmozitoolkit/crates/mtk-save/README.md)
  - [libmtk facade](../../libmozitoolkit/crates/libmtk/README.md)、[mtk-py bindings](../../libmozitoolkit/bindings/mtk-py/README.md)、[mtk-ffi](../../libmozitoolkit/bindings/mtk-ffi/README.md)
