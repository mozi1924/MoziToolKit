# GEMINI.md - MoziToolKit (Blender Addon) 协作与开发规范

本文档是供所有 AI Coding Agent 以及核心开发者在 `MoziToolKit` 工作区阅读的开发规范与架构准则。

---

## 1. 项目定位与工作区边界

`MoziToolKit` 是基于 Blender 4.2+ 的高性能 Minecraft 资产处理、着色器构建与实时世界协同扩展插件前端。

### 多工作区协同拓扑
| 工作区路径 | 角色 | 职责边界 |
| :--- | :--- | :--- |
| **`../MoziToolKit`** | **DCC 插件前端 (当前工作区)** | 负责 Blender UI 面板、操作符 (Operators)、属性注册 (Properties)、着色器材质节点树生成，以及通过 `bridge/` 层消费底层 Rust 核心的能力。 |
| **`../libmozitoolkit`** | **Rust 核心引擎 (`libmtk`)** | 纯数据、无宿主依赖的通用 3D/体素计算内核。所有复杂的几何网格重构、图集装箱、遮挡剔除与生物群系计算均在此实现。 |
| **`../MiEx`** | **世界导出参考生态** | 参考 USD 世界导出结构与测试资产源。 |

---

## 2. 核心规约与必须遵守的铁律 (Golden Rules)

### 规则 1：严禁在前端重写核心算法 (No Re-inventing the Wheel)
- 所有计算密集型操作（如像素网格切分、智能挤出侧面 UV 修复、随机噪声挤出、面遮挡剔除、图集装箱、Biome 调色板映射）**必须且只能由 `libmtk_py` 后端处理**。
- 严禁在 Python 端自行实现复杂的 3D 几何、多边形裁剪或图像像素混合算法。

### 规则 2：Bridge 胶水层单一调用原则 (Bridge Encapsulation)
- UI 面板（`ui/`）和操作符（`operators/`）**绝不允许直接 `import libmtk_py`**。
- 所有对 Rust 后端的调用必须通过 `bridge/` 模块（如 `bridge/mesh.py`, `bridge/extrude.py`, `bridge/subdivide.py`, `bridge/cull.py`, `bridge/assets.py`）进行统一封装。
- `bridge/` 层负责：
  - 数据类型安全校验与容错；
  - 动态检查 `libmtk_py` 是否正确加载并提供优雅降级或安装引导；
  - 为自动化单元测试提供可 Mock 的抽象接口。

### 规则 3：批量灌入与零拷贝优先原则 (Batch & Zero-Copy)
- 在 Blender 中读写网格几何时，优先使用 `b_mesh.vertices.foreach_set`、`b_mesh.loops.foreach_set`、NumPy 数组或 BMesh 批量操作。
- 严禁在 Python 中对成千上万个顶点或面进行逐元素循环（如 `for v in mesh.vertices:` 修改坐标），避免造成 Blender 界面卡顿。

### 规则 4：Blender 4.2+ 扩展轮子规范与严禁全局 bpy 污染 (Extension Wheels & No Global bpy Pollution)
- **严格遵循 Blender 4.2+ 扩展轮子规范**：插件依赖的底层二进制扩展（如 `libmtk_py`）必须打包存放在插件根目录下的 `wheels/` 目录中（如 `wheels/libmtk_py-0.1.0-cp311-...whl`），并通过 `blender_manifest.toml` 的 `wheels = [...]` 字段进行显式声明。
- **严禁安装在全局 bpy / Python 环境中**：
  - 严禁通过 `pip install`、脚本或任何外部手段将编译出的轮子直接安装到宿主 Blender 的全局 `bpy` 或系统全局 Python 环境中。
  - 依赖的装配与解压必须完全交由 Blender 4.2+ Extensions 平台的本地隔离机制（Local Environment Isolation）管理，确保插件是纯净自包含（Self-Contained）的。
  - 严禁在代码、操作符或测试脚本中假设存在全局安装的 `libmtk_py`。
- **轮子同步与验证**：当 `../libmozitoolkit` 的核心 API 或实现发生变更时，必须在 Rust 工作区虚拟环境中编译出新 Release 轮子，同步拷贝覆盖至 `wheels/`，并在当前工作区运行测试验证。

### 规则 5：Blender 4.2+ 扩展清单规范 (Manifest Integrity)
- 本插件遵循 Blender 4.2+ Extension 标准。版本号、权限、依赖项与元数据必须同步维护在 `blender_manifest.toml` 中。
- 每次新增、更新或调整 `wheels/` 目录下的轮子文件名/版本时，必须同步更新 `blender_manifest.toml` 中的 `wheels` 列表，确保平台打包与发布的一致性。

---

## 3. 插件目录架构

```
MoziToolKit/
├── blender_manifest.toml -> Blender 4.2+ 扩展清单元数据
├── __init__.py           -> 插件入口，注册/注销生命周期
├── bridge/               -> 核心胶水桥梁，封装 libmtk_py 调用
│   ├── mesh.py           -> 基础网格拓扑转换与 Quad 保留
│   ├── extrude.py        -> 批量 Data In Data Out 挤出修复桥接
│   ├── subdivide.py      -> 自适应像素切分桥接
│   ├── cull.py           -> 遮挡剔除桥接
│   ├── texture.py        -> 贴图与图集桥接
│   ├── assets.py         -> 预编译资产与缓存加载
│   └── uv.py             -> UV 重映射与清洗
├── operators/            -> Blender 操作符 (UI 事件响应)
├── ui/                   -> 3D 视图侧边栏面板与菜单
├── utils/                -> 节点树生成、BMesh 辅助、日志工具
├── wheels/               -> libmtk_py 动态轮子二进制
├── docs/                 -> 详细的架构与功能设计手册
└── tests/                -> 自动化测试用例
```

---

## 4. 开发与测试流程

1. **运行测试**：
   ```bash
   pytest tests/
   ```
2. **多工作区联动验证**：
   涉及 Rust 核心调整时，首先在 `../libmozitoolkit` 完成 `cargo test` 与 `maturin build`，更新 `wheels/` 后再在 `MoziToolKit` 运行集成测试。
