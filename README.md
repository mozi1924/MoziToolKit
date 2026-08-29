# MoziToolKit

**MoziToolKit** 是一套专为 Blender 艺术家、动画师与游戏资产开发者打造的高效生产力工具集。针对 **Minecraft 资产转换**、**纹理图集（Texture Atlas）烘焙**、**自适应像素网格切分**、**UV 修正**、**智能挤出建模** 以及 **模块化自动化流水线** 进行了深度优化与自动化集成。

> 📖 **架构设计与防回归规范**：详细设计理念、数学原理、边界约束与防回归规范请参阅 [MoziToolKit 技术文档与设计规范导航](docs/README.md)。

> 由此插件，献给我的朋友 [白巧克力酱OvO](https://space.bilibili.com/475942905)

---

## 🌟 核心功能一览 (Key Features)

### 1. 🎨 Minecraft 材质替换与 Atlas 烘焙管线 (Material & Texture Pipeline)
- **多格式与多来源无缝兼容**：
  - 支持直接读取 Minecraft Java 资源包（`.zip`、`.jar` 或解压目录）。
  - 智能适配多种常见地图导出工具模型：
    - **`jmc2obj`**：原生支持保留连续平铺 UV，通过图集着色器安全映射，解决 UV 越界贴图拉伸问题。
    - **`Mineways`**：深度解析 Mineways 材质映射逻辑与方块纹理。
    - **`Ice-Cube`**：智能匹配其材质别名与专属命名规范。
    - **`Generic` 通用模型**：智能去除材质前缀、版本别名映射与模糊匹配。
- **双材质构建模式 (Dual Material Modes)**：
  - **图集模式 (Atlas Mode)**：自动将所有方块贴图动态打包为一张紧凑高效的 Texture Atlas 图集，配合自定义 Atlas UV 变换节点组，大幅降低 Draw Call 与显存占用，完美支持平铺纹理（Tiling UV Wrapping）防溢色运算。
  - **独立模式 (Standalone Mode)**：为每个方块创建独立的 PBR 材质节点树，针对逐帧动画贴图提供 UV 局部自动对齐重构。
- **🌿 生物群系颜色染色系统 (Biome Color Palettes & Colormap Tinting)**：
  - 内置 **14+ 种官方生物群系配色预设**（平原 Plains、森林 Forest、桦木林 Birch Forest、针叶林 Taiga、丛林 Jungle、热带草原 Savanna、恶地 Badlands、沼泽 Swamp、黑森林 Dark Forest、红树林沼泽 Mangrove Swamp、樱花树林 Cherry Grove、雪原 Snowy Plains、沙漠 Desert、温带海洋 Warm Ocean 等）。
  - 支持对草方块（Grass）、树叶（Foliage/Leaves）、水体（Water）、藤蔓（Vines）、甘蔗（Sugar Cane）、红石线（Redstone）等进行高精度色图（Colormap）双线性插值与颜色染色。
- **🎬 动态动画材质 (Animated Textures)**：
  - 自动解析 Minecraft `.mcmeta` 逐帧动画数据，自动生成由时间轴驱动的逐帧切换着色器节点组。
- **⚡ 高性能缓存与资源打包**：
  - 多级解包缓存（Temp Cache）极大提升二次加载速度。
  - 支持贴图一键内嵌（Pack Textures into `.blend`）或导出到工程目录（`//textures/block/`）。

---

### 2. ✂️ 自适应像素网格细分与建模工具 (Mesh & Modeling Operators)
- **自适应像素网格切分 (Adaptive Pixel Split)**：
  - 根据所贴材质纹理的分辨率与 UV 像素密度，自适应细分网格面（实现 **1 面 = 1 像素** 或指定像素网格比例）。
  - 自动保持顶点组权重（Vertex Groups）与自定义网格属性（Attributes），智能兼容动画单帧与图集瓦片。
- **自动挤出与 UV 修复 (Auto Extrude Repair)**：
  - 彻底解决面挤出后侧面 UV 拉伸、重叠及错位问题。
  - 提供三种 UV 修正模式：
    - **智能模式 (Smart)**：根据挤出方向自动推断内外侧。
    - **向内模式 (Inward)**：侧面自动收缩取样自顶面像素（Minecraft 经典像素挤出）。
    - **向外模式 (Outward)**：侧面映射取样自相邻方块像素。
  - 支持自动为挤出边缘添加折痕权重（**Mean Crease**），防止细分曲面时边缘塌陷变形。
- **🎲 随机高度挤出 (Random Extrude)**：
  - 沿法线以随机高度或 3D 噪声（Perlin Noise / Cell Noise / 伪随机 Seed）批量独立挤出选中面，自带侧面 UV 修复与 Crease 控制，快速为地貌、砖石和建筑表面营造自然的立体浮雕与高低层次。
- **🧹 清除自定义分割法线 (Clear Custom Normals)**：
  - 一键清理从外部导入工具带入的损坏法线与 `custom_normal` 属性，彻底解决模型阴影发黑、面法线撕裂破损问题。
- **📐 锐边与硬边选择 (Select Hard & Sharp Edges)**：
  - 按角度阈值与锐边标记快速选区，便于标记缝合边与倒角控制。

---

### 3. 🧊 UV 编辑与选区工具 (UV & Selection Tools)
- **UV 原地独立缩放 (Scale UV Individual)**：
  - 支持每个面在自身的 UV 局部中心独立进行微距缩放（如 `0.8x` 或 `0.999x`），轻松消除贴图边缘采样渗色与接缝黑边瑕疵。
- **🌊 修复流体 UV (Repair Fluid UV)**：
  - 自动检测并修复倾斜水流、岩浆侧面等流体网格 UV 上下颠倒与拉伸对齐问题。
- **👻 基于纹理透明度选择面 (Select Transparent Faces)**：
  - 采样贴图 Alpha 通道，自动选出或剔除完全透明/半透明的面（如树叶镂空、草丛植物周围的透明多边形），支持中心采样（Center）、四角采样（All Corners）与平均采样（Average）。
- **🔍 一键邻近插值 (Texture Interpolation Closest)**：
  - 批量将选中物体材质中的图像贴图节点插值模式设置为 **Closest（最近邻/邻近）**，呈现清爽锐利的像素画风。

---

### 4. 🔄 模块化流水线系统 (Modular Step Pipeline & Presets)
- 基于解耦设计的 Pipeline 架构（`Step` ↔ `PipelineContext` ↔ `StepResult`）。
- 支持非阻塞模态进度条（Modal Progress Bar）交互反馈与实时状态报告。
- 内置开箱即用的一键预设（Presets），便于快速批量处理资产。

---

### 5. ⚙️ 高度可定制的右键上下文菜单 (Dynamic Context Menus)
- **菜单全自由定制**：在 Blender 偏好设置中自由启用、禁用、拖拽排序、重命名 3D View（**Object Mode**、**Edit Mode**）和 **UV Editor** 的右键上下文菜单项。
- **配置导入与导出**：支持将自定义的菜单配置一键导出为 JSON 文件或从 JSON 导入，便于团队共享与多机同步。
- **🌐 完整双语支持 (i18n)**：深度支持简体中文（`zh_CN` / `zh_HANS`）与英文（`en_US`）。

---

## 📦 依赖管理与 Python Wheels (Python Wheels & Dependencies)

MoziToolKit 基础建模与 UV 工具均为纯 Blender Python 实现，无需额外依赖。  
- **Atlas 材质图集生成与图像像素采样** 依赖轻量图像处理库 `Pillow` (PIL)。
- **Minecraft Live Sync 实时双向同步** 依赖高性能 WebSocket 库 `websockets`。

根据 **Blender 4.2+ / 5.x 扩展平台 (Extensions Platform)** 规范，通过 **Python Wheels (`.whl`)** 打包依赖，实现环境完全隔离与离线即用，避免全局 Python 环境污染或依赖版本冲突。

### 1. 跨平台预置 Wheels 结构

项目在 `wheels/` 目录下准备了对齐全平台的预编译 Wheels 包（兼容 Python 3.13 / Blender 4.2+）：
- **macOS ARM64 (Apple Silicon)**: `pillow-*-macosx_*_arm64.whl`, `websockets-*-macosx_*_arm64.whl`
- **Windows AMD64 (x86_64)**: `pillow-*-win_amd64.whl`, `websockets-*-win_amd64.whl`
- **Windows ARM64**: `pillow-*-win_arm64.whl`, `websockets-*-py3-none-any.whl`
- **Linux AMD64 (x86_64)**: `pillow-*-manylinux_*.whl`, `websockets-*-manylinux_*.whl`

### 2. 在 Manifest 中声明

在 `blender_manifest.toml` 中配置支持平台与 Wheels 列表：

```toml
platforms = ["windows-x64", "windows-arm64", "macos-arm64", "linux-x64"]

wheels = [
  "wheels/pillow-12.3.0-cp313-cp313-macosx_11_0_arm64.whl",
  "wheels/pillow-12.3.0-cp313-cp313-win_arm64.whl",
  "wheels/pillow-12.3.0-cp313-cp313-win_amd64.whl",
  "wheels/pillow-12.3.0-cp313-cp313-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl",
  "wheels/websockets-15.0.1-cp313-cp313-macosx_11_0_arm64.whl",
  "wheels/websockets-15.0.1-cp313-cp313-manylinux_2_5_x86_64.manylinux1_x86_64.manylinux_2_17_x86_64.manylinux2014_x86_64.whl",
  "wheels/websockets-15.0.1-cp313-cp313-win_amd64.whl",
  "wheels/websockets-15.0.1-py3-none-any.whl",
]
```

---

## 🚀 构建与打包 (Build & Package)

### 方式 A：使用内置多平台协调构建脚本（推荐）

`build.py` 会自动定位系统中的 Blender，提取其内置 Python 与 pip，下载补齐依赖，校验扩展元数据并执行全平台独立分包：

```bash
# 默认协调 Blender Python 下载依赖、校验并分平台打包至 dist/
python3 build.py

# 仅验证扩展元数据
python3 build.py --validate-only

# 清理并重新下载全平台最新依赖 wheels
python3 build.py --clean-wheels

# 同时生成全量 Universal 独立安装包
python3 build.py --universal

# 指定特定 Blender 执行程序路径
python3 build.py --blender /Applications/Blender.app/Contents/MacOS/blender
```

### 方式 B：使用 Blender 官方命令行

```bash
# 校验 Manifest 格式
blender --command extension validate

# 单包构建
blender --command extension build --output-dir dist

# 分平台构建（推荐）
blender --command extension build --split-platforms --output-dir dist
```

---

## 🧪 自动化测试 (Testing)

项目配备了基于 Blender Python 环境的自动化测试用例，覆盖网格细分算法、UV 变换、材质解包与生物群系映射逻辑：

```bash
# 在终端中通过 Blender 无头模式执行测试套件
blender -b --python tests/run_tests.py
```

---

## 📄 开源许可 (License)

本项目基于 **GNU General Public License v3.0 or later (SPDX: GPL-3.0-or-later)** 开源。

