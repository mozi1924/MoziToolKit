# GEMINI.md - MoziToolKit (Blender Addon) 架构与开发规范

本文档是 `MoziToolKit` 工作区的核心架构准则与开发铁律。全局通用开发规范与 CLI 工具偏好遵循用户全局规则。

---

## 1. 项目定位与协同拓扑

- **本工作区职责**：基于 Blender 4.2+ 的 DCC 插件前端，负责 UI 交互、操作符 (Operators)、标准 PBR 着色器节点构建、场景装配与 Save/Sync/.mtkscene 编排。
- **协同边界**：
  - 底层计算消费相对路径 `../libmozitoolkit` 产出的原生绑定 (`libmtk_py` / `libmtk_blender_dna`)；
  - 实时世界协同对接相对路径 `../yefira` 服务端 (RFC v3.1)。

---

## 2. 核心架构规约与铁律 (Golden Rules)

### 规则 1：严禁前端重写核心算法 (No Re-inventing the Wheel)
- 网格切分、UV 智能修复、挤出噪声、面遮挡剔除、图集装箱、Biome 映射、Mini-Atlas 裁剪与场景包解算等密集计算**必须由底层原生核心处理**，严禁在 Python 端自行实现几何裁剪或像素色彩解算。

### 规则 2：Bridge 胶水层纯数据交换规范 (Pure Data Bridge)
- **层级隔离**：`ui/` 和 `operators/` **绝不允许直接 import `libmtk_py` 或 `libmtk_blender_dna`**，必须统一经由 `bridge/`。
- **Data-In, Data-Out**：`bridge/` 严禁编写 Blender 宿主业务编排（如物体创建、材质节点树链接，统一收敛在 `utils/`）。
- **零假降级 (No Fake Fallbacks)**：全面移除 Python 假数据生成与静默吞错，原生核心未就绪或参数非法时抛出明确异常或走统一门禁。

### 规则 3：双通道批量灌入与安全降级规范 (Dual-Channel Ingestion & Safe Fallback)
- **双通道架构**：
  1. **Fast-Path (DNA 直写零拷贝)**：通过 `libmtk_blender_dna` 直写 C++ 内存指针，作为极速加速插件。
  2. **Safe-Path (官方安全批量通道)**：基于 Blender 官方稳定 `foreach_set` / `Attribute.data.foreach_set` 批量灌入。
- **解耦与降级铁律**：严禁将 DNA 直写作为不可替代的硬性依赖。当未来 Blender 版本 DNA 结构变化、指针校验失败或用户手动关闭零拷贝（`use_dna=False`）时，系统必须无缝回退至官方批量通道，且保证几何、UV、属性 100% 一致。严禁在 Python 中逐顶点/面循环修改。

### 规则 4：双轮子开发态直通与发布态隔离 (Dual-Wheel Architecture)
- **开发态**：通过 `dev/lib/` 软链接直连相对路径 `../libmozitoolkit` 的 Rust 构建产物（`libmtk_py.so`, `libmtk_blender_dna.so`），由 `dev/loader.py` 动态加载，即改即生效。
- **发布态**：由 `python3 build.py` 物理剔除 `dev/` 目录并注入平台 wheels，更新 `blender_manifest.toml`。
- **严禁全局安装**：严禁通过 `pip install` 将轮子安装到宿主全局 bpy 或系统环境中。

### 规则 5：标准预解码 PBR 材质管线 (Canonical PBR Pipeline)
- 所有材质统一基于标准 `Principled BSDF` + 属性向量化驱动；严禁在运行期动态生成 LabPBR 复杂解码节点树，严禁使用过时的 `mtk_material_props` 物理属性表。

### 规则 6：Blender 4.2+ / 5.x / 6.0 前瞻兼容与结构体规范
- **禁止废弃 API**：严禁编写 `mat.use_nodes = True`（5.2 废弃，6.0 移除），必须直接操作/判断 `mat.node_tree`。
- **现代节点**：严禁使用 `ShaderNodeMixRGB`，统一使用 modern `ShaderNodeMix` (`data_type='RGBA'`)。
- **结构体属性只读**：在真实 Blender 中，`Object.type` 是只读属性（在创建时由 `bpy.data.objects.new(name, data)` 自动确定，传入 `None` 为 `"EMPTY"`，传入 mesh 数据块为 `"MESH"`），严禁对其进行直接赋值。
- **操作符架构与测试规范**：复杂操作符必须采用独立子包架构（如 `operators/scene/`、`operators/extrude/`、`operators/sync/`），严禁巨石单文件。测试中由于 Blender `bpy.types.Operator` 无法直接实例化，统一采用 `MOZI_OT_xxx.execute(mock_op, context)` 模式。

### 规则 7：RFC v3.1 协议与权威资产门禁
- Live Sync 严格遵循 RFC v3.1 契约、服务端权威机制与状态机。
- 世界构建与网格重构必须依赖 Minecraft 原版权威资产门禁，严禁无资产灰模降级。

### 规则 8：场景交换格式 (.mtkscene) 与伴生体素点云
- **自包含场景包**：`.mtkscene` 作为中间场景交换格式，内含紧凑稀疏体素 (Sparse Voxels)、按需裁剪装箱的自包含 Mini-Atlas (含 UV 自动重映射)、Tree-Shaken 方块模型库，实现脱离原版资源的独立便携共享。
- **伴生体素点云 (Voxel Point Cloud)**：几何网格与体素数据通过 companion point cloud 建立 0ms 快速链接（标识属性 `mtk:is_voxel_cloud`），支持非破坏性视口遮罩与体素雕刻。

---

## 3. 插件目录架构

```
MoziToolKit/
├── blender_manifest.toml -> Blender 4.2+ 扩展清单
├── bridge/               -> 纯数据交换桥梁 (Data-In Data-Out，零宿主业务)
│   ├── scene.py          -> .mtkscene 场景交换与 Mini-Atlas 导出桥
│   ├── point_cloud/      -> 伴生点云双通道数据桥
│   └── ...
├── dev/                  -> 开发专用直连扩展与无头测试 (发布时物理剔除)
│   └── lib/              -> 软链接至 ../libmozitoolkit 的构建产物
├── operators/            -> Blender 操作符子包 (响应 UI，按功能解耦)
│   ├── scene/            -> .mtkscene 导入/导出操作符
│   ├── sync/             -> Live Sync 同步操作符
│   ├── extrude/          -> 像素挤出操作符
│   └── ...
├── ui/                   -> 3D 视图面板与上下文菜单 (含菜单挂载 menu_import/menu_export)
├── utils/                -> DCC 宿主业务装配 (世界注入器、PBR 节点树、层级管理)
│   ├── scene/            -> .mtkscene 层级装配与自包含材质挂载
│   ├── point_cloud/      -> 伴生点云层级、修改器与遮罩管理
│   └── ...
├── docs/                 -> 架构手册与 RFC 协议文档
└── tests/                -> 自动化测试套件
```

---

## 4. 测试与验证门禁

所有测试命令均基于 `uv` 虚拟环境与相对路径执行，杜绝全局 Python 污染：

- **Mock 快速测试（CI 默认门禁）**：
  ```bash
  # 全套测试
  uv run pytest tests/ -q

  # 运行指定测试用例
  uv run pytest tests/test_scene_interchange.py -q
  ```

- **Blender 宿主环境测试（真实 bpy，5.x LTS）**：
  必须通过 `uv run python` 解析虚拟环境的 `site-packages`，确保 Blender 内置 Python 能加载 `pytest` 等依赖：
  ```bash
  MTK_TEST_SITE_PACKAGES="$(uv run python -c 'import site; print(site.getsitepackages()[0])')" \
    blender --background --python tests/run_tests.py -- -q
  ```

- **Rust 原生模块热更新验证**：
  当相对路径 `../libmozitoolkit` 源码修改后，可一键重新编译并刷新 `dev/lib/` 软链接：
  ```bash
  (cd ../libmozitoolkit && cargo build-all-py)
  ```

- **测试资产定位**：
  测试资产统一走 `tests/_assets.py` 动态解析，缺失时必须优雅跳过 (`pytest.skip`)，严禁硬编码绝对路径。
