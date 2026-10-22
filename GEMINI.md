# GEMINI.md - MoziToolKit (Blender Addon) 协作与开发规范

本文档是供所有 AI Coding Agent 以及核心开发者在 `MoziToolKit` 工作区阅读的开发规范与架构准则。

---

## 1. 项目定位与工作区边界

`MoziToolKit` 是基于 Blender 4.2+ 的高性能 Minecraft 资产处理、着色器构建与实时世界协同扩展插件前端。

### 多工作区协同拓扑 (Three-Pillar Architecture)
| 工作区路径 | 角色 | 职责边界 |
| :--- | :--- | :--- |
| **`../MoziToolKit`** | **DCC 插件前端 (当前工作区)** | 负责 Blender UI 面板、操作符 (Operators)、属性注册 (Properties)、标准 PBR 着色器材质节点树生成、场景层级装配，以及通过 `bridge/` 层消费底层 Rust 核心能力。 |
| **`../libmozitoolkit`** | **Rust 核心引擎 (`libmtk`)** | 纯数据、无宿主依赖的通用 3D/体素计算内核。包含几何重构、图集装箱、遮挡剔除、生物群系计算、PBR 预解码、RFC v3.1 同步客户端与 Python 绑定 (`libmtk_py`) 及独立宿主内存适配器 (`libmtk_blender_dna`)。 |
| **`../yefira`** | **实时协同服务端模组 (Live Sync Mod)** | 基于 Fabric / Forge / NeoForge 的 Minecraft 服务端伴生模组（跨 1.20.1 ~ 26.2 多版本）。负责服务端权威 3D 体素扫描 (CanonicalVoxelScanner)、XXHash64 校验、WebSocket 选区流式推送与 Loopback/Token 安全鉴权。 |

---

## 2. 核心规约与必须遵守的铁律 (Golden Rules)

### 规则 1：严禁在前端重写核心算法 (No Re-inventing the Wheel)
- 所有计算密集型操作（如像素网格切分、智能挤出侧面 UV 修复、随机噪声挤出、面遮挡剔除、图集装箱、Biome 调色板映射、PBR 贴图预解码）**必须且只能由底层原生核心处理**。
- 严禁在 Python 端自行实现复杂的 3D 几何、多边形裁剪、图像像素解码或色彩解算算法。

### 规则 2：Bridge 胶水层单一调用与纯数据交换原则 (Pure Data-Exchange Bridge)
- **UI 与操作符隔离**：UI 面板（`ui/`）和操作符（`operators/`）**绝不允许直接 `import libmtk_py` 或 `libmtk_blender_dna`**，必须统一通过 `bridge/` 模块交互。
- **纯数据交换原则 (B6 架构规范)**：
  - `bridge/` 是**纯数据转换与验证桥梁**，必须保持 Data-In, Data-Out 契约；
  - **严禁在 `bridge/` 中编写宿主业务编排逻辑**（如 Blender 物体创建、材质节点树链接、Collection 层级管理、本地注册表读写），所有宿主编排逻辑统一收敛在 `utils/`；
  - **严禁虚假降级与静默吞错 (No Fake Fallbacks)**：全面移除 Python 端假数据生成分支与 broad `except` 吞错重试。原生核心未就绪或参数非法时必须抛出明确异常或走统一门禁；
  - 启动与动态调用严格遵循 API 握手契约（`handshake`）。

### 规则 3：批量灌入与零拷贝优先原则 (Batch & Zero-Copy)
- 在 Blender 中读写网格几何时，优先使用 `libmtk_blender_dna` 原生指针直写，或使用 `b_mesh.vertices.foreach_set`、`b_mesh.loops.foreach_set`、NumPy 数组及 memoryview 批量通道。
- 严禁在 Python 中对成千上万个顶点或面进行逐元素循环（如 `for v in mesh.vertices:` 修改坐标），避免造成 Blender 界面卡顿。

### 规则 4：双轮子体系、双态开发架构与严禁全局 bpy 污染 (Dual-Wheel & Dual-Mode Dev/Release)
- **双轮子体系 (Dual-Wheel Architecture)**：
  - 底层原生库分为通用的 `libmtk_py`（宿主无关纯计算内核）与独立的 `libmtk_blender_dna`（Blender C++ 内存直写特化适配器），通过 CI 矩阵构建为符合 CPython 3.11+ 标准 ABI (`abi3`) 的跨平台 Wheel。
- **开发态（Development Mode）极速直通规约**：
  - 日常开发阶段工作区根目录不存放固定本地 wheel，`blender_manifest.toml` 中不声明开发期本地轮子。
  - 底层二进制扩展统一由 `dev/loader.py` 动态加载，通过软链接（`dev/lib/libmtk_py.so` 与 `dev/lib/libmtk_blender_dna.so`）直通 Rust 编译产物，编译后 Blender 重载插件即可即时生效。
  - 开发专用面板、压测与调试算子统一收敛在 `dev/` 模块，并通过 `dev/api.py` 提供无头测试支持。
- **发布态（Release Packaging）纯净隔离规约**：
  - 打包由 `python3 build.py` 处理；打包脚本拉取/注入对应平台的 release wheels 并更新 `blender_manifest.toml` 的 `wheels = [...]` 字段。
  - 打包过程**物理剔除 `dev/` 文件夹**，交回 Blender 4.2+ 原生扩展平台隔离机制，确保发售包自包含且绝对纯净。
- **严禁安装在宿主全局 bpy / Python 环境中**：
  - 严禁通过 `pip install` 将轮子安装到宿主 Blender 全局 `bpy` 或系统全局 Python 环境，杜绝沙箱污染。

### 规则 5：Blender 4.2+ 扩展清单规范 (Manifest Integrity)
- 本插件遵循 Blender 4.2+ Extension 标准。版本号、权限、依赖项与元数据必须同步维护在 `blender_manifest.toml` 中。
- 每次新增、更新或调整轮子文件名/版本时，必须同步更新清单中的 `wheels` 列表。

### 规则 6：标准化预解码 PBR 材质管线 (Canonical Pre-decoded PBR Pipeline)
- **预解码权威通道**：所有 PBR 属性（LabPBR 等）在 Rust 预编译期（`ASSET_CACHE_FORMAT_VERSION = 5`）解码为规范的 PBR 图集通道（Albedo, Normal_GL, Roughness, Metallic, Aux/Emission），丢弃原始 `_n` / `_s`。
- **彻底清除旧材质依赖**：
  - 严禁在运行期动态生成 LabPBR 复杂解码器节点树；
  - 严禁使用过时的 `mtk_material_props` 物理属性表或逐面字符串属性展开；
  - 前端材质统一使用标准 `Principled BSDF` 节点树，并通过属性向量化驱动。

### 规则 7：操作符与业务逻辑模块化规范 (Operator Modularity)
- **严禁创建单文件巨石操作符**：当操作符逻辑涉及“属性定义 (Properties)”、“后台定时器/Depsgraph 监听 (Watcher/Handler)”与“多个用户算子 (Operators)”时，严禁堆叠在同一个大文件中。
- **强制采用子包架构**：必须参照 `operators/extrude/` 与 `operators/sync/` 架构建立专属子目录包（包含 `__init__.py`, `properties.py`, `watcher.py`, `op_xxx.py`）。
- **文件行数软约束**：除纯静态查找表外，业务逻辑代码单文件原则上控制在 500 行以内。

### 规则 8：Blender 5.x / 6.0 API 前瞻兼容规范 (Forward Compatibility)
- **严禁使用即将废弃的属性**：严禁直接在代码中编写 `mat.use_nodes = True`（在 Blender 5.2 中已标记废弃，Blender 6.0 彻底移除）。必须通过直接操作/判断 `mat.node_tree` 维持兼容。
- **现代着色器节点兼容**：严禁使用已弃用的 `ShaderNodeMixRGB`，必须统一采用 modern `ShaderNodeMix`（`data_type='RGBA'`）。

### 规则 9：全链路执行诊断与性能探针规范 (Diagnostics & Profiling Probes)
- 所有核心网格生成、重构与 Live Sync 算子必须接入 `bridge.diagnostics` 探针体系。
- 算子完成报告与 Dev 面板中必须清晰拆分并输出 Rust 核心计算耗时与 Blender 宿主装配耗时，杜绝性能黑盒。

### 规则 10：原版客户端资产权威门禁 (Vanilla Client Asset Gate)
- 任何体素世界构建、图集预烘焙与网格重建，必须依赖真正的 Minecraft 原版客户端资产（JAR / 解包客户端目录），严禁绕过门禁使用无资产假数据，杜绝无 UV 灰模。

### 规则 11：实时协同 Protocol v3 契约规范 (Live Sync Protocol v3 & Security)
- 严格遵循 RFC v3.1 协议标准与服务端权威机制；
- 握手决策码 (`decision_code`)、流进度归一化 (`normalize_stream_progress`) 与增量合并由 Rust 核心统一裁决；
- 网络通信支持安全 Token 鉴权，默认启用 Loopback 本地连接免密直连；选区操作必须遵循原子化与软硬上限保护。

### 规则 12：代码检索与构建目录过滤规范 (Code Search & Target Exclusion)
- **优先使用 ripgrep (`rg`)**：在工作区检索代码、资产引用或符号时，首选且尽量使用 `rg`。
- **使用 `grep` 时必须忽略 `target` 目录**：必须显式添加 `--exclude-dir=target`（以及 `--exclude-dir=.git`、`--exclude-dir=__pycache__`、`--exclude-dir=.venv` 等），严禁扫描底层 Rust 构建产物与缓存。

### 规则 13：测试门禁与测试资产规范 (Test Gate & Asset Policy)
- **两个测试模式缺一不可**：
  - **Mock 快速模式（无 Blender，CI 首选）**：`python -m pytest tests/ -q`（验证 Bridge 与纯数据逻辑）；
  - **Blender 宿主模式（真实 bpy / 节点树 / 算子）**：`blender --background --python tests/run_tests.py -- -q`。`tests/run_tests.py` 是唯一测试入口。
- **测试资产统一走 `tests/_assets.py`**：定位依赖资产，严禁硬编码个人绝对路径；缺失时必须优雅跳过（`pytest.skip` / `unittest.SkipTest`）。
- **开发环境严禁全局污染**：开发态必须依赖 `dev/lib/` 直连产物，严禁在 `.venv` 中保留陈旧 `libmtk_py` wheel 假象。
- **提交前必须通过**：Mock 模式全绿；涉及 bpy 的变更还需 Blender 宿主模式全绿。

---

## 3. 插件目录架构

```
MoziToolKit/
├── blender_manifest.toml -> Blender 4.2+ 扩展清单元数据 (声明双 wheel)
├── __init__.py           -> 插件生命周期入口
├── bridge/               -> 纯数据交换桥梁 (Data-In Data-Out，零业务宿主编排)
│   ├── mesh/             -> 几何网格拓扑转换、NumPy 批量提取、DNA 指针直灌与属性注入
│   ├── point_cloud/      -> 体素点云几何流提取与回灌 (DNA / Standard Palette)
│   ├── extrude.py        -> 原生 C++/Rust 挤出修复与噪声计算桥接
│   ├── subdivide.py      -> 原生像素网格切分与任意旋转 UV 修复桥接
│   ├── texture.py        -> 贴图采样与透明度分析桥接
│   ├── material.py       -> 规范 PBR 材质路由与 Palette Biome 数据桥接
│   ├── assets.py         -> 权威原版资产门禁与缓存包解析桥接
│   ├── sync.py           -> RFC v3.1 Live Sync 会话生命周期与事件合并桥接
│   ├── world.py          -> 体素存储网格化 (VoxelWorld) 与 FaceCuller 缓存
│   ├── save.py           -> 存档 Anvil 解包与纯数据切片桥接
│   ├── uv.py             -> UV 几何数学与重映射桥接
│   └── diagnostics.py    -> 端到端性能分析探针桥接
├── dev/                  -> 开发专用直连扩展与无头测试工具 (发布时自动剔除)
│   ├── lib/              -> 软链接直连 Rust 核心产物 (libmtk_py.so, libmtk_blender_dna.so)
│   ├── loader.py         -> 动态加载器
│   └── api.py            -> 面向自动化测试与无头 DCC 的开发 API
├── operators/            -> Blender 操作符 (响应 UI 事件)
│   ├── extrude/          -> 智能挤出与实时修复模块包 (Watcher, Properties, Ops)
│   ├── sync/             -> 原生 Live Sync 实时协同模块包 (Watcher, Properties, Ops)
│   ├── save/             -> 存档导入与模型原地刷新算子
│   └── ...               -> 像素切分 (op_pixel_split) 等独立算子
├── ui/                   -> 3D 视图侧边栏面板、状态指示卡片与上下文菜单
├── utils/                -> DCC 宿主业务装配、流程编排、节点树与材质管线
│   ├── assets/           -> 资产缓存目录解析、系统文件夹管理、Modrinth 下载、任务守卫
│   ├── world/            -> VoxelWorld 场景对象注入器 (apply_voxel_mesh_to_blender)
│   ├── point_cloud/      -> 点云层级、Mask 修改器与父子对象管理
│   ├── materials/        -> 标准 PBR 节点树构建器 (pbr_graph, atlas_builder) 与 Biome 更新
│   ├── mesh/             -> BMesh 高阶几何计算、选区与归属标记
│   ├── save/             -> 存档场景层级组织与导入编排 (hierarchy, registry)
│   └── system/           -> 偏好设置、菜单注册、系统依赖与 SaveRegistry
├── wheels/               -> 跨平台 pre-built wheels (发布包注入)
├── docs/                 -> 架构设计手册、RFC 协议规范与计划文档
└── tests/                -> 自动化测试套件 (Mock 单元测试 + Blender 宿主回归测试)
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
  MTK_TEST_SITE_PACKAGES="$(python -c 'import site; print(site.getsitepackages()[0])')" \
    blender --background --python tests/run_tests.py -- -q
  ```

### 2. 多工作区联动验证
- Rust 核心改动后在 `../libmozitoolkit` 执行 `cargo test` 与 `maturin build`；
- 通过 `dev/lib/` 软链接在 Blender 宿主或测试中即时验证；
- 涉及网络协同协议调整时，在 `../yefira` 运行 `./gradlew test` 验证服务端 WebSocket 与编码器。

---

## 5. 版本路线与开发计划

- [TODO.md](./TODO.md)
