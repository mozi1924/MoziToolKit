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

## 阶段零：会话生命周期与跨工程深度清理（P0 - 核心稳定性 🚧 规划中）
- [ ] **跨工程加载深度断开与清理器 (`operators/sync/properties.py`, `bridge/sync.py`)**
  - [ ] 注册 `bpy.app.handlers.load_pre` 钩子，不仅调用 `session.stop()`，还要强制注销并终止活跃的 `bpy.app.timers`（防止定时器跨工程残留跳动）。
  - [ ] 清理全局 `SyncBridgeSession` 内存单例，防止跨工程引用已失效的旧场景数据。
  - [ ] 注册 `bpy.app.handlers.load_post` 钩子，重置场景与物体的连接状态（`is_connected=False`, `DISCONNECTED`）。
- [ ] **底层 TCP 连接强制关闭配合 (`libmozitoolkit::mtk-sync`)**
  - [ ] 在 `SyncClient::stop()` 中针对底层 TCP Stream 触发 `shutdown(Shutdown::Both)`，确保工程切换时远端 Minecraft 服务端瞬间感应连接断开，杜绝新工程提示“端口占用”。
- [ ] **自动化测试验证**
  - [ ] 编写跨工程加载集成测试（验证 `File -> New` / `File -> Open` 后无残留定时器与活跃套接字）。

---

## 阶段一：多会话架构与 Empty 容器统一层级规范（P1 - 结构规范 🚧 规划中）
- [ ] **统一 Empty 根容器与平铺子物体结构 (`hierarchy.py`)**
  - [ ] 废弃单网格作为根节点，还原为标准 Empty 根容器：
    ```text
    📁 Container Root (Empty, mtk:is_container=True, mtk:session_id=...)
    ├── 🧊 World Mesh (Mesh, 几何面与多材质槽)
    └── ☁️ Point Cloud (Mesh/PointCloud, 存储未剔除体素与元数据，默认隐藏)
    ```
  - [ ] 重构 `get_or_create_world_mesh_object` 与 `update_world_mesh`，确保 Mesh 与 PointCloud 挂载为同级子物体。
- [ ] **多会话上下文感知与属性隔离 (`properties.py`, `ui/panel_sync.py`)**
  - [ ] 编写 `find_root_container(obj)` 向上寻址解析器，无论选中容器、网格还是点云，均精准定位根容器。
  - [ ] 将会话属性绑定至每个 Container 物体本身（独立的 URL、选区坐标、顶点统计与连接状态），实现多会话完全并行隔离。
- [ ] **容器与子物体重命名级联同步 (`watcher.py`)**
  - [ ] 恢复 `bpy.app.handlers.depsgraph_update_post` 监听机制。
  - [ ] 当用户在大纲视图重命名 Empty 容器时，自动级联同步更新子网格与子点云名称（如 `MyWorld_Mesh`, `MyWorld_PointCloud`）。

---

## 阶段二：网格重构脏缓存校验与顶层右键菜单解耦（P1 - 功能解耦 🚧 规划中）
- [ ] **网格重构前缓存指纹一致性检查 (`bridge/sync.py`, `op_sync_rebuild.py`)**
  - [ ] 在触发网格重构前，检查磁盘 `assets_cache/cache_manifest.json` 或文件时间戳。
  - [ ] 若检测到用户在偏好设置中重新预编译/重新配置材质包：
    1. 动态重新加载最新 Atlas、ModelDatabase 与 BiomeResolver；
    2. 调用 Rust 端 `VoxelWorld::clear_cache()`，强制清除脏区块网格缓存（`section_mesh_cache`）；
    3. 重新执行全量网格化，并同步更新 Blender 材质节点树中的图集图像节点，彻底杜绝 UV 偏移与模型错乱。
- [ ] **顶层通用网格重构算子与右键菜单化 (`operators/op_mesh.py`)**
  - [ ] 将网格重构从“实时同步”面板中解耦，提炼为通用算子 `mozi.rebuild_mesh`。
  - [ ] 智能判定所选物体的体素源（实时同步容器 / 存档导入容器 / 点云物体），统一派发重构逻辑。
  - [ ] 注册至 3D 视图右键菜单（`VIEW3D_MT_object_context_menu`），实现右键一键重构。

---

## 阶段三：Minecraft 存档导入容器化、无感刷新与隐私 UUID 体系（P2 - 杀手级体验 🚧 规划中）
- [ ] **存档导入非破坏性容器化 (`operators/save/op_import_save.py`, `bridge/save.py`)**
  - [ ] 存档导入时自动创建独立 Empty 根容器（如 `Save_WorldName_Dimension_01`），子网格与子点云收拢于容器内。
  - [ ] 连续导入新选区时绝不覆盖历史已导入的存档物体，自动递增序号新建容器。
- [ ] **本地隐私注册表管理器 (`utils/system/save_registry.py`)**
  - [ ] 实现基于用户本地数据目录的 `SaveRegistryManager`，在 `DATAFILES/mozi_toolkit/save_registry.json` 中记录：
    ```json
    {
      "uuid_hash": {
        "world_dir": "/path/to/local/saves/WorldName",
        "dimension": "overworld",
        "last_refreshed": 1728100000
      }
    }
    ```
  - [ ] `.blend` 内部仅存储 `mozi_save_uuid` 以及不涉密的 AABB 选区与维度，彻底杜绝个人本地绝对路径随工程文件泄露。
- [ ] **存档专属面板与“一键刷新模型”算子 (`ui/panel_save.py`, `op_refresh_save.py`)**
  - [ ] 物体属性面板中为存档容器展示专属信息卡片（选区坐标、体积、最后更新时间）。
  - [ ] 提供 **“🔄 刷新模型 (Refresh Model)”** 按钮：按原选区重新解包 MCA/NBT 并原地无感替换网格。
  - [ ] 异地工程加载安全回退：当其他用户打开工程且本地无此 UUID 时，弹出友好提示并提供“重新关联本地存档路径”入口。

---

## 阶段四：右键菜单管理器自适应与全域 UI/UX 深度重构（P2 - 交互精修 🚧 规划中）
- [ ] **右键菜单智能差集自适应合并 (`utils/config/manager.py`, `utils/system/menu_registry.py`)**
  - [ ] 引入 `menu_schema_version` 版本迁移机制。
  - [ ] 插件启动加载配置时，比对内建 `CANONICAL_DEFAULT_PRESETS` 与用户已保存的 `views`：
    - 自动将新引入的内建推荐算子并入可用列表或菜单，保留用户已有的自定义排序与开关；
    - 告别每次新增选项都要手动点击“重置右键菜单”的繁琐体验。
- [ ] **全域 UI 面板风格现代化与整合**
  - [ ] 3D 视图 N 侧边栏及属性面板分区梳理：
    - 📡 **实时网络同步 (Live Sync)**：会话管理、多容器状态、流量与增量指标；
    - 📦 **世界存档导入 (World Saves)**：选区预览框、存档导入与刷新记忆；
    - 🧊 **体素与网格工具 (Voxel Tools)**：点云展示、通用网格重构、面剔除与像素切分。
  - [ ] 统一步骤进度条汇报（Blender 状态栏 / 模态任务窗）与图标视觉语言。
