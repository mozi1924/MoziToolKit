# MoziToolKit

**MoziToolKit** 是一套专为 Blender 艺术家与游戏资产开发者打造的高效生产力工具集。针对 Minecraft 材质包转换、纹理图集（Texture Atlas）生成、自适应像素网格切分、UV 原地缩放、自动挤出修复等工作流进行了深度优化与自动化集成。

---

## 🌟 核心特性 (Features)

- 🎨 **Minecraft 材质批量替换 & Atlas 渲染管线**：
  - 支持直接读取 Minecraft Java 资源包（`.zip` 或解压目录），自动匹配并构建 PBR 材质节点。
  - 支持 **Atlas 材质图集模式** 与 **Standalone 独立材质模式**。
  - 自动解包、图集烘焙、多级缓存加速与动画材质节点生成。
  - 针对 `jmc2obj` 优化网格保留原始 UV 平铺，并通过 Atlas 着色器安全渲染。
- ✂️ **自适应像素网格切分 (Adaptive Pixel Split)**：
  - 根据 UV 纹理像素密度自适应细分面，无缝适配像素画风与方块建模。
- 🧊 **UV 原地独立缩放 (Scale UV Individual)**：
  - 支持每个面在自身 UV 局部中心独立缩放，消除边缘溢色与接缝瑕疵。
- 🛠️ **自动挤出与 UV 修复 (Auto Extrude & Repair)**：
  - 批量或随机高度挤出并自动修复侧面 UV 拉伸及折痕（Mean Crease）。
- ⚙️ **高度可定制的右键上下文菜单 (Context Menu Presets)**：
  - 在偏好设置中自由启用、排序、重命名 Edit Mode / Object Mode / UV Editor 右键菜单项，支持 JSON 配置导入导出。

---

## 📦 依赖管理与 Python Wheels (Python Wheels & Dependencies)

MoziToolKit 的基础建模与 UV 工具均为纯 Blender Python 实现，无需任何外部依赖。  
**Atlas 材质图集生成功能** 依赖轻量图像处理库 `Pillow` (PIL)。

根据 **Blender 4.2+ 扩展平台 (Extensions Platform)** 规范，推荐通过 **Python Wheels (`.whl`)** 打包依赖，实现环境完全隔离与离线即用，避免与系统或其他插件环境产生版本冲突。

### 1. 预先下载 Wheels 脚本 (Download Wheels)

如果需要构建包含 Pillow 的全功能自包含扩展包，可以在扩展根目录下创建 `wheels/` 目录并下载对应平台的 Wheels。

以 Blender 4.2+ / 5.x 内置 Python 3.13 为例：

```bash
# 创建 wheels 目录
mkdir -p wheels

# 1. macOS Apple Silicon (M1/M2/M3/M4)
pip download pillow --dest ./wheels --only-binary=:all: --python-version=3.13 --platform=macosx_11_0_arm64

# 2. Windows (Arm64)
pip download pillow --dest ./wheels --only-binary=:all: --python-version=3.13 --platform=win_arm64

# 3. Windows (x86_64)
pip download pillow --dest ./wheels --only-binary=:all: --python-version=3.13 --platform=win_amd64

# 4. Linux (x86_64)
pip download pillow --dest ./wheels --only-binary=:all: --python-version=3.13 --platform=manylinux_2_28_x86_64
```

> **提示**：如果目标是较早的 Blender 4.2（内置 Python 3.11），请将 `--python-version=3.13` 调整为 `--python-version=3.11`。

### 2. 在 Manifest 中启用 Wheels

在 `blender_manifest.toml` 中取消注释并声明下载的 wheels：

```toml
# 支持的操作系统平台
platforms = ["windows-x64", "macos-arm64", "macos-x64", "linux-x64"]

# 打包进扩展的 wheel 文件列表
wheels = [
  "./wheels/pillow-12.1.0-cp313-cp313-macosx_11_0_arm64.whl",
  "./wheels/pillow-12.1.0-cp313-cp313-macosx_10_10_x86_64.whl",
  "./wheels/pillow-12.1.0-cp313-cp313-win_amd64.whl",
  "./wheels/pillow-12.1.0-cp313-cp313-manylinux_2_28_x86_64.whl",
]
```

---

## 🚀 构建与打包 (Build & Package)

### 方式 A：使用内置构建脚本（推荐）

项目自带跨平台构建脚本 `build.py`，优先调用 Blender 官方构建引擎：

```bash
# 默认构建（生成至 dist/ 目录）
python3 build.py -o dist

# 分平台独立构建（为不同操作系统生成对应轻量 zip）
python3 build.py -o dist --split-platforms

# 指定特定 Blender 执行程序路径
python3 build.py --blender /Applications/Blender.app/Contents/MacOS/blender
```

### 方式 B：使用 Blender 官方命令行工具

```bash
# 校验 Manifest 格式
blender --command extension validate

# 单包构建
blender --command extension build --output-dir dist

# 分平台构建（推荐用于带二进制 wheel 的扩展）
blender --command extension build --split-platforms --output-dir dist
```

---

## 🧪 自动化测试 (Testing)

项目配备了基于 Blender Python 环境的自动化测试用例，覆盖管线核心、网格细分算法、UV 变换与材质解包逻辑。

```bash
# 在终端中通过 Blender 无头模式执行测试
blender -b --python tests/run_tests.py
```

---

## 📋 上架 Blender 扩展平台常见问答 (FAQ)

### Q1: 带有 Wheel 的扩展能否上传到 `extensions.blender.org`？
**答：完全可以，且官方强烈推荐。**  
Blender 官方扩展平台设计了专用的 Wheels 机制。扩展在安装时由 Blender 自动解压到该扩展私有的 `site-packages` 目录，彻底解决了以往插件运行 `pip install` 污染全局 Python 环境和版本冲突的问题。平台审核要求 wheel 文件直接从 PyPI 下载且未经篡改。

### Q2: 是否必须打包全部平台的 Wheel？
**答：取决于你打算支持的操作系统范围。**
1. **全平台分发（推荐）**：
   - 准备 `windows-x64`、`macos-arm64`、`macos-x64`、`linux-x64` 的 wheels。
   - 使用 `blender --command extension build --split-platforms` 打包，会针对每个平台生成专属的小体积 zip（如 `mozitoolkit-1.0.0-windows-x64.zip`）。
   - 上传到扩展平台时，平台会自动根据用户的操作系统分发对应平台的安装包。
2. **指定部分平台**：
   - 如果只打包了部分平台的 wheel（例如只提供了 Windows 和 macOS），只需在 `blender_manifest.toml` 的 `platforms` 列表中保留对应平台即可，未列出的平台将不会接收到不兼容的安装包。

---

## 📄 开源许可 (License)

本项目基于 **GNU General Public License v3.0 or later (SPDX: GPL-3.0-or-later)** 开源。
