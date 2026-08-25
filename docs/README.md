# MoziToolKit 技术文档与设计规范导航

欢迎查阅 **MoziToolKit** 的模块化设计与技术规范文档。为降低阅读和开发时的上下文开销，本文档库已按功能域进行了模块化拆分。

---

## 快速导航与模块索引

### 1. 架构总览与防回归哲学 (Architecture & Principles)
- **[架构总览与设计原则](file:///Users/jaxlocke/Desktop/MoziToolKit/docs/architecture/overview.md)**：包含插件的分层架构图（UI 层、Pipeline 调度层、Engine 引擎层、System 基础层）以及全项目不可违背的四大核心设计哲学。
- **[核心设计决策与防回归 FAQ 对照表](file:///Users/jaxlocke/Desktop/MoziToolKit/docs/architecture/faq_anti_regression.md)**：列举了草方块侧面染色、动画贴图正方形截断、jmc2obj 连续平铺 UV 等常见易被误判为 Bug 的既定设计特征对照表。

---

### 2. 材质与模型烘焙系统 (Materials & Model Baking)
- **[材质解析、匹配与替换管线](file:///Users/jaxlocke/Desktop/MoziToolKit/docs/materials/material_pipeline.md)**：
  - 三层物理资源包优先级栈（`RESOURCE_PACK` → `MOD_JAR` → `VANILLA`）与通道级独立级联回退。
  - 多导入器（`jmc2obj`, `Mineways`, `Ice-Cube`, `Generic`）自适应匹配。
  - 双材质构建体系：图集模式（Atlas Mode）与预编译全栈融合独立模式（Standalone Mode）。
  - 图集防溢色数学模型（Padding & Safe Clamp）、生物群系高精度双线性染色、逐帧动态动画（MCMETA）驱动及验收矩阵。
- **[MC 方块模型烘焙引擎 (MC Baker)](file:///Users/jaxlocke/Desktop/MoziToolKit/docs/materials/mc_baker.md)**：
  - Blockstate 变体与 Multipart 复合条件解析。
  - Block Model JSON 继承树展开、`#texture` 变量解析、Cullface 标记、UV 旋转与 Atlas Bridge 桥接。

---

### 3. 网格与建模工具系统 (Mesh & UV Modeling)
- **[原生网格实时同步构建体系 (Direct Mesh)](file:///Users/jaxlocke/Desktop/MoziToolKit/docs/mesh/direct_mesh.md)**：
  - 16x16x16 Section 分块容器、6 向邻域遮挡剔除、拓扑微距焊接。
  - 毫秒级增量更新（Delta Update）与原生多图集 UVMap 写入。
- **[自适应像素网格切分系统 (Adaptive Pixel Split)](file:///Users/jaxlocke/Desktop/MoziToolKit/docs/mesh/pixel_split.md)**：
  - 1 面 = 1 贴图像素自适应分辨率计算。
  - 动画贴图单帧正方形边界识别（避免过度切分）。
  - 骨骼权重（Vertex Groups）与网格属性双线性插值保真。
- **[智能挤出与 UV 修复系统 (Auto Extrude Repair)](file:///Users/jaxlocke/Desktop/MoziToolKit/docs/mesh/extrude_repair.md)**：
  - 侧面 UV 塌陷成因与三种修复模式（`SMART`、`INWARD`、`OUTWARD`）。
  - 图集跨界防溢色安全裁剪、边缘折痕保护（Mean Crease = 1.0）与随机挤出（Random Extrude）噪声算法。
- **[网格与 UV 实用工具集 (Mesh & UV Tools)](file:///Users/jaxlocke/Desktop/MoziToolKit/docs/mesh/tools.md)**：
  - 清除自定义分割法线（Clear Custom Normals）、锐边与硬边选择、UV 原地独立缩放（Scale UV Individual）、修复流体 UV、Alpha 智能选面与纹理插值模式一键切换。

---

### 4. 调度与流水线系统 (Modular Step Pipeline)
- **[模块化流水线系统 (Step Pipeline)](file:///Users/jaxlocke/Desktop/MoziToolKit/docs/pipeline/step_pipeline.md)**：
  - `Step ↔ Context ↔ Pipeline` 契约模型与结构化 `StepResult`。
  - 非阻塞 Modal Timer 交互与进度条报告。
  - 预设流水线编排（Presets）。

---

### 5. 偏好设置、生态与工程规范 (System & Ecosystem)
- **[偏好设置、右键菜单与工程规范](file:///Users/jaxlocke/Desktop/MoziToolKit/docs/system/preferences_and_ecosystem.md)**：
  - 右键上下文菜单动态注册与自由重排。
  - JSON 偏好配置防丢失与原子序列化。
  - Blender 4.2+ Extensions / Python Wheels 隔离管理、i18n 国际化字典、自动化构建与 CI 测试套件。
