# MoziToolKit 技术文档与设计规范导航

欢迎查阅 **MoziToolKit** 的模块化设计与技术规范文档。为降低阅读和开发时的上下文开销，本文档库已按功能域进行了模块化拆分。

---

## 快速导航与模块索引

### 1. 架构总览与防回归哲学 (Architecture & Principles)
- **[架构总览与设计原则](architecture/overview.md)**：包含插件的分层架构图（UI 层、Pipeline 调度层、Engine 引擎层、System 基础层）以及全项目不可违背的四大核心设计哲学。
- **[核心设计决策与防回归 FAQ 对照表](architecture/faq_anti_regression.md)**：列举了草方块侧面染色、动画贴图正方形截断、jmc2obj 连续平铺 UV 等常见易被误判为 Bug 的既定设计特征对照表。

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
- **[实时同步网络传输协议规范 (Live Sync Protocol)](live_sync/live_sync_protocol.md)**：
  - Minecraft <-> DCC 完整的二进制帧头、数据包类型清单（S2C/C2S）。
  - 选区拖拽释放时提交（Commit-on-Release）与握手时序。
  - 单方块微操作与大批量更新自动分流规范。
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
- **[网格与 UV 实用工具集 (Mesh & UV Tools)](mesh/tools.md)**：
  - 清除自定义分割法线（Clear Custom Normals）、锐边与硬边选择、UV 原地独立缩放（Scale UV Individual）、修复流体 UV、Alpha 智能选面与纹理插值模式一键切换。

---

### 4. 调度与流水线系统 (Modular Step Pipeline)
- **[模块化流水线系统 (Step Pipeline)](pipeline/step_pipeline.md)**：
  - `Step ↔ Context ↔ Pipeline` 契约模型与结构化 `StepResult`。
  - 通用模态调度算子（`mozi.modal_pipeline_runner`）、3D 视口 Header 进度条与状态栏双通道反馈。
  - 预设流水线编排（Presets，含预编译缓存 `StepPrecompileCache`）。

---

### 5. 偏好设置、生态与工程规范 (System & Ecosystem)
- **[偏好设置、右键菜单与工程规范](system/preferences_and_ecosystem.md)**：
  - 右键上下文动态菜单注册与自由重排（支持添加/移除/移动/导入/导出/重置）。
  - 多存储后端配置引擎（`JsonBackend`, `MemoryBackend`, `BlenderBackend`）与原子持久化。
  - Blender 4.2+ Extensions / Python Wheels 隔离管理、i18n 国际化字典、自动化构建与 54 个全量 CI 测试套件。

