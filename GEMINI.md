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

### 规则 4：双态架构与严禁全局 bpy 污染 (Dual-Mode Dev/Release Architecture & No Global bpy Pollution)
- **开发态（Development Mode）极速迭代规约**：
  - 日常开发阶段**彻底移除根目录下的一切 wheel 轮子**，`blender_manifest.toml` 中不声明任何固定本地 wheel（避免 VSCode Link 时触发 Blender 轮子缓存锁定与卸载重装地狱）。
  - 底层二进制扩展统一由 `dev/loader.py` 动态加载，通过软链接（`MoziToolKit/dev/lib/libmtk_py.so` -> `libmozitoolkit/target/release/liblibmtk_py.so`）直通 Rust 编译产物。Rust 核心修改编译后，Blender 重载即可即时生效。
  - 所有开发专用面板、基准压测与调试算子统一收敛在 `dev/` 模块中，提供 N 侧边栏可视化 UI，并通过 `dev/api.py` 为 MCP Agent（`execute_blender_code`）提供便捷的无头自动化测试能力。
- **发布态（Release Packaging）纯净隔离规约**：
  - 最终打包统一由 `python3 build.py` 处理；打包脚本自动拉取/编译 release wheels 注入临时打包目录与 `blender_manifest.toml` 的 `wheels = [...]` 字段。
  - 打包过程中**自动物理剔除 `dev/` 文件夹**，交回 Blender 4.2+ 原生扩展平台隔离机制，确保面向最终用户的发行包自包含且绝对纯净。
- **严禁安装在宿主全局 bpy / Python 环境中**：
  - 严禁通过 `pip install`、脚本或任何外部手段将编译出的轮子直接安装到宿主 Blender 的全局 `bpy` 或系统全局 Python 环境中，彻底杜绝全局环境污染。

### 规则 5：Blender 4.2+ 扩展清单规范 (Manifest Integrity)
- 本插件遵循 Blender 4.2+ Extension 标准。版本号、权限、依赖项与元数据必须同步维护在 `blender_manifest.toml` 中。
- 每次新增、更新或调整 `wheels/` 目录下的轮子文件名/版本时，必须同步更新 `blender_manifest.toml` 中的 `wheels` 列表，确保平台打包与发布的一致性。

### 规则 6：操作符与业务逻辑模块化规范 (Operator Modularity)
- **严禁创建单文件巨石操作符**：当操作符逻辑涉及“属性定义 (Properties)”、“后台定时器/Depsgraph 监听 (Watcher/Handler)”与“多个用户算子 (Operators)”时，**严禁堆叠在同一个大文件中**。
- **强制采用子包架构**：必须参照 `operators/extrude/` 与 `operators/sync/` 架构建立专属子目录包（包含 `__init__.py`, `properties.py`, `watcher.py`, `op_xxx.py`）。
- **文件行数软约束**：除纯静态查找表（如预设表 `mineways_table.py`）外，业务逻辑代码单文件原则上控制在 500 行以内。

### 规则 7：Blender 5.x / 6.0 API 前瞻兼容规范 (Forward Compatibility)
- **严禁使用即将废弃的属性**：严禁直接在代码中编写 `mat.use_nodes = True`（在 Blender 5.2 中已标记废弃，Blender 6.0 彻底移除）。
- **统一使用兼容封装**：必须统一使用 `utils/materials/builder/` 中封装的安全兼容方法，或在材质创建后直接操作/判断 `mat.node_tree`，彻底杜绝 DeprecationWarning。

### 规则 8：代码检索与构建目录过滤规范 (Code Search & Target Exclusion)
- **优先使用 ripgrep (`rg`)**：在工作区检索代码、资产引用或符号时，**首选且尽量使用 `rg` (ripgrep)** 命令。`rg` 具备极致的检索性能且原生遵循 `.gitignore` 规则。
- **使用 `grep` 时必须忽略 `target` 目录**：若在特定场景下使用 `grep`，**必须显式添加 `--exclude-dir=target`**（以及 `--exclude-dir=.git`、`--exclude-dir=__pycache__`、`--exclude-dir=.venv` 等冗余目录），严禁递归扫描底层 Rust 构建产物 `target/` 目录与 Python 缓存，杜绝海量输出干扰与性能损耗。

### 规则 9：测试门禁与测试资产规范 (Test Gate & Asset Policy)
- **两个测试模式缺一不可**：
  - **Mock 快速模式（无 Blender，CI 首选）**：`python -m pytest tests/ -q`（`conftest.py` 自动 mock `bpy`，仅验证 Bridge 与纯数据逻辑）；
  - **Blender 宿主模式（真实 bpy / 节点树 / 算子）**：`blender --background --python tests/run_tests.py -- -q`。`tests/run_tests.py` 是唯一测试入口，禁止再另起 `pytest.main` 脚本。
- **测试资产统一走 `tests/_assets.py`**：所有需要真实 Minecraft 资产的测试必须通过 `assets_root()` / `fabric_jar()` / `resource_pack_zip()` / `save_world()` / `blender_datafiles_cache()` 定位；严禁硬编码 `/home/<user>`、`/Users/<user>` 等个人绝对路径。
  - 环境变量：`MTK_TEST_ASSETS` / `MC_DIR` / `MC_ASSETS_DIR` / `MTK_TEST_JAR` / `MTK_TEST_RESOURCE_PACK` / `MTK_TEST_SAVE` / `MTK_TEST_CACHE`。
  - 大型真包（客户端 JAR、资源包、Blender 本体）**绝不入库**，由 `.github/workflows/ci.yml` 从临时镜像 `mozi1924/mtk-ci-assets` 下载（过渡方案，迁移后删除）。
- **缺失即优雅跳过**：资产或 Blender 不可用时，相关测试必须 `skip`（`pytest.skip` / `unittest.SkipTest`），严禁在 `setUpClass` 中直接 `FileNotFoundError` 崩溃。
- **严禁在 `.venv` 中保留陈旧 `libmtk_py`**：开发态必须依赖 `dev/lib/libmtk_py.so` 直连编译产物；若确需安装 wheel 调试，必须先卸载旧版本，否则陈旧 API 会掩盖真实集成问题（曾导致大量假 `AttributeError`）。
- **提交前必须通过**：Mock 模式全绿；涉及 bpy 的变更还需 `blender --background --python tests/run_tests.py` 全绿。

---

## 3. 插件目录架构

```
MoziToolKit/
├── blender_manifest.toml -> Blender 4.2+ 扩展清单元数据
├── __init__.py           -> 插件入口，注册/注销生命周期
├── bridge/               -> 核心胶水桥梁，封装 libmtk_py 调用
│   ├── mesh.py           -> 几何网格拓扑转换、NumPy 批量提取与 Quad 保留
│   ├── extrude.py        -> 批量 Data In Data Out 挤出修复桥接
│   ├── subdivide.py      -> 自适应像素切分桥接
│   ├── cull.py           -> 遮挡剔除桥接
│   ├── texture.py        -> 贴图与图集桥接
│   ├── material.py       -> 材质与 BiomeResolver 桥接
│   ├── assets.py         -> 预编译资产与缓存加载
│   ├── sync.py           -> 原生 Live Sync 会话生命周期桥接
│   └── uv.py             -> UV 重映射与清洗
├── operators/            -> Blender 操作符 (UI 事件响应)
│   ├── extrude/          -> 智能挤出与实时修复模块包 (Watcher, Properties, Ops)
│   ├── sync/             -> 原生 Live Sync 实时协同模块包
│   └── ...               -> 独立单算子文件 (op_cull, op_mesh, op_uv 等)
├── ui/                   -> 3D 视图侧边栏面板与菜单
├── utils/                -> 节点树生成、BMesh 辅助、材质管线、日志工具
├── wheels/               -> libmtk_py 动态轮子二进制
├── docs/                 -> 详细的架构与功能设计手册
└── tests/                -> 自动化测试用例
```

---

## 4. 开发与测试流程

### 1. 运行测试
- **纯 Python / Mock 快速测试（无 Blender，CI 首选）**：
  ```bash
  python -m pytest tests/ -q
  ```
- **完整 Blender 宿主环境测试（真实 bpy / 节点树 / 算子）**：
  ```bash
  # 将当前虚拟环境的 site-packages 注入 Blender 内置 Python（pytest + libmtk_py abi3 轮子）
  MTK_TEST_SITE_PACKAGES="$(python -c 'import site; print(site.getsitepackages()[0])')" \
    blender --background --python tests/run_tests.py -- -q
  ```
- **真实资产注入（可选）**：设置 `MTK_TEST_ASSETS=/path/to/unpacked/mc`、`MTK_TEST_JAR=/path/to/26.2-Fabric.jar` 可启用真包验证；缺失时相关测试自动跳过。

### 2. 多工作区联动验证
- 涉及 Rust 核心调整时，首先在 `../libmozitoolkit` 完成 `cargo test` 与 `maturin build`；
- **严禁在 `.venv` 中保留陈旧 `libmtk_py`**：开发态优先通过 `dev/lib/libmtk_py.so` 直连 `target/release` 产物；若需安装 wheel，先 `pip uninstall libmtk_py` 再装新版本；
- 然后在 `MoziToolKit` 运行上述 Mock 与 Blender 双端测试验证。CI 默认从 `libmozitoolkit` 的滚动 `ci-latest` Release 下载 abi3 轮子，并可从临时镜像获取 Blender 与真包加速。


## 5.TODO

- [TODO.md](./TODO.md)