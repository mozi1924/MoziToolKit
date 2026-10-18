# MoziToolKit

[![Blender](https://img.shields.io/badge/Blender-5.0%2B%20LTS-orange.svg)](https://www.blender.org/)
[![Platform](https://img.shields.io/badge/Platforms-macOS%20%7C%20Windows%20%7C%20Linux-lightgrey.svg)](blender_manifest.toml)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Core: libmtk](https://img.shields.io/badge/Core-libmozitoolkit%20(Rust)-red.svg)](../libmozitoolkit)

**MoziToolKit** 是面向 Blender 5.0+ (LTS) 扩展平台的高性能 Minecraft 资产处理、世界协同与着色器管线系统。

系统采用 **计算下沉与宿主解耦** 架构：几何重构、微观遮挡剔除、体素流解析、图集装箱与生物群系色彩数学均由底层通用 Rust 引擎（`libmtk`）无头处理；Blender 前端负责 UI 交互、视口渲染调度与材质节点树装配，并通过 Buffer Protocol 及 Blender DNA 裸指针实现硬件级零拷贝几何直写。

---

## 核心系统与功能规范 (Architecture & Features)

### 1. 实时双向网络协同 (Minecraft Live Sync)
- **传输协议**：基于全双工 WebSocket 二进制异步流，直连 Minecraft 客户端（Fabric `Yefira`）或服务端。
- **增量网格重构 (Delta Meshing)**：以 16×16×16 Section 为空间单元，仅计算 6 向暴露外表面，提供平滑 4 角环境光遮蔽 (Smooth AO) 与拓扑微距焊接。
- **状态校验与接缝自愈**：基于 CRC32 校验码实现零重复流量瞬时重连；选区变动或流传输完成时自动触发跨 Section 边界接缝面剔除自愈（Seam Healing）。
- **复合方块解析**：支持定向方块、红石线动力学、流体表面张力四角高度插值及 CTM (Connected Textures Mod) 47-tile 状态解算。

### 2. 存档直读与体素存储 (Anvil Save Pipeline & Voxel Storage)
- **Anvil 区域文件直读**：支持直接解析 Minecraft 原版 `.mca` 区域文件，解包 384 高度世界方块状态与 3D 生物群系分布。
- **空间切片与流式提取**：按需提取指定空间坐标范围的体素切片，无需运行游戏环境即可批量重构场景网格。
- **体素容器与伴生点云 (Voxel Storage & Point Cloud)**：
  - 网格生成时在子级自动挂载全量体素点云（`Voxel Point Cloud`），提供 Geometry Nodes 轻量化视口预览。
  - 支持非破坏性体素编辑与双向无损重新网格化（Rebuild Mesh）。

### 3. 方块模型烘焙与遮挡剔除 (MC Baker & Face Culling)
- **JSON 模型继承展开**：递归解析 Minecraft 原版及模组方块模型 JSON 继承链，支持 `#texture` 变量解析与 `multipart` 复合条件评估。
- **规范面剔除 (Face Culling)**：严格对齐 Minecraft 1.21+ `Block.shouldRenderFace` 与 `BlockBehaviour.skipRendering` 规范（实心不透明、半透玻璃、透空树叶组及台阶/楼梯 2D 矩形差集切分）。
- **外部网格消重清洗 (`MeshSanitizer`)**：消除外部导入几何中的重叠面、共面自交与微观冗余几何。

### 4. 材质、图集与着色器管线 (Material & Shader Pipeline)
- **双材质构建体系**：
  - **图集分块模式 (Atlas Chunk)**：采用二维装箱算法动态拼合，应用安全 Padding 与 UV Clamp 防溢色算法，通过面级属性（`mtk_atlas_chunk_id` / `mtk_source_texture_key`）驱动共享材质槽位。
  - **独立材质模式 (Standalone PBR)**：预编译通道全栈融合，支持独立纹理展开。
- **PBR 与实时渲染引擎适配**：
  - 完整实现 LabPBR（法线、粗糙度、金属度、发光、次表面散射 Thin-Wall）与 OldPBR 规范。
  - 自动适配 Eevee Next 与 Cycles 渲染器着色节点特性。
- **权威生物群系调色板 (Biome Palette SSOT)**：
  - 内置 66 种原版规范生物群系，提供温度/湿度双线性三角坐标采样与 Linear RGBA 色彩转换。
  - 面级群系属性注入，实现视口亚毫秒级无缝群系切换。
- **逐帧动态材质 (Animated Textures)**：解析 `.mcmeta` 动画元数据，生成由时间轴直接驱动的逐帧切换着色器节点组。
- **导入生态兼容与材质自愈**：自适应兼容 `jmc2obj`、`Mineways`、`Ice-Cube` 与通用导出模型；支持基于面级来源属性的一键原地无损材质自愈。
- **外部网格多 UV 与无损重贴**：原始 local UV 保留在独立 UV Map 中，图集 UV 写入 `MTK_Atlas`；图集布局不变时复用现有 Atlas UV 仅替换贴图，布局变化时从 local UV 重新映射，换包不再破坏原始 UV。

### 5. 几何、UV 与拓扑算子 (Mesh & UV Operators)
- **自适应像素切分 (Adaptive Pixel Split)**：依据贴图像素密度自适应细分平面，实现 1 面 = 1 像素高精度网格，保持顶点组权重与多属性双线性插值。
- **智能挤出与侧面 UV 修复 (Auto Extrude Repair)**：连续像素边界挤出，提供 `SMART`、`INWARD`、`OUTWARD` 修复模式与边缘折痕权重控制（Mean Crease = 1.0）；支持基于 3D 噪声的随机高度挤出 (Random Extrude)。
- **UV 与法线工具**：局部中心独立缩放 (Scale UV Individual)、倾斜流体 UV 修复、贴图 Alpha 通道智能选面、Closest 最近邻插值批量切换、硬边与锐边选择、清除无效 `custom_normal` 属性。
- **程序化植物摇摆 (Foliage Waving)**：一键构建风吹摇摆着色器节点组，支持顶点组权重掩码与风场参数调节。

### 6. 流水线调度与界面架构 (Pipeline & Modular UI)
- **非阻塞模态流水线 (Step Pipeline)**：解耦的 Step 调度机制，配备 3D 视口 Header 进度条与异步状态流反馈。
- **动态上下文菜单**：偏好设置内完全可配置的 3D 视图与 UV 编辑器右键上下文菜单（支持添加/移除/移动/导入/导出/重置）。
- **双语国际化 (i18n)**：全量界面支持简体中文 (`zh_CN`) 与英文 (`en_US`)。

---

## 运行架构与依赖规范 (Architecture & Runtime)

### 纯净运行时与零外部 Python 依赖
- 计算密集型算法与网络 IO 全部下沉至 Rust 内核。
- 图像编解码、图集打包、NBT/Anvil 解析、WebSocket 传输均由原生二进制接管，无第三方 Python 运行时依赖（无需安装 Pillow 或 websockets）。
- 内存直写：支持 Buffer Protocol、`foreach_set` 批量注入及 Blender DNA 裸指针直写。

### 双态架构 (Dual-Mode Architecture)
- **开发态 (Development Mode)**：
  - 源码工作区内不预存静态 wheel 文件。
  - 通过 `dev/loader.py` 动态加载 `dev/lib/libmtk_py.so`（直接软链至 Rust 编译产物），实现免重复打包的快速重载。
- **发布态 (Release Packaging)**：
  - 严格遵循 Blender 5.0+ Extensions Platform 隔离规范。
  - 由 `python3 build.py` 统一拉取/构建符合 ABI3 规范的 wheel 包并封装至分发包内，禁止向 Blender 全局 Python 环境安装任何扩展。

---

## 支持平台 (Supported Platforms)

遵循 Blender 5.0+ 扩展规范，支持以下 64 位平台架构：
- **macOS ARM64** (Apple Silicon)
- **Windows AMD64** (x86_64)
- **Windows ARM64**
- **Linux AMD64** (manylinux x86_64)

---

## 构建与分发 (Build & Packaging)

### 工程构建脚本 (推荐)
```bash
# 全平台依赖补齐、元数据校验并打包至 dist/
python3 build.py

# 仅执行清单元数据校验（不校验 wheel 完整性）
python3 build.py --validate-only

# 清理并重新拉取全平台依赖 wheel
python3 build.py --clean-wheels

# 生成全量 Universal 安装包
python3 build.py --universal

# 指定外部 Blender 可执行文件路径
python3 build.py --blender /path/to/blender
```

> **发布硬性要求**：`build.py` 会为每个声明平台校验 `wheels/` 中是否存在匹配的 `libmtk_py` abi3 wheel，
> 并在打包后检查每个 zip 是否真的带上了该 wheel；缺失时构建直接失败。发布 CI 会先通过
> `.github/workflows/build-release.yml` 的矩阵构建四个平台 wheel，再执行打包。

### 扩展命令行构建 (Blender CLI)
```bash
# 校验扩展清单
blender --command extension validate

# 分平台独立构建
blender --command extension build --split-platforms --output-dir dist
```

---

## 测试与质量门禁 (Testing & Quality Gate)

工程采用分层测试体系，包含纯 Python Mock 快速模式与真实 Blender 宿主环境验证：

```bash
# 1. 快速单元测试（无需 Blender 环境，CI 首选）
python -m pytest tests/ -q

# 2. Blender 宿主环境集成测试（全量真实 bpy、节点树与算子）
blender --background --python tests/run_tests.py -- -q
```

> 测试资产统一由 `tests/_assets.py` 定位（环境变量：`MTK_TEST_ASSETS` / `MTK_TEST_JAR` / `MTK_TEST_SAVE`）。资产缺失时相关测试自动跳过，保证测试密闭性。

---

## 技术文档与规范索引 (Documentation)

- [MoziToolKit 技术文档与设计规范导航](docs/README.md)
  - [分层架构设计与核心原则](docs/architecture/overview.md)
  - [核心设计决策与防回归对照表](docs/architecture/faq_anti_regression.md)
  - [材质解析与模型烘焙管线规范](docs/materials/material_pipeline.md)
  - [RFC v3.1 实时同步协议与架构规范](docs/live_sync/live_sync_protocol.md)
  - [面剔除与微观遮挡算法](docs/mesh/face_culling.md)
  - [自适应像素切分与智能挤出规范](docs/mesh/pixel_split.md)
  - [体素点云持久化与存储契约](docs/mesh/voxel_point_cloud.md)
- [Rust 底层核心库 (`libmozitoolkit`)](../libmozitoolkit/README.md)
- [版本变更日志 (CHANGELOG.md)](CHANGELOG.md)

---

## 开源许可 (License)

本项目遵循 **GNU General Public License v3.0 or later (SPDX: GPL-3.0-or-later)** 开源协议。
