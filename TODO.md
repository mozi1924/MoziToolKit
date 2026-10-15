# 📋 MoziToolKit (Blender Addon) 开发计划与版本路线图 (Roadmap)

本文档为 `MoziToolKit` Blender 插件前端的功能演进与版本规划清单。底层核心算法、体素流与几何计算见 [`libmozitoolkit/TODO.md`](../libmozitoolkit/TODO.md)。

---

## 📌 版本演进总览 (Milestones Overview)

| 版本 | 阶段定位 | 核心主题与边界 | 状态 |
| :--- | :--- | :--- | :--- |
| **v2.0 正式版** | **里程碑发版** | **核心世界资产与材质渲染基石 (Production Release)**<br>聚焦世界存档导入、Live Sync 实时同步、小三样网格工具、Biome 3D 染色、CTM 规则与**动画材质端到端闭环**，交付 100% 稳定开箱即用的高保真视觉与极速体验。 | 🚀 **收官冲刺中 (RC)** |
| **v2.1** | **次级大版本** | **动画生态整合与高级实体 (Animation Ecosystem & Advanced Entities)**<br>整合 `mi2bl`（Mine-imator 动画导入）、自包含场景交换包 (`.mtkscene`)、原版悬挂实体（画作/展示框）、地图物品解码、1.21.4+ 铜像特殊模型与可动铰链装配。 | 📋 **规划排期中** |
| **v2.2+** | **万能创作套件** | **创作者全能工具箱 (Creator's Swiss Army Knife)**<br>交互式 2D 俯视微型地图选区器、建筑蓝图 (`.litematic` / `.schematic`) 导入、角色皮肤 3D 挤出与预设 Rig 库、环境日夜天空盒。 | 🔮 **远景规划** |

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

## 🚀 v2.1 版本：动画生态整合与高级实体 (规划排期中 📋)

> **2.1 版本主题**：从“静态世界资产”升级为“Minecraft 角色、动画与跨工具生产力生态”，打造核心工作流闭环。

### 1. 整合 Mine-imator 转 Blender 导入器 (`mi2bl`) (P1 核心特性 🌟)
- [ ] **模块化架构引入**
  - [ ] 将原 [mi2bl](https://github.com/mozi1924/mi2bl) 重构为 `MoziToolKit` 子包（`operators/mi2bl/`）；
  - [ ] 顶部主菜单接入：`File -> Import -> Mine-imator Project (.miproject / .miobject / .miframes)`；
- [ ] **高保真动画与曲线映射 (F-Curves)**
  - [ ] 全量支持 Mine-imator 过渡曲线类型（Linear, Instant, Bézier 等）直接映射为 Blender F-curves；
  - [ ] 时间线对齐与帧率自适应转换；
- [ ] **Pivot 空物体骨架与层级系统**
  - [ ] 自动构建基于 Pivot Empty 的父子层级结构，精准处理 Y/Z 轴翻转；
  - [ ] 确保局部旋转、缩放与原版 Mine-imator 视觉完全一致；
- [ ] **原生参数与自定义属性无缝映射**
  - [ ] 摄像机参数映射：FOV、景深 (DOF) 焦距、光圈大小、散景叶片数 (Blades)、散景比例；
  - [ ] 灯光参数映射：强度换算、裁剪距离 (Cutoff Distance)、颜色、软阴影半径 (Radius)、聚光灯圆锥角度；
  - [ ] 材质自定义属性保留：`mi_alpha`、`mi_emissive`、`mi_roughness`、`mi_metallic` 等挂载至物体属性，供着色器调用。

### 2. 1.21.4+ 客户端特殊模型攻坚 (Special Renderers & Copper Golem Statue) (P1)
- [ ] **解析客户端模型新规范**
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

## 🔮 v2.2+ 远景：万能创作者瑞士军刀 (Future Vision)

- [ ] **交互式 2D 俯视微型地图选区器 (Interactive 2D Minimap Selector)**
  - 彻底告别纯数字 AABB 坐标输入；
  - 提供可视化的世界俯视微缩地图弹窗，支持缩放拖拽、方块生物群系着色预览与矩形框选选区。
- [ ] **建筑投影与蓝图文件直接导入 (`.litematic` / `.schematic` / `.nbt`)**
  - 无需把建筑粘贴进世界存档，直接在 Blender 中单选 `.litematic` 蓝图文件一键生成网格与材质。
- [ ] **玩家角色与原版生物绑定库 (Character Rig & Skin Tools)**
  - 玩家皮肤一键加载器（支持 64×64 双层皮肤，第二层立体挤出）；
  - 内置经典角色与常用原版生物基础 FK/IK 骨骼绑定预设。
- [ ] **环境氛围与渲染辅助工具集 (Atmosphere & Render Presets)**
  - 原版日夜循环天空盒节点树（动态太阳、月相与体积云朵方块层）；
  - Cycles / Eevee Next 一键渲染优化预设（AgX 色彩管理、景深与采样率自动化）。
