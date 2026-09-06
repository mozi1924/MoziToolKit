# MoziToolKit

**MoziToolKit** 是一套专为 Blender 艺术家、动画师与游戏资产开发者打造的高效生产力工具集。针对 **Minecraft 实时双向同步（Live Sync）**、**MC 方块模型烘焙引擎（MC Baker）**、**材质替换与纹理图集（Texture Atlas）烘焙**、**自适应像素网格切分**、**智能挤出与 UV 修复** 以及 **模块化自动化流水线** 进行了深度优化与自动化集成。

> 📖 **架构设计与防回归规范**：详细设计理念、数学原理、边界约束与防回归规范请参阅 [MoziToolKit 技术文档与设计规范导航](docs/README.md)。

> 由此插件，献给我的朋友 [白巧克力酱OvO](https://space.bilibili.com/475942905)

---

## 🌟 核心功能一览 (Key Features)

### 1. ⚡ Minecraft 实时双向同步系统 (Minecraft Live Sync)
- **WebSocket 异步二进制高频流通信**：
  - 基于高性能 WebSocket 二进制流与主线程高频事件泵（Event Pump），实现 Minecraft（Yefira Mod）与 Blender 之间亚毫秒级的方块数据实时双向协同与网格渲染。
- **Direct Mesh 原生 16×16×16 Section 增量构建**：
  - 采用 16×16×16 分块容器与 6 向邻域遮挡剔除算法（Face Culling），仅渲染暴露外表面，极大地降低多边形数量与视口渲染负载。
- **0ms 瞬间握手校验与增量更新 (CRC32 Handshake & Delta Engine)**：
  - 连接时自动比对服务端与本地 Section 的 CRC32 哈希，100% 一致时实现 0 毫秒瞬间连接与零重复流量；方块放置、破坏与红石更新实时增量重构（Delta Update）。
- **动态选区移动与边界接缝自愈 (Seam Healing)**：
  - 支持在游戏或 Blender 中动态缩放/移动同步选区，自动剪枝超出边界的体素，并在选区变动与流式传输结束瞬间自动执行跨 Section 接缝面剔除自愈（Seam Healing）。
- **实时生物群系平滑混合与流体动力学**：
  - 内存体素支持 5×5 邻域加权平滑群系色图（Colormap）采样；流体网格生成器支持水/岩浆表面张力、4 角高度插值与流动方向斜坡 UV 旋转。

---

### 2. 🧊 MC 方块模型烘焙引擎 (MC Baker Engine)
- **JSON 方块模型继承树展开**：
  - 深度解析 Minecraft 原版及 MOD 的方块模型 JSON 文件，支持 `#texture` 变量继承树展开与多重父模型递归解析。
- **Blockstate 变体与 Multipart 复合条件解析**：
  - 完美支持 `blockstates` 中的 `variants` 变体权重与 `multipart` 复合逻辑条件分支评估，准确还原复杂方块形态。
- **原版遮挡算法与 Atlas Bridge 桥接**：
  - 结合 `cullface` 标记与 3D 空间裁剪，自动过滤内部隐藏面；内置 Atlas Bridge 桥接器将 JSON 模型顶点动态映射至 Texture Atlas 图集。

---

### 3. 🎨 材质替换与 Atlas 烘焙管线 (Material & Texture Pipeline)
- **多格式与多来源无缝兼容**：
  - 支持直接读取 Minecraft Java 资源包（`.zip`、`.jar` 或解压目录）。
  - 智能适配多种常见地图导出工具模型：
    - **`jmc2obj`**：原生支持保留连续平铺 UV，通过图集着色器安全映射，解决 UV 越界贴图拉伸问题。
    - **`Mineways`**：深度解析 Mineways 材质映射逻辑与方块纹理。
    - **`Ice-Cube`**：智能匹配其材质别名与专属命名规范。
    - **`Generic` 通用模型**：智能去除材质前缀、版本别名映射与模糊匹配。
- **双材质构建模式 (Dual Material Modes)**：
  - **图集模式 (Atlas Mode)**：自动将所有方块贴图动态打包为一张紧凑高效的 Texture Atlas 图集，配合自定义 Atlas UV 变换节点组，大幅降低 Draw Call 与显存占用，完美支持平铺纹理（Tiling UV Wrapping）防溢色 Clamp 运算。
  - **独立模式 (Standalone Mode)**：为每个方块创建独立的 PBR 材质节点树，针对逐帧动画贴图提供 UV 局部自动对齐重构。
- **材质来源追踪与无损复原 (`mtk_source_texture_key`)**：
  - 生成网格时自动写入面级来源属性 `mtk_source_texture_key`，支持基于面属性的一键材质原地无损复原与槽位自动自愈。
- **🌿 生物群系颜色染色系统 (Biome Color Palettes & Colormap Tinting)**：
  - 内置 **65+ 种原生生物群系配色预设**（平原、森林、苔原、沼泽、樱花树林、黑森林等）。
  - 支持对草方块（Grass）、树叶（Foliage/Leaves）、水体（Water）、藤蔓（Vines）、甘蔗（Sugar Cane）等进行高精度色图（Colormap）双线性插值与颜色染色。
- **🎬 动态动画材质 (Animated Textures)**：
  - 自动解析 Minecraft `.mcmeta` 逐帧动画数据，自动生成由时间轴驱动的逐帧切换着色器节点组。

---

### 4. ✂️ 网格、建模与动画实用工具集 (Mesh, UV & Animation Tools)
- **自适应像素网格切分 (Adaptive Pixel Split)**：
  - 根据所贴材质纹理的分辨率与 UV 像素密度，自适应细分网格面（实现 **1 面 = 1 像素** 或指定像素网格比例），自动保持顶点组权重（Vertex Groups）与网格属性。
- **自动挤出与 UV 修复 (Auto Extrude Repair)**：
  - 彻底解决面挤出后侧面 UV 拉伸与错位问题。提供 **智能模式 (Smart)**、**向内模式 (Inward)** 与 **向外模式 (Outward)**，支持自动为挤出边缘添加折痕权重（**Mean Crease = 1.0**）。
- **🎲 随机高度挤出 (Random Extrude)**：
  - 沿法线以随机高度或 3D 噪声（Perlin Noise / Cell Noise / 伪随机 Seed）批量独立挤出选中面，自带侧面 UV 修复与 Crease 控制，快速营造自然的立体浮雕与高低层次。
- **🍃 植物风吹摇摆程序化动画 (Foliage Waving)**：
  - 一键为树叶、草丛等植物模型构建程序化风吹摇摆着色器节点组，支持顶点组权重控制与风速/风向/摆幅实时调节。
- **🧊 UV 与选区工具**：
  - **UV 原地独立缩放 (Scale UV Individual)**：每个面在自身 UV 局部中心独立微距缩放，轻松消除贴图边缘采样渗色。
  - **修复流体 UV (Repair Fluid UV)**：自动检测并修复倾斜水流、岩浆侧面等流体网格 UV 上下颠倒与拉伸对齐问题。
  - **基于 Alpha 透明度选择面 (Select Transparent Faces)**：采样贴图 Alpha 通道自动选出或剔除透明/半透明面。
  - **一键邻近插值 (Texture Interpolation Closest)**：批量将选中物体材质中的图像贴图节点插值模式设置为 Closest（最近邻/邻近），呈现清爽锐利的像素画风。
  - **清除自定义分割法线与硬边选择**：清理损坏法线与 `custom_normal` 属性，按角度阈值与锐边标记快速选区。

---

### 5. 🔄 模块化流水线与动态 UI (Pipeline & Dynamic Context Menus)
- **模块化流水线系统 (Modular Step Pipeline)**：基于解耦设计的 Step 架构，支持非阻塞模态进度条交互反馈与一键预设（Presets）批处理。
- **菜单全自由定制**：在偏好设置中自由启用、禁用、拖拽排序、重命名 3D View（Object Mode, Edit Mode）和 UV Editor 的右键上下文菜单项，支持配置 JSON 导出与导入。
- **🌐 完整双语支持 (i18n)**：深度支持简体中文（`zh_CN` / `zh_HANS`）与英文（`en_US`）。

---

## 📦 依赖管理与 Python Wheels (Python Wheels & Dependencies)

MoziToolKit 基础建模与 UV 工具均为纯 Blender Python 实现，无需额外依赖。  
- **Atlas 材质图集生成与图像像素采样** 依赖轻量图像处理库 `Pillow` (PIL)。
- **Minecraft Live Sync 实时双向同步** 依赖高性能 WebSocket 库 `websockets`。

根据 **Blender 4.2+ / 5.2+ 扩展平台 (Extensions Platform)** 规范，通过 **Python Wheels (`.whl`)** 打包依赖，实现环境完全隔离与离线即用，避免全局 Python 环境污染或依赖版本冲突。

### 跨平台预置 Wheels 结构

项目在 `wheels/` 目录下准备了对齐全平台的预编译 Wheels 包（兼容 Python 3.13 / Blender 4.2+ / 5.2+）：
- **macOS ARM64 (Apple Silicon)**: `pillow-*-macosx_*_arm64.whl`, `websockets-*-py3-none-any.whl`
- **Windows AMD64 (x86_64)**: `pillow-*-win_amd64.whl`, `websockets-*-py3-none-any.whl`
- **Windows ARM64**: `pillow-*-win_arm64.whl`, `websockets-*-py3-none-any.whl`
- **Linux AMD64 (x86_64)**: `pillow-*-manylinux_*.whl`, `websockets-*-py3-none-any.whl`

在 `blender_manifest.toml` 中已完整配置：

```toml
platforms = ["windows-x64", "windows-arm64", "macos-arm64", "linux-x64"]

wheels = [
  "./wheels/pillow-12.3.0-cp313-cp313-macosx_11_0_arm64.whl",
  "./wheels/pillow-12.3.0-cp313-cp313-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl",
  "./wheels/pillow-12.3.0-cp313-cp313-win_amd64.whl",
  "./wheels/pillow-12.3.0-cp313-cp313-win_arm64.whl",
  "./wheels/websockets-15.0.1-py3-none-any.whl",
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

项目配备了基于 Blender Python 环境的自动化测试用例，覆盖 Live Sync 握手与网格生成、MC Baker 解析、网格细分算法、UV 变换、材质解包与生物群系映射逻辑：

```bash
# 在终端中通过 Blender 无头模式执行测试套件
blender -b --python tests/run_tests.py
```

---

## 📄 开源许可 (License)

本项目基于 **GNU General Public License v3.0 or later (SPDX: GPL-3.0-or-later)** 开源。
