# 📋 MoziToolKit (Blender Addon) 开发计划与版本路线图 (Roadmap)

本文档为 `MoziToolKit` Blender 插件前端的功能演进与版本规划清单。底层核心算法、体素流与几何计算见 [`libmozitoolkit/TODO.md`](../libmozitoolkit/TODO.md)。

---

## 📌 版本演进总览 (Milestones Overview)

| 版本 | 阶段定位 | 核心主题与边界 | 状态 |
| :--- | :--- | :--- | :--- |
| **v2.0 正式版** | **里程碑发版** | **核心世界资产与材质渲染基石 (Production Release)**<br>聚焦世界存档导入、Live Sync 实时同步、小三样网格工具、Biome 3D 染色、CTM 规则与**动画材质端到端闭环**，交付 100% 稳定开箱即用的高保真视觉与极速体验。 | 🚀 **收官冲刺中 (RC)** |
| **v2.1** | **次级大版本** | **Mine-imator 深度集成、通用动作重定向与高级实体 (Animation Ecosystem)**<br>以 Mine-imator 2.0 官方源码为参考底座，深度重构 `mi2bl`；构建**临时参考骨骼 + 通用动作重定向引擎**（直通 Rig2 / Ice Cube / BPS / Thomas）；攻坚 1.21.4+ 铜像 Special Renderers 模型、原版悬挂实体与 `.mtkscene`。 | 📋 **规划排期中** |
| **v2.2** | **高级生产力** | **从资产到代码：通用面部绑定系统与全能创作套件 (Universal Rigging & Tools)**<br>将 Blend shapes 映射解耦为通用代码规范（支持 Rig2 / Ice Cube / BPS / Thomas 等人模）；Rust 后端处理网络与滤波；交互式 2D 俯视微缩地图选区器；建筑蓝图 (`.litematic` / `.schematic`) 导入；GeckoLib 双向动画协同。 | 📋 **规划排期中** |
| **v2.3+** | **万能工作流** | **创作者全能生态 (Universal Creator Suite)**<br>角色皮肤 3D 立体挤出与预设 Rig 库、Mine-imator HLSL 渲染特性 1:1 复刻、原版环境日夜天空盒与渲染预设。 | 🔮 **远景规划** |

---

## 🎯 v2.0 正式版：核心世界资产与材质渲染基石 (收官冲刺 🚧)

> **2.0 发版铁律**：严守核心世界与材质闭环，不留半成品。未完成的扩展性需求坚决推迟至 2.1。

### 1. 动画材质系统端到端串联 (P0 - 2.0 终局冲刺项 🚧)
- [ ] **导入与偏好设置开关集成**
  - [ ] 插件偏好设置 (Preferences) 增加全局默认开关 `enable_animated_textures: BoolProperty(name="Animated Textures", default=True)`；
  - [ ] 存档导入操作符 (`mtk.import_minecraft_save`) 弹窗面板增加 `enable_animated_textures` 局部覆盖选项；
- [ ] **“静态图集保底 + 动态材质专用寻址”双通道路由机制**
  - [ ] **静态图集全覆盖保底 (Fallback Baseline)**：
    - 预烘焙静态图集已包含全部材质（包括动态纹理的 Frame 0 静态表示）；
    - 当用户禁用动画材质时：网格全量映射至静态图集材质（`MTK:Atlas:blocks:001` 等），Shader 零额外计算开销，保证极致视口流畅度；
  - [ ] **动态材质专用寻址 (Dynamic Material Routing)**：
    - 当用户启用动画材质时：识别带动画元数据（`is_animated: true`）的方块面（如水流、熔岩、火、下界传送门、海晶石等）；
    - 专门将其材质槽与 UV 重定向至动态材质（`MTK:Atlas:blocks:anim:001`）；
    - 在该材质节点树中自动连通 [utils/node_groups/animated.py](utils/node_groups/animated.py) 的 `MC_Animated_UV_Mapping`、`MC_Animation_Scheduler_Default` 与 `MC_Animated_Frame_Blend` 节点组；
    - 绑定 Blender 时间线驱动（`frame_current`），实现与 MC Tick Rate (20 TPS) 对齐的实时帧播放与双帧插值混合。

### 2. 存档导入容器化与稳定性闭环 (✅ 已完成)
- [x] **Minecraft 存档端到端导入前端 (`operators/save/op_import_save.py`, `bridge/save.py`)**
  - [x] 顶部主菜单接入（`File -> Import -> Minecraft World / Save (.mca / level.dat)`）；
  - [x] 修复导入按钮调用 ID (`mtk.import_minecraft_save`)；
  - [x] 世界路径选取、维度选择（主世界/下界/末地）与 `level.dat` 元数据探测；
  - [x] 3D 轴对齐选区坐标输入与方块体积统计；
  - [x] 独立 Empty 根容器化（`Save_WorldName_Dimension_01`），多选区自动递增序号新建容器；
  - [x] 本地隐私注册表管理器（`save_registry.json`），工程内仅存 UUID，杜绝本地路径随工程泄露；
  - [x] 专属信息面板卡片与“🔄 刷新模型 (Refresh Model)”原地无感重构算子。

### 3. 胶水层智能按需预烘焙门禁 (✅ 已完成)
- [x] **自动前置资产校验与热重载 (`bridge/assets.py`)**
  - [x] 门禁机制：未就绪或材质包变更时，自动两阶段流水线先烘焙再执行导入/同步；
  - [x] 涵盖存档导入、刷新、Live Sync 连接/重构、通用网格重构各核心入口；
  - [x] 彻底杜绝首次导入出现无 UV 灰模问题。

### 4. 真实生态 3D Biome 染色与平滑过渡管线 (✅ 已完成)
- [x] **真实 3D Quart Biome 染色采样**
  - [x] 接入 Rust 核心 3D 生物群系面域 Tint（沼泽特异水色/斑驳双色草、热带雨林、黑森林、恶地等）；
  - [x] 5×5 (R=2) 原版均匀盒式平滑过渡核（Uniform Box Filter）与 Colormap UV 插值；
  - [x] 着色器节点树自适应适配 Cycles 与 Eevee Next。

### 5. CTM 连接纹理端到端验证 (✅ 已完成)
- [x] **OptiFine / Continuity CTM 规则与图集解算**
  - [x] 偏好设置与导入选项提供 `enable_ctm` 复选框；
  - [x] 验证连续玻璃、连续书架、平滑石材的 47-tile 拓扑解算与 UV 渲染，杜绝单像素塌陷。

### 6. 现代 Blender 5.0+ 零拷贝与批写入现代化 (✅ 已完成)
- [x] **Rust $\leftrightarrow$ Blender 内存直接写入管道**
  - [x] Tier 1 直接指针直写 (`direct_copy_*_to_ptr`)；
  - [x] Tier 2 通用属性（Generic Attributes）向量化批量灌入；
  - [x] 字符串面属性“调色板化（Palette Indexing）”改造；
  - [x] 几何写入总耗时提速 38x~900x。

### 7. 小三样核心网格与 UV 工具库 (✅ 已完成)
- [x] 自适应像素网格切分 (`op_pixel_split.py`)；
- [x] 智能挤出与 UV 修复系统 (`operators/extrude/`，SMART / INWARD / OUTWARD 模式，实时 Depsgraph 监听)；
- [x] 外部网格面遮挡剔除 (`op_cull.py`，6 向邻域分析)。

### 8. 实时网络同步 (Live Sync) 会话生命周期 (✅ 已完成)
- [x] 伴生体素点云子物体结构与 Empty 根容器平铺统一层级；
- [x] 跨工程深度清理钩子（`load_pre` / `load_post`，切断 TCP 并清理定时器）；
- [x] 多会话并行隔离与防串流。

### 9. v2.0 正式发版验证与打包测试 (P0 🚧)
- [ ] 运行 `python3 build.py` 验证发布包：
  - [ ] 确保自动物理剔除 `dev/` 开发模块；
  - [ ] 确保 `blender_manifest.toml` 包含正确的 abi3 wheel 声明；
  - [ ] 验证发布包安装于全新纯净 Blender 4.2+ / 5.2+ 宿主无报错；
- [x] Mock 测试门禁通过（205 passed / 71 skipped）；
- [ ] Blender 宿主测试门禁验证（`blender --background --python tests/run_tests.py`）。

---

## 🚀 v2.1 版本：Mine-imator 深度集成、通用动作重定向与高级实体 (规划排期中 📋)

> **2.1 版本主题**：以官方停更的 Mine-imator 2.0 源码为权威参考，构建“临时参考骨骼 + 通用动作重定向”管道，将角色动作自由映射到 Rig2 / Ice Cube / BPS / Thomas 等主流人模，并攻坚 1.21.4+ 客户端特殊模型与场景交换。

### 1. Mine-imator 深度集成与全能动作重定向管线 (`mi2bl` Retargeting Pipeline - P1 核心 🌟)
- [ ] **Mine-imator 2.0 官方源码参考与逆向分析**
  - [ ] 基于已克隆的稳定 Mine-imator 2.0 源码，提取核心数学与渲染规范；
  - [ ] 剖析 MI 着色器特性（HLSL/GLSL 自发光、卡通描边、次表面散射、高光粗糙度换算、Alpha Blend/Hash）；
  - [ ] 剖析关键帧过渡曲线（Linear, Instant, Bézier 速度与张力参数算法）；
  - [ ] 剖析摄像机物理参数（FOV、景深焦距/光圈、散景叶片、Camera Shake 随机噪声）；
  - [ ] 剖析灯光能量换算（Strength × Range² × 4π 物理辐射照度映射）；
- [ ] **MI 标准临时参考骨骼 (Template Intermediate Armature)**
  - [ ] 导入 `.miproject` / `.miobject` / `.miframes` 时，在 Blender 现场动态构建 1:1 对齐 Mine-imator 关节命名与层级的标准临时骨骼；
  - [ ] 将 MI 原始关键帧无损灌入该参考骨骼，原汁原味还原动作与时间线；
- [ ] **通用动作重定向引擎 (Universal Minecraft Action Retargeting Engine)**
  - [ ] 建立基于中间标准的**骨骼重定向映射表 (Bone Retargeting Profiles)**；
  - [ ] 预置主流人模映射 Profile：
    - **Rig2** (Mozi 家族专属 Rig)
    - **Ice Cube** (经典传奇人模)
    - **BPS** (Black Plasma Studios 人模)
    - **Thomas** (Thomas's Rig 系列)
    - **Custom Armature** (用户自定义骨骼交互式配准)；
  - [ ] 支持一键将临时参考骨骼的 Action 动作重定向、解算轴心偏移并烘焙为目标人模的 FK/IK 动作；
  - [ ] 动作重定向完成后支持一键安全清理/隐藏临时中介骨骼；
- [ ] **场景材质与物理相机一键映射**
  - [ ] 将 MI 的材质轨道（`alpha`, `emissive`, `metallic`, `roughness`, `subsurface`）转换为 Blender Principled BSDF 节点树；
  - [ ] 生成对齐 MI 渲染特性的物理摄像机与 Cycles/Eevee 灯光阵列。

### 2. 1.21.4+ 客户端特殊模型攻坚 (Special Renderers & Copper Golem Statue) (P1)
- [ ] **解析客户端模型新规范 (`mtk-model::special`)**
  - [ ] 攻坚 Minecraft 1.21.4+ Item/Block Model Definitions 中的 `"type": "minecraft:special"` 与 `"type": "minecraft:select"` 语法；
- [ ] **铜像 / 铜傀儡像 (Copper Golem Statue) 网格重构**
  - [ ] 解决铜像在缺少传统 `"elements"` 字段时的网格丢失问题；
  - [ ] 内置铜傀儡像 4 种氧化态（未氧化、斑驳、锈蚀、完全氧化）与各姿态（standing, sitting, running, star）的盒模型几何拓扑与贴图映射。

### 3. 原版静态与悬挂实体导入系统 (P1)
- [ ] **艺术画 (Painting) 前端构建器 (`bridge/entity.py`, `operators/save/`)**
  - [ ] 从存档数据读取 `PaintingEntity`（`variant`, `facing`, `pos`）；
  - [ ] 生成规整的 1x1 ~ 4x4 原版三维画框带木质背板，绑定对应画作贴图；
- [ ] **物品展示框 (Item Frame & Glow Item Frame)**
  - [ ] 解析展示框外壳与发光边框，处理 45° `ItemRotation` 与 `Invisible` 隐形状态；
  - [ ] 内容物自适应装配：方块模型、平面切分挤出物品模型、或地图无框平坦面；
- [ ] **填充地图 (Filled Map Data) 像素图像解码**
  - [ ] 对接 Rust 导出的 128×128 RGBA8 像素缓冲，现场生成 Blender Image Datablock 并赋材质；
- [ ] **盔甲架 (Armor Stand) 支架与装备挂载**
  - [ ] 导入木质支架骨架与 `Pose` 姿态角度，挂载手持与穿戴装备。

### 4. 复杂方块实体 NBT 图元与动画分体铰链装配 (P2)
- [ ] **告示牌与悬挂告示牌文字生成器 (Sign Text)**
  - [ ] 读取 `front_text` / `back_text`，生成文字网格或高保真纹理投影，支持 16 色染料与发光墨囊；
- [ ] **旗帜多层花纹合成 (Banner Patterns)**
  - [ ] 依照原版 40+ 种图案公式与 16 种颜色按 NBT 顺位合成多层 Alpha 纹理；
- [ ] **动画铰链分体装配选项 (Animation-Ready Hierarchy)**
  - [ ] 提供“分离可动部件”选项：门（Door）、栅栏门（Fence Gate）、箱子顶盖（Chest Lid）、钟体（Bell Body）生成为独立子物体；
  - [ ] 精确放置铰链旋转中心（Pivot Point），方便动画师直接设置旋转关键帧。

### 5. 自包含轻量场景交换包 (`.mtkscene`) (P2)
- [ ] **场景交换格式导入导出算子 (`operators/package/`)**
  - [ ] 顶部菜单集成：`File -> Import/Export -> MoziToolKit Scene Package (.mtkscene)`；
  - [ ] 导出端自动 Tree-shaking 剪枝，仅打包选区内实际引用的独立贴图与方块模型；
  - [ ] 导入端现场动态重构世界几何与材质节点树。

---

## 🛠️ v2.2 版本：从资产到代码：通用面部绑定与高级创作者工具 (规划排期中 📋)

> **2.2 版本主题**：将 `rig2_addons` 沉淀的资产能力抽象为通用代码规范；构建多模型适配的面部绑定系统；Rust 处理网络与滤波；提供 2D 小地图与建筑蓝图支持。

### 1. 通用 Minecraft 面部绑定与驱动系统 (Universal Facial Engine - P1 核心 🌟)
- [ ] **从资产强绑定解耦为通用代码规范**
  - [ ] 彻底摆脱对特定 Rig 内部 Driver 资产的硬依赖，将 ARKit 52 Blendshapes 映射抽象为代码层可配置的骨骼变换映射表 (Mapping Schema)；
  - [ ] 建立标准数据流：`Blendshape Weights (0..1) -> Mapping Rules (Translation/Rotation/Scale) -> Bone Pose Channels`；
- [ ] **主流人模全覆盖预设 Profile (Universal Rig Support)**
  - [ ] 预置 **Rig2** 面部骨骼映射 Profile；
  - [ ] 预置 **Ice Cube** 面部骨骼映射 Profile；
  - [ ] 预置 **BPS** 面部骨骼映射 Profile；
  - [ ] 预置 **Thomas** 面部骨骼映射 Profile；
  - [ ] 提供可视化映射编辑器：允许用户针对任意自定义 Minecraft 骨骼拾取骨骼并标定极值偏移行程；
- [ ] **一键装配模式 vs 实时驱动模式**
  - [ ] **一键装配模式 (Generate Drivers)**：根据选定 Profile，一键在目标 Armature 上生成原生 Blender Driver，永久脱离插件独立工作；
  - [ ] **实时驱动模式 (Live Motion Stream)**：无需修改绑定，实时将面部动作直接写入 PoseBone，支持一键烘焙关键帧；
- [ ] **Rust 高性能网络与平滑滤波后端 (`mtk-face` / `mtk-net`)**
  - [ ] 原生 Rust 实现 LiveLinkFace (UDP 11111) 与 WebSocket 高并发无锁数据包监听；
  - [ ] 集成 One Euro Filter 与卡尔曼滤波，消除面捕抖动与网络丢包卡顿；
  - [ ] 头部姿态四元数解算与零延迟桥接进 Blender。

### 2. GeckoLib 动画双向协同 (`.animation.json`) (P2)
- [ ] **Rig2 / 通用骨骼导出至 Blockbench / GeckoLib**
  - [ ] 继承并重构 `rig2_addons` 的 R2BB 引擎，支持将 Blender Action 导出为标准 GeckoLib 1.8.0 格式；
  - [ ] 支持轴向反转、关键帧去重压缩与时间线归一化；
- [ ] **GeckoLib 动画导入至 Blender**
  - [ ] 支持读取 `.animation.json` 并重定向至 Rig2 / Thomas / BPS 骨骼。

### 3. 交互式 2D 俯视微型地图选区器 (Interactive 2D Minimap Selector) (P1)
- [ ] **可视化世界选区面板**
  - [ ] 告别纯数字 AABB 坐标输入；
  - [ ] 基于 Rust 后端快速渲染 2D 俯视地形与群系切片，提供视口弹窗点击拖拽框选。

### 4. 建筑投影与蓝图文件直接导入 (`.litematic` / `.schematic` / `.nbt`) (P1)
- [ ] **蓝图一键转网格**
  - [ ] 无需先将建筑导入世界存档，直接在 Blender 中单选 `.litematic` 文件；
  - [ ] 现场生成带完整材质、CTM 与 Biome 的自包含建筑网格。

---

## 🔮 v2.3+ 远景：万能创作者全能生态 (Future Vision)

- [ ] **玩家角色与原版生物绑定库 (Character Rig & Skin Tools)**
  - 玩家皮肤一键贴图与 64×64 双层外皮 3D 立体切分挤出；
  - 内置经典角色与常用原版生物（苦力怕、僵尸、骷髅、末影人）基础 FK/IK 骨骼绑定。
- [ ] **Mine-imator 渲染特性 1:1 深度复刻预设**
  - 深入 Mine-imator 2.0 官方源码的 HLSL 着色器，精确复刻其光影衰减、高光反光率与卡通轮廓。
- [ ] **环境氛围与渲染辅助工具集 (Atmosphere & Render Presets)**
  - 原版日夜循环天空盒节点树（动态太阳、月相与体积云朵方块层）；
  - Cycles / Eevee Next 一键渲染优化预设（AgX 色彩管理、景深与采样率自动化）。
