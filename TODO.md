# 📋 MoziToolKit (Blender Addon) 开发计划与版本路线图 (Roadmap)

本文档为 `MoziToolKit` Blender 插件前端的功能演进与版本规划清单。底层核心算法、体素流与几何计算见 [`libmozitoolkit/TODO.md`](../libmozitoolkit/TODO.md)。实时协同服务端见 [`yefira/GEMINI.md`](../yefira/GEMINI.md)。

---

## 📌 版本演进总览 (Milestones Overview)

| 版本 | 阶段定位 | 核心主题与边界 | 状态 |
| :--- | :--- | :--- | :--- |
| **v2.0 基础发版** | **核心基石** | **核心世界资产与材质渲染基石 (Production Release)**<br>世界存档导入、Live Sync 实时同步、小三样核心工具、Biome 3D 染色、CTM 规则与静态/动态双图集端到端闭环。 | ✅ **完成交付 (2026-10-18)** |
| **v2.0 架构淬炼** | **纯净化里程碑** | **B0–B7 架构大收敛、预解码 PBR 材质与原生三端闭环 (Hardened Milestone)**<br>完成系统级 B0–B7 架构大清理；剥离独立 `libmtk_blender_dna` 适配器；原生 C++/Rust 像素切分（Quads 重构）；PBR 图集预解码全面上线，彻底物理清除 LabPBR 运行时生成器与 `mtk_material_props`；打通全链路诊断探针；强制原版客户端资产门禁；Yefira Protocol v3 闭环与 6 平台 Wheels 构建矩阵。 | ✅ **全面达成 (2026-10-21)** |
| **v2.1** | **次级大版本** | **Mine-imator 深度集成、通用动作重定向与高级实体 (Animation Ecosystem)**<br>以 Mine-imator 2.0 官方源码为底座，重构 `mi2bl`；构建**临时参考骨骼 + 通用动作重定向引擎**（直通 Rig2 / Ice Cube / BPS / Thomas）；攻坚 1.21.4+ 铜像 Special Renderers 模型、原版悬挂实体与自包含场景交换包 (`.mtkscene`)。 | 📋 **启动推进中** |
| **v2.2** | **高级生产力** | **从资产到代码：通用面部绑定系统与全能创作套件 (Universal Rigging & Tools)**<br>将 Blend shapes 映射解耦为通用代码规范（支持 Rig2 / Ice Cube / BPS / Thomas 等人模）；Rust 后端处理网络与滤波；交互式 2D 俯视微缩地图选区器；建筑蓝图 (`.litematic` / `.schematic`) 导入；GeckoLib 双向动画协同。 | 📋 **规划排期中** |
| **v2.3+** | **万能工作流** | **创作者全能生态 (Universal Creator Suite)**<br>角色皮肤 3D 立体挤出与预设 Rig 库、Mine-imator HLSL 渲染特性 1:1 复刻、原版环境日夜天空盒与渲染预设。 | 🔮 **远景规划** |

---

## 🏆 近期重大架构跃迁：v2.0 架构淬炼战役 (2026-10-18 ~ 2026-10-21)

> 详细设计与执行记录参见：
> - [`docs/planning/2026-10-20_deletion_and_surface_cleanup.md`](docs/planning/2026-10-20_deletion_and_surface_cleanup.md) (B0–B7 计划)
> - [`docs/planning/2026-10-21_legacy_material_isolation.md`](docs/planning/2026-10-21_legacy_material_isolation.md) (材质清洗记录)

### 1. B0–B7 架构大清理战役 (✅ 全部通过验证)
- [x] **B0：基准快照与自动化冒烟守护**：记录 184 原生 API 与 344 项测试基线，建立零回归守护网。
- [x] **B1：剔除废弃菜单操作符与注册表垫片**：清除无用操作符与 legacy registry shims。
- [x] **B2：胶水层虚假降级与旧轮子回退彻底归零**：删除 Python bridge fake 分支，杜绝运行时“静默吞错”与假数据污染。
- [x] **B3：Rust 核心零调用方绑定与废弃管线收敛**：删除 Python 未消费的 47 个绑定方法，`libmtk` 从 175 符号收敛至 9 个核心符号，彻底废弃 `mtk-ffi`。
- [x] **B4：物理剔除遗留 `unified_mesh` 胶水与废弃格式**。
- [x] **B5：收敛网格与体素点云数据模型**：全面统一为基于调色板索引（Palette）的内存高效表达。
- [x] **B6：API 握手契约与业务编排彻底归位**：网格创建、集合装配、材质节点生成等宿主逻辑全部移入 `utils/`，`bridge/` 彻底纯化为纯数据转换桥梁；全面暴露 Palette Biome APIs。
- [x] **B7：拆分宿主内存适配器为独立 Wheel**：Blender C++ 内存直写被剥离为独立的 `libmtk_blender_dna` wheel，计算核保持 100% 宿主无关。

### 2. 材质管线现代化与旧实现物理清除 (✅ 全部完成)
- [x] **PBR 图集预解码全面接管**：Rust 预编译期（`ASSET_CACHE_FORMAT_VERSION = 4`）将 LabPBR 解码为规范图集通道（Albedo, Normal_GL, Roughness, Metallic, Aux/Emission），丢弃原始 `_n` / `_s`。
- [x] **彻底删除 `mtk_material_props`**：移除物理属性注册表、`properties_config.py` 与外部 JSON，移除逐面材质属性字符串展开，每面少存一份 Float4。
- [x] **着色器现代化**：前端着色器全面适配原生 Principled BSDF，节点图全面迁移至现代 `ShaderNodeMix`（彻底消除过时的 `ShaderNodeMixRGB` 与 `use_nodes = True` 警告）。
- [x] **材质视觉回归测试框架**：增加 `test(material): add legacy-vs-baked visual regression harness`，保障材质渲染 100% 视觉对齐。

### 3. 原生 C++/Rust 几何切分与拓扑修复 (✅ 全部完成)
- [x] **移除 Python 切分降级**：自适应像素网格切分 (`op_pixel_split.py`) 全面交由原生底层驱动。
- [x] **切片三角形转 Quads**：像素切分后的网格三角面自动重构为规范四边形，优化视口与着色。
- [x] **任意旋转像素切片与 UV 修复**：解决带旋转网格切片时的 UV 扭曲问题；统一动画长条贴图截断。

### 4. 全链路执行诊断与探针体系 (✅ 全部完成)
- [x] Rust 核心与 Python 前端 (`bridge/diagnostics.py`) 全链路接入执行探针。
- [x] 操作符报告中拆分并输出 Rust 耗时与 Blender 宿主耗时，消除黑盒。

### 5. 权威原版客户端资产门禁 (✅ 全部完成)
- [x] 强制校验真正的 Minecraft 原版客户端资产（JAR / 解包目录），杜绝因资产缺失导致的无 UV 灰模。

### 6. Live Sync 实时协同 Protocol v3 闭环 (✅ 全部完成)
- [x] 与 `yefira` 伴生模组全面对接 Protocol v3：XXHash64 校验自愈、增量分片批量推送、选区原子化与软限制。
- [x] 客户端支持安全 Token 鉴权与 Loopback 本地连接免密直连。
- [x] 握手决策码 (`decision_code`) 与进度归一化由 Rust 权威掌控。

### 7. 6 平台 Native Wheels 自动化构建与发布矩阵 (✅ 全部完成)
- [x] Windows x64, macOS (arm64/x64), Linux (glibc/musl) CI 验证全绿，支持 rolling release 自动注入。

---

## 🧭 当前待办与持续优化清单

### 📋 性能持续微调
- [ ] **1M faces 渲染与导入进一步优化**：进一步减少 source-key 展开，推进全流程 Palette-native 优化。
- [ ] **C-ABI 独立头文件（可选/按需）**：按 C4D 或独立查看器实际需求提供轻量级 C-ABI 头文件示例。

---

## 🎯 v2.0 正式版：核心世界资产与材质渲染基石 (✅ 已交付并淬炼)

### 1. 动画材质系统端到端串联 (✅ 已完成)
- [x] 偏好设置与导入面板提供 `enable_animated_textures` 选项；
- [x] “静态图集保底 + 动态图集专用寻址”双通道机制；
- [x] 时间线驱动与双帧插值混合。

### 2. 存档导入容器化与稳定性闭环 (✅ 已完成)
- [x] 顶部主菜单接入（`File -> Import -> Minecraft World / Save (.mca / level.dat)`）；
- [x] 3D 轴对齐选区坐标输入与方块体积统计；
- [x] 独立 Empty 根容器化与多选区自动递增；
- [x] 本地隐私注册表（UUID 存储，防工程泄漏本地路径）；
- [x] “🔄 刷新模型 (Refresh Model)”原地无感重构算子。

### 3. 真实生态 3D Biome 染色与平滑过渡管线 (✅ 已完成)
- [x] 真实 3D Quart Biome 染色采样（沼泽特异水色、双色草、热带雨林、黑森林等）；
- [x] 5×5 原版均匀盒式平滑滤波；
- [x] Rust 扁平 memoryview 零拷贝直写（498k faces 耗时降至 ~2.1 ms）。

### 4. CTM 连接纹理端到端验证 (✅ 已完成)
- [x] OptiFine / Continuity 47-tile 拓扑解算与 UV 渲染。

### 5. 现代 Blender 5.0+ 零拷贝内存直写 (✅ 已完成)
- [x] 独立 `libmtk_blender_dna` 实现硬件带宽级连续内存拷贝；
- [x] 通用属性（Generic Attributes）向量化批量灌入与 Palette 调色板化。

### 6. 小三样核心网格与 UV 工具库 (✅ 已完成)
- [x] 自适应像素网格切分 (`op_pixel_split.py`)；
- [x] 智能挤出与 UV 修复系统 (`operators/extrude/`)；
- [x] 外部网格面遮挡剔除（`op_cull.py` 已彻底废弃并移除，面遮挡判定全面收敛至权威体素级 `FaceCuller`）。

---

## 🚀 v2.1 版本：Mine-imator 深度集成、通用动作重定向与高级实体 (📋 启动推进中)

> **2.1 版本主题**：以官方停更的 Mine-imator 2.0 源码为权威参考，构建“临时参考骨骼 + 通用动作重定向”管道，将角色动作自由映射到 Rig2 / Ice Cube / BPS / Thomas 等主流人模，并攻坚 1.21.4+ 客户端特殊模型与场景交换包。

### 1. Mine-imator 深度集成与全能动作重定向管线 (`mi2bl` - P1 核心 🌟)
- [ ] **Mine-imator 2.0 官方源码参考与逆向分析**
  - [ ] 剖析关键帧过渡曲线（Linear, Instant, Bézier 速度与张力参数算法）；
  - [ ] 剖析摄像机物理参数（FOV、景深焦距/光圈、散景叶片、Camera Shake 随机噪声）；
  - [ ] 剖析灯光能量换算（Strength × Range² × 4π 物理辐射照度映射）；
- [ ] **MI 标准临时参考骨骼 (Template Intermediate Armature)**
  - [ ] 导入 `.miproject` / `.miobject` / `.miframes` 时现场动态构建 1:1 对齐 Mine-imator 关节命名与层级的标准临时骨骼；
  - [ ] 将 MI 原始关键帧无损灌入该参考骨骼；
- [ ] **通用动作重定向引擎 (Universal Minecraft Action Retargeting Engine)**
  - [ ] 预置主流人模映射 Profile：**Rig2**, **Ice Cube**, **BPS**, **Thomas**, **Custom Armature**；
  - [ ] 一键重定向、解算轴心偏移并烘焙为目标人模的 FK/IK 动作；
  - [ ] 动作重定向完成后一键安全清理/隐藏临时中介骨骼；
- [ ] **场景材质与物理相机一键映射**
  - [ ] 将 MI 材质轨道转换为标准 Principled BSDF 节点树；
  - [ ] 生成对齐 MI 渲染特性的物理摄像机与 Cycles/Eevee 灯光阵列。

### 2. 1.21.4+ 客户端特殊模型攻坚 (Special Renderers & Copper Golem Statue) (P1)
- [ ] **解析客户端模型新规范 (`mtk-model::special`)**
  - [ ] 支持 `"type": "minecraft:special"` 与 `"type": "minecraft:select"` 语法；
- [ ] **铜像 / 铜傀儡像 (Copper Golem Statue) 网格重构**
  - [ ] 解决铜像在缺少传统 `"elements"` 字段时的网格丢失；
  - [ ] 内置铜傀儡像 4 种氧化态与各姿态盒模型几何与贴图映射。

### 3. 原版静态与悬挂实体导入系统 (P1)
- [ ] **艺术画 (Painting) 前端构建器 (`bridge/entity.py`)**：生成带木质背板的三维画框网格；
- [ ] **物品展示框 (Item Frame & Glow Item Frame)**：支持 45° 旋转、隐形状态与内部物品装配；
- [ ] **填充地图 (Filled Map Data) 像素图像解码**：对接 Rust 导出的 128×128 RGBA8 像素流，现场生成贴图并赋材质；
- [ ] **盔甲架 (Armor Stand)**：导入支架骨架与 `Pose` 姿态角度，挂载装备。

### 4. 复杂方块实体 NBT 图元与动画分体铰链装配 (P2)
- [ ] **告示牌与悬挂告示牌文字生成器 (Sign Text)**：支持 16 色染料与发光墨囊；
- [ ] **旗帜多层花纹合成 (Banner Patterns)**：按原版公式进行多层 Alpha 顺位合成；
- [ ] **动画铰链分体装配选项**：门、栅栏门、箱子顶盖、钟体生成为独立子物体并预留精确轴心。

### 5. 自包含轻量场景交换包交互 (`.mtkscene`) (P2)
- [ ] **导出端 (`Export -> MTK Scene Interchange (.mtkscene)`)**：按需提取最小依赖模型与独立贴图闭包（Tree-shaking），稀疏体素单文件打包；
- [ ] **导入端与现场重构 (`Import -> MTK Scene Interchange (.mtkscene)`)**：极速读取单文件并重构世界几何。

---

## 🛠️ v2.2 版本：通用面部绑定系统与全能创作套件 (📋 规划排期中)

### 1. 通用 Minecraft 面部绑定与驱动系统 (Universal Facial Engine - P1 核心 🌟)
- [ ] **从资产强绑定解耦为通用代码规范**：将 ARKit 52 Blendshapes 抽象为通用骨骼变换映射表；
- [ ] **主流人模全覆盖预设 Profile**：Rig2, Ice Cube, BPS, Thomas 及可视化映射编辑器；
- [ ] **一键装配模式 vs 实时驱动模式**：生成原生 Blender Driver 或实时写入 PoseBone；
- [ ] **Rust 高性能网络与平滑滤波后端 (`mtk-face` / `mtk-net`)**：LiveLinkFace (UDP 11111) 与 WebSocket 异步接收，One Euro Filter 抗抖动。

### 2. GeckoLib 动画双向协同 (`.animation.json`) (P2)
- [ ] Rig2 / 通用骨骼导出至 Blockbench / GeckoLib；
- [ ] GeckoLib 动画导入至 Blender 并重定向至主流骨骼。

### 3. 交互式 2D 俯视微型地图选区器 (Interactive 2D Minimap Selector) (P1)
- [ ] 基于 Rust 后端渲染 2D 俯视地形与群系切片，提供视口拖拽框选。

### 4. 建筑投影与蓝图文件直接导入 (`.litematic` / `.schematic` / `.nbt`) (P1)
- [ ] 直接解包 Litematica 区域并现场生成带完整材质、CTM 与 Biome 的建筑网格。

---

## 🔮 v2.3+ 远景：万能创作者全能生态 (Future Vision)

- [ ] 玩家角色与原版生物绑定库（皮肤 3D 双层立体挤出与预设 Rig）；
- [ ] Mine-imator 渲染特性 1:1 深度复刻预设（光影衰减、高光反光率、卡通描边）；
- [ ] 原版环境日夜循环天空盒节点树与渲染优化预设。
