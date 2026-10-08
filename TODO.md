# 📋 MoziToolKit (Blender Addon) 开发计划与 TODO 清单

本文档为 `MoziToolKit` Blender 插件前端的功能演进与任务规划清单。底层核心算法、体素流与几何计算见 [`libmozitoolkit/TODO.md`](../libmozitoolkit/TODO.md)。

---

## 阶段一：小三样核心网格与 UV 工具库（✅ 已完成）
- [x] **自适应像素网格切分前端 (`operators/op_pixel_split.py`)**
  - [x] 封装 `bridge/subdivide.py`，与 Rust 后端 `adaptive_pixel_split_mesh` 零拷贝通信。
  - [x] UI 侧边栏参数绑定（像素密度、最大切分数、微距焊接阈值）。
  - [x] 自动保留顶点色、UV、Deform 蒙皮权重等原生 Blender 属性。
- [x] **智能挤出与 UV 修复系统前端 (`operators/extrude/`)**
  - [x] 模块化重构为子包架构（`properties.py`, `watcher.py`, `op_auto_extrude_repair.py`, `op_random_extrude.py`）。
  - [x] 封装 `bridge/extrude.py`，支持 SMART / INWARD / OUTWARD 模式。
  - [x] Blender 4.2+ 实时编辑模式 Depsgraph 动态监听与 UV 即时修复。
  - [x] 3D 噪声与随机高度挤出操作符及 UI 控制面板。
  - [x] 自动标记锐边 Crease，保持边缘硬朗着色。
- [x] **外部网格面遮挡剔除前端 (`operators/op_cull.py`)**
  - [x] 封装 `bridge/cull.py`，调用 Rust 6 向邻域遮挡分析。
  - [x] 一键清理 Mineways / MiEx 导入资产的内部重叠废面。

---

## 阶段零：会话生命周期与跨工程深度清理（✅ 已完成）
- [x] **跨工程加载深度断开与清理器 (`operators/sync/properties.py`, `bridge/sync.py`)**
  - [x] 注册 `bpy.app.handlers.load_pre` 钩子，调用 `session.stop()` 切断网络连接。
  - [x] 强制注销并终止活跃的 `bpy.app.timers`（防止定时器跨工程残留跳动）。
  - [x] 清理全局 `SyncBridgeSession` 内存单例，防止跨工程引用已失效的旧场景数据。
  - [x] 注册 `bpy.app.handlers.load_post` 钩子，重置场景与物体的连接状态（`is_connected=False`, `DISCONNECTED`）。
- [x] **底层 TCP 连接强制关闭配合 (`libmozitoolkit::mtk-sync`)**
  - [x] 在 `SyncClient::stop()` 中针对底层 TCP Stream 触发 `shutdown(Shutdown::Both)`，确保工程切换时远端 Minecraft 服务端瞬间感应连接断开，杜绝新工程提示“端口占用”。
- [x] **自动化测试验证**
  - [x] 编写跨工程加载与会话状态集成测试（`tests/test_sync_lifecycle_and_session.py`，验证生命周期、定时器清理与状态切换）。

---

## 阶段零点五：Blender 5.2 (Python 3.13) 宿主兼容与类注册稳健性（✅ 已完成）
- [x] **Python 3.13 严格类型注解与类注册保护 (`operators/op_mesh.py`)**
  - [x] 补齐顶层 `typing` 显式导入，防止 `bpy.utils.register_class` 触发 `get_type_hints` 时因未导入符号报错崩溃。
  - [x] 地毯式扫描全插件 97 个注册类，验证 Python 3.13 环境下注解求值 100% 正常。
- [x] **Blender 5.2 PropertyGroup 结构体标准对齐**
  - [x] 为全量 PropertyGroup（挤出、实时同步、偏好设置）补充 `__slots__ = ()`，消除结构警告。
- [x] **双测试门禁（Mock vs Blender 5.2 真实宿主）全绿通过**
  - [x] Mock 快速模式：140 项测试全过。
  - [x] Blender 5.2 真实宿主模式：197 项测试全过（涵盖真实 Mesh 拓扑、RNA 属性与算子执行）。

---

## 阶段一：多会话架构与 Empty 容器统一层级规范（✅ 已完成）
- [x] **伴生体素点云子物体结构与全量持久化 (`hierarchy.py`, `bridge/point_cloud.py`)**
  - [x] 废弃独立集合隔离，对齐世界网格挂载伴生点云子物体（`ensure_voxel_child_cloud`）。
  - [x] 自动承载未遮挡剔除体素元数据、Attributes 绑定与 Mask 修改器一键显隐。
- [x] **统一 Empty 根容器与平铺子物体结构演进**
  - [x] 升级为标准 Empty 根容器：
    ```text
    📁 Container Root (Empty, mtk:is_container=True, mtk:container_id=...)
    ├── 🧊 World Mesh (Mesh, 几何面与多材质槽)
    └── ☁️ Point Cloud (Mesh/PointCloud, 存储未剔除体素与元数据，默认隐藏)
    ```
  - [x] 重构 `get_or_create_world_mesh_object` 与 `update_world_mesh`，确保 Mesh 与 PointCloud 挂载为 Empty 根容器子物体。
- [x] **多会话上下文感知与属性隔离 (`properties.py`, `ui/panel_sync.py`)**
  - [x] 编写 `resolve_world_root_object(obj)` / `find_root_container(obj)` 向上寻址解析器，无论选中容器、网格还是点云，均精准定位根容器。
  - [x] 将会话属性绑定至每个 Container 物体本身（独立的 URL、选区坐标、顶点统计与连接状态），实现多会话完全并行隔离与防串流。
  - [x] 单一活跃会话互斥保护机制（检测到多容器同步冲突时弹出友好确认切换对话框）。
  - [x] 属性面板深度优化：移出场景 Scene 选项卡，Empty 根容器显示于绿色 Object Data 选项卡，子物体显示于橙色 Object 选项卡。
- [x] **容器与子物体重命名级联同步 (`watcher.py`)**
  - [x] 恢复 `bpy.app.handlers.depsgraph_update_post` 监听机制。
  - [x] 当用户在大纲视图重命名 Empty 容器时，自动级联同步更新子网格与子点云名称（如 `MyWorld_Mesh`, `MyWorld_PointCloud`）。
  - [x] 活跃连接中防 Edit Mode 误操作保护机制（自动回退至 Object Mode）。

---

## 阶段二：网格重构脏缓存校验与顶层右键菜单解耦（P1 - 功能解耦 🚧 进行中）
- [x] **基于体素点云的网格重构算子与右键菜单化 (`operators/op_voxel_cloud.py`)**
  - [x] 从点云数据提取并无损重构网格算子（`mozi.remesh_from_voxel_cloud`，支持用户手动删点雕刻并即时重构）。
  - [x] 重构材质与图集贴图绑定算子（`mozi.rematerialize_from_voxel_cloud`）。
  - [x] 通过 `@register_menu_item(views=["object", "mesh"])` 直接注入 3D 视图右键上下文菜单。
  - [x] 实时同步内存体素世界异步重构算子（`mozi.sync_rebuild_world`，支持 `ModalTaskRunner` + 进度汇报）。
- [x] **网格重构前缓存指纹一致性检查 (`bridge/sync.py`, `op_sync_rebuild.py`)**
  - [x] 在触发网格重构前，检查磁盘 `assets_cache/cache_manifest.json` 或文件时间戳。
  - [x] 若检测到用户在偏好设置中重新预编译/重新配置材质包：
    1. 动态重新加载最新 Atlas、ModelDatabase 与 BiomeResolver；
    2. 调用 Rust 端 `VoxelWorld::clear_cache()`，强制清除脏区块网格缓存（`section_mesh_cache`）；
    3. 重新执行全量网格化，并同步更新 Blender 材质节点树中的图集图像节点，彻底杜绝 UV 偏移与模型错乱。
- [x] **顶层通用网格重构统一门面算子 (`operators/op_mesh.py`)**
  - [x] 智能判定所选物体的体素源（实时同步容器 / 存档导入容器 / 点云物体），统一收拢派发至单一入口 `mozi.rebuild_mesh`。
  - [x] 右键上下文菜单与默认预设无缝集成（`CANONICAL_DEFAULT_PRESETS`，支持对象与网格视图一键重构）。

---

## 阶段三：Minecraft 存档导入容器化、无感刷新与隐私 UUID 体系（✅ 已完成）
- [x] **Minecraft 存档端到端导入前端（✅ 已完成基础链路 - commit `8ad56fc`）**
  - [x] 顶部主菜单接入（`File -> Import -> Minecraft World / Save (.mca / level.dat)`，`ui/menu_import.py`）。
  - [x] 世界路径选取、维度选择（主世界/下界/末地）与 `level.dat` 元数据自动探测。
  - [x] 3D 轴对齐选区坐标输入与方块体积统计实时预览。
  - [x] 零拷贝网格流极速灌入（AO、流体、顶点焊接、原点居中，`bridge/save.py`）。
  - [x] 依据体素元数据自动创建并分配多材质槽与 Principled BSDF 节点树。
  - [x] 自动提取并生成伴生体素点云子物体 (`ensure_voxel_child_cloud`)。
  - [x] 物体自定义属性存储元数据（选区坐标、世界名、数据版本等）。
- [x] **存档导入非破坏性独立容器化 (`operators/save/op_import_save.py`, `bridge/save.py`)**
  - [x] 存档导入时自动创建独立 Empty 根容器（如 `Save_WorldName_Dimension_01`），子网格与子点云收拢于容器内。
  - [x] 连续导入新选区时绝不覆盖历史已导入的存档物体，自动递增序号新建容器。
  - [x] 根容器与子物体完整记录 AABB、维度、AO、流体、居中与材质参数自定义属性。
- [x] **本地隐私注册表管理器 (`utils/system/save_registry.py`)**
  - [x] 实现基于用户本地配置目录的 `SaveRegistryManager`，在 `CONFIG/MoziToolKit/save_registry.json`（与右键菜单 `context_menus.json` 同目录）中记录：
    ```json
    {
      "uuid_hash": {
        "world_dir": "/path/to/local/saves/WorldName",
        "dimension": "overworld",
        "last_refreshed": 1728100000
      }
    }
    ```
  - [x] `.blend` 内部仅存储 `mozi_save_uuid` 以及不涉密的 AABB 选区与维度，彻底杜绝个人本地绝对路径随工程文件泄露。
  - [x] 提供 `sanitize_save_privacy` 自动清洗与静默迁移旧工程中的绝对路径属性。
- [x] **存档专属面板与“一键刷新模型”算子 (`ui/panel_save.py`, `op_refresh_save.py`, `op_relink_save.py`)**
  - [x] 物体属性面板中为存档容器展示专属信息卡片（选区坐标、体积、几何信息、最后更新时间）。
  - [x] 提供 **“🔄 刷新模型 (Refresh Model)”** 按钮：按原选区重新解包 MCA/NBT 并原地无感替换网格。
  - [x] 异地工程加载安全回退与重新关联：当其他用户打开工程或本地路径移动时，弹出友好提示并提供“重新关联本地存档路径”算子（`mozi.relink_save_folder`）。


---

## 阶段四：右键菜单管理器自适应与全域 UI/UX 深度重构（P2 - 交互精修 🚧 进行中）
- [x] **统一异步任务与分阶段物理进度条流水线（✅ 已完成 - commit `8119e06`, `4ac500d`, `30bf638`）**
  - [x] 封装统一的 Blender 模态异步进度汇报器 (`utils/progress.py` -> `BlenderProgressReporter`, `wrap_progress_callback`)。
  - [x] 非阻塞后台任务执行框架 (`utils/async_task.py` -> `AsyncTask`, `ModalTaskRunner`)。
  - [x] 资产预编译多阶段进度汇报 (`op_precompile.py`)。
  - [x] 实时网络同步多阶段下载与网格化进度追踪 (`StreamProgress` -> `sync_download`, `sync_meshing`, `sync_request`)。
  - [x] 存档导入物理进度接入与状态栏即时提示。
- [x] **材质与资产缓存管理 API 与开发面板（✅ 已完成 - commit `b16fb5d`）**
  - [x] 材质图集与模型预编译缓存清除与重建 API (`bridge.clear_cache`, `bridge.precompile_stack`)。
  - [x] Dev 开发调试面板中的缓存状态监视器与一键预编译/清除算子。
- [x] **右键菜单智能差集自适应合并与 Schema 迁移（✅ 已完成）**
  - [x] 引入 `menu_schema_version` (v2) 版本迁移机制 (`utils/config/models.py`)。
  - [x] 插件启动加载配置时自动执行 `reconcile_views_with_canonical_presets`：
    - 比对内建 `CANONICAL_DEFAULT_PRESETS` 与用户已保存的 `views`，自动将新引入的内建推荐算子无缝并入菜单列表；
    - 严格保留用户已有的自定义排序、自定义标签以及启用/禁用开关；
    - 告别每次新增选项都要手动点击“重置右键菜单”的繁琐体验。
  - [x] 右键菜单项原生图标渲染（`MOD_REMESH`, `MATERIAL`, `GRID`, `UV_DATA` 等，提升视觉辨识度）。
  - [x] 偏好设置支持直接点击列表项开关 (`enabled` 复选框) 实时控制显示/隐藏，并支持单视图独立重置 (`reset_views(view_name)`)。
- [x] **全域 UI 面板风格现代化与整合（✅ 已完成）**
  - [x] 3D 视图 N 侧边栏及属性面板分区梳理：
    - 📡 **实时网络同步 (Live Sync)**：新增 `MOZI_PT_view3d_live_sync`，在 3D 视图 N 侧边栏直接掌控会话管理、多容器状态、URL、连接/断开与增量指标；未有容器时提供快速创建引导；
    - 📦 **世界存档导入 (World Saves)**：`MOZI_PT_view3d_save_container` 增加未选中存档物体时的“一键导入 Minecraft 存档”快捷入口，选中时完整展示选区与刷新卡片；
    - 🧊 **体素与网格工具 (Voxel Tools)**：重构升级为 `MOZI_PT_view3d_voxel_tools`，集成通用网格重构、伴生点云雕刻、自适应像素网格切分、面遮挡剔除、流体 UV 修复与材质法线工具；
  - [x] 国际化字典全量补齐（`i18n/dictionary.py` 同步覆盖所有新增 UI 标签与提示）。

---

## 阶段五：通用二进制中间包与场景交换前端对接 (`.mtkscene` / `.mtkcache` - 进行中 🚧)
- [x] **设计规范对齐（✅ 已落地）**
  - [x] 底层容器规范与分块协议对齐：见 [`libmozitoolkit/docs/PACKAGE_SPEC.md`](../libmozitoolkit/docs/PACKAGE_SPEC.md)。
- [x] **全量资产缓存单文件包挂载 (`bridge/assets.py` - ✅ 已完成)**
  - [x] 后端与前端全面切换至单一 `.mtkcache`（`<fingerprint>.mtkcache`）二进制容器，彻底替代散文件扫描。
  - [x] 分块压缩策略：原始数据/模型/元数据采用 Zstd 块级压缩，贴图保持 Raw PNG 流，杜绝二次压缩性能开销。
  - [x] 材质管线按需解包纹理并对齐 Blender Cycles/Eevee 材质节点树加载。
- [ ] **场景交换格式导入算子 (`operators/package/op_import_scene.py`)**
  - [ ] 顶部菜单集成：`File -> Import -> MoziToolKit Scene Package (.mtkscene)`。
  - [ ] 导入选项面板：
    - 网格化拓扑：平滑 AO、面遮挡剔除、贪婪网格化 (Greedy Meshing) 开关；
    - 材质策略：现场烘焙紧凑微图集 (On-the-fly Atlas) vs 独立 Principled BSDF 材质。
  - [ ] 调用 `bridge/package.py` 驱动 Rust 现场重构网格并生成材质节点树。
- [ ] **场景交换格式导出算子 (`operators/package/op_export_scene.py`)**
  - [ ] 顶部菜单集成：`File -> Export -> MoziToolKit Scene Package (.mtkscene)`。
  - [ ] 支持所选物体/容器（无论是 Live Sync 容器、Save 存档容器还是体素点云）一键导出为 `.mtkscene`。
  - [ ] 自动树状剪枝（Tree-shaking），仅打包选区内实际引用的独立贴图与方块模型，生成轻量自包含分享包。

---

## 阶段六：现代 Blender 5.0+ 极致批量写入与零拷贝现代化重构（P0 架构性能演进 🚧 待启动）

> 基于 Blender 5.2.1 LTS 现场 MCP 内存探查与压测，彻底铲除插件内残留的 2.x/3.x 时代低效 Python 遍历与 BMesh 过程式拼装模式，全面换装现代通用属性（Generic Attributes）批写入与零拷贝数据通道。

- [ ] **任务一：自适应像素切分算子整体管道化重构（彻底抛弃 BMesh 逐面循环）**
  - [ ] 彻底废弃 [`utils/mesh/subdivide.py`](utils/mesh/subdivide.py) 中的逐面 `slice_polygon_face_by_pixel_grid` 以及 Python 循环创建 BMVert / BMFace / 逐项权重插值的低效模式。
  - [ ] 将 [`op_pixel_split.py`](operators/op_pixel_split.py) 全面重构为对接 Rust 的单次批量 Data-In Data-Out 管道：
    1. 前端通过 `extract_mesh_data`（支持全选区）一次性提取网格连续流；
    2. 单次调用 Rust `bridge.subdivide.adaptive_pixel_split_mesh`（Rayon 多核并行切分、UV/顶点色/Deform权重/自定义属性双线性插值、空间哈希焊点一次性完成）；
    3. 单次通过 `inject_mesh_data` 批量回灌 Blender。
  - [ ] 目标性能：大型网格切分耗时从 3~8 秒下降至 20~50 毫秒（提速 100x+）。

- [ ] **任务二：字符串面属性“调色板化（Palette Indexing）”改造**
  - [ ] 破局 Blender C RNA 对字符串属性执行 `foreach_set` 报错（`internal error setting the array`）引发的慢速 Python `for i, val in enumerate(values): attr.data[i].value = val` 循环。
  - [ ] 将面域 `mtk_source_texture_key`、点云 `block_state`、`biome` 全面重构为 **`INT` 索引属性 + 网格/物体级 `ID-Property` 调色板数组**：
    - 面属性写入：`mesh.attributes.new(name="mtk_source_texture_idx", type="INT", domain="FACE")`，通过 `foreach_set("value", np_indices)` 批量写入（10万面耗时 < 0.5ms）；
    - 调色板存储：`mesh["mtk_source_textures"] = [...]`；
    - 读取端兼容适配：提供统一的 `resolve_source_texture_keys(mesh)` 助手方法，优先读取 `INT` + `palette`（微秒级），优雅兼容旧工程遗留的 String 属性；
    - 彻底删除 [`bridge/mesh.py`](bridge/mesh.py) 和 [`point_cloud.py`](bridge/point_cloud.py) 中的海量面 Python 遍历赋值循环。

- [x] **任务三：材质槽重映射与生物群系实时更新器向量化加速（✅ 已完成）**
  - [x] **材质槽重映射向量化 ([`cleaner.py`](utils/materials/cleaner.py), [`world.py`](bridge/world.py))**：
    - 废除 `[chunk_to_slot.get(int(idx), 0) for idx in poly_mats]` Python 列表推导；
    - 改用统一封装的 NumPy 查找表 `remap_indices_lut`：密集表一次性索引 `lut[poly_mats]`（10万面从 50ms 降至 0.2ms，提速 250x）；
    - 材质查重使用 `set(np.unique(poly_mats))` 代替 `{p.material_index for p in mesh.polygons}`。
  - [x] **生物群系实时调色器向量化 ([`updater.py`](utils/materials/biome/updater.py), [`biome.py`](utils/materials/biome/biome.py))**：
    - 废弃 `[list(d.color) for d in old_attr.data]` 与遍历 `tint_data_attr.data` 的逐元素 RNA 访问循环；
    - 改用 `tint_data_attr.data.foreach_get("color", raw_data)` + NumPy 向量化布尔掩码直接在连续内存上计算 `new_tint_colors`；
    - 改造 `apply_biome_tint_attributes` 支持直接接收一维连续内存 NumPy 数组向 `foreach_set` 零开销灌入；
    - 确保 20 万面的调色板动态切换真正达成宣称的 `< 1ms` 刷新响应。

- [ ] **任务四：网格拓扑校验与流体 UV 修复向量化**
  - [x] **拓扑全四边形校验 ([`bridge/mesh.py`](bridge/mesh.py))**：
    - 将 `all(getattr(p, "loop_total", len(p.vertices)) == 4 for p in mesh.polygons)`（20万次 Python 对象访问）重构为：
      ```python
      poly_totals = np.empty(num_polys, dtype=np.int32)
      mesh.polygons.foreach_get("loop_total", poly_totals)
      is_all_quads = bool(np.all(poly_totals == 4))
      ```
      耗时从 150ms 压缩至 0.3ms（提速 500x）。
  - [ ] **流体 UV 修复 ([`fluid_uv.py`](utils/mesh/fluid_uv.py))**：
    - 废弃单面循环 `for li in loop_indices: uv_layer.data[li].uv.x = u`；
    - BMesh 模式下消除逐顶点、逐面 Python 循环提取，优先在 Object Mode 走全量向量化 Mesh 路径；针对选区面支持批量 NumPy 提取与回写。

- [ ] **任务五：Rust $\leftrightarrow$ Blender 内存直接写入与零拷贝通道探索（进阶）**
  - [ ] 基于 MCP 实测结论（`mesh.attributes["position"].data[0].as_pointer()` 直指连续 C++ 内存）：
  - [ ] 在 `bridge/mesh.py` 与 `bindings/mtk-py` 建立可选的 `direct_write_to_ptr` 通道（通过 `ctypes.memmove` 或 Rust `std::ptr::copy_nonoverlapping`），将 10 万顶点/UV 写入耗时从 `foreach_set` 的 3.5ms 进一步压缩至硬件带宽级的 0.19ms（再提速 18x）。


