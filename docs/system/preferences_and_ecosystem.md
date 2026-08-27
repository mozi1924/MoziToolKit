# 模块八：偏好设置、右键上下文菜单、扩展生态与工程规范

MoziToolKit 构建于现代 Blender 4.2+ 扩展架构之上，提供了高度可定制的右键上下文菜单、线程安全且具备崩溃自愈能力的持久化配置引擎、跨平台 Wheels 隔离加载体系以及完备的国际化与自动化构建流水线。

- **核心实现模块**：`utils/config/` ([`manager.py`](file:///Users/jaxlocke/Desktop/MoziToolKit/utils/config/manager.py), `backends/`, `models.py`), `ui/` ([`preferences.py`](file:///Users/jaxlocke/Desktop/MoziToolKit/ui/preferences.py)), `utils/system/`, `i18n/` ([`dictionary.py`](file:///Users/jaxlocke/Desktop/MoziToolKit/i18n/dictionary.py)), `build.py`

```mermaid
graph TD
    subgraph ConfigSystem [配置与持久化系统 Config Engine]
        CM[ConfigManager 单例 Controller]
        Backend[JsonConfigBackend / MemoryBackend]
        AtomicIO[原子写入 .tmp + fsync -> 替换主 JSON]
        BakFile[最近有效备份 .bak 自动自愈]
        CM --> Backend
        Backend --> AtomicIO
        AtomicIO -. 异常崩溃 .-> BakFile
    end

    subgraph MenuRegistry [右键上下文动态菜单体系]
        Deco[@register_menu_item 装饰器]
        OrderStore[Preferences 存储的自定义顺序与启用标记]
        DynamicDraw[3D View / UV Editor 右键菜单动态绘制]
        Deco --> DynamicDraw
        OrderStore --> DynamicDraw
    end

    subgraph ExtensionEcosystem [扩展打包与依赖隔离]
        Manifest[blender_manifest.toml]
        WheelIso[wheels/ 跨平台 Pillow 隔离导入]
        BuildPy[build.py: --split-platforms]
    end
```

---

## 1. 右键上下文菜单动态注册与自由重排体系

### 1.1 菜单装饰器元数据注册 (`@register_menu_item`)
- 插件内的所有 Operator 通过 [`@register_menu_item(views=["mesh", "object", "uv"])`](file:///Users/jaxlocke/Desktop/MoziToolKit/utils/system/menu_registry.py) 声明其支持的目标视图与上下文。
- 支持视图：
  - **`object`**：3D Viewport 物体模式（Object Mode）右键菜单。
  - **`mesh`**：3D Viewport 编辑模式（Edit Mesh Mode）右键菜单。
  - **`uv`**：UV Editor 编辑器右键菜单。

### 1.2 全自由偏好设置面板 (`ui/preferences.py`)
- **自由重排与自定义 Label**：用户可在偏好设置中对每个视图下的菜单项自由进行上移（Move Up）、下移（Move Down）、启用/禁用（Toggle Enable），并能自定义菜单显示的别名（Label）。
- **未添加项目智能归并 (`sort_unadded_items`)**：当插件版本升级新增 Operator 时，偏好设置会自动发现新条目并智能吸附到列表底部，不会打乱用户已有的个性化排序。

---

## 2. 线程安全配置管理与防丢失持久化契约 (`ConfigManager`)

### 2.1 架构与后端解耦 (`utils/config/`)
- **`ConfigManager`** 单例门面（Facade）：维护全局 `_lock = threading.RLock()`，保证进程内所有 UI 属性变动、异步线程与后台任务对配置的读写绝对串行化。
- **后端插拔**：
  - `JsonConfigBackend`：生产默认，持久化至 Blender 用户配置目录下的 `mozitoolkit_config.json`。
  - `MemoryConfigBackend`：用于单元测试与无头沙盒。
  - `BlenderPreferencesConfigBackend`：与 Blender 内置 `AddonPreferences` 同步。

### 2.2 防丢失写入与原子发布契约 (Atomic Publication & Fallback)
1. **原子写入与崩溃防护**：
   所有 JSON 写入必须先写入同目录下的临时文件（`mozitoolkit_config.json.tmp`），执行 `flush() + os.fsync()` 确保物理落盘后，再执行原子重命名（`os.replace`）覆盖主配置；
2. **自动备份自愈机制 (`.bak`)**：
   系统持续同步维护一份最近一次成功加载/保存的 `mozitoolkit_config.json.bak`。若主文件在操作系统异常断电、进程强杀时损坏或截断，系统在启动时自动静默回退至 `.bak` 恢复，并在控制台记录警告，**严禁静默覆盖为空配置**；
3. **结构校验与导入防护**：
   通过 `mozi.import_config` 导入外部 JSON 时，必须先进行全量 Schema 校验（`ConfigData.from_dict`），只有在整个结构解析合法后方可应用，无效的外部 JSON 绝对不会污染已有配置。

---

## 3. Blender 4.2+ Extensions 生态与 Python Wheels 隔离管理

### 3.1 扩展清单合规 (`blender_manifest.toml`)
- 全面适配 Blender 4.2+ / 5.x 现代 Extension 规范，严谨声明 `schema_version = "1.0.0"`, `permissions = ["files", "network"]`。

### 3.2 跨平台预编译 Wheels 隔离沙盒 (`wheels/`)
- **依赖库**：高性能图集烘焙引擎依赖轻量图像处理库 `Pillow`。
- **内置预编译包**：
  - Windows x86_64 / arm64 (`Pillow-...-win_amd64.whl`, `win_arm64.whl`)
  - macOS Apple Silicon & Intel (`Pillow-...-macosx_11_0_arm64.whl`, `macosx_10_10_x86_64.whl`)
  - Linux x86_64 (`Pillow-...-manylinux_2_28_x86_64.whl`)
- **隔离加载与优雅降级**：
  在 [`operators/misc/op_dependencies.py`](file:///Users/jaxlocke/Desktop/MoziToolKit/operators/misc/op_dependencies.py) 与 `utils/system/` 中，插件启动时优先将自带 `wheels/` 目录挂载到隔离 `sys.path`，绝不污染全局 Blender Python 环境；若宿主环境缺失 Pillow，基础网格清洗与 UV 工具依然可 100% 独立正常运行。

---

## 4. 统一多语言国际化 (i18n) 字典体系

- **`i18n/dictionary.py`**：
  采用标准的二元元组键 `(context, msgid)` 映射结构，全量覆盖所有 Operator 标签、描述 Tooltips、偏好设置菜单项、诊断日志与 Modal 进度条文案。
- **实时切换**：
  深度支持简体中文（`zh_HANS` / `zh_CN`）与英文（`en_US`），随 Blender 偏好设置的语言切换实时刷新。

---

## 5. 自动化构建与 CI 测试套件

### 5.1 智能构建工具 (`build.py`)
- **全平台一键打包**：
  ```bash
  python3 build.py -o dist
  ```
  自动扫描并优先调用本地 Blender 的 `blender --command extension build`；若环境无 Blender 二进制，自动回退到符合 Manifest 规范的纯 Python 纯净打包器。
- **分平台独立轻量化构建 (`--split-platforms`)**：
  ```bash
  python3 build.py -o dist --split-platforms
  ```
  自动针对不同操作系统分别剔除无关平台的 `.whl` 文件，生成体积极为小巧的平台专用安装包。

### 5.2 自动化测试套件 (`tests/run_tests.py`)
- 在终端中通过 Blender 无头模式执行全量单元测试：
  ```bash
  blender -b --python tests/run_tests.py
  ```
- 测试覆盖：
  - `test_adaptive_pixel_split.py`：自适应网格细分与权重迁移测试。
  - `test_atlas_addressing.py`：图集坐标寻址与安全 Clamp 测试。
  - `test_extrude_repair.py`：侧面 UV 塌陷修复与模式判定测试。
  - `test_mc_baker.py`：BlockState 变体、Multipart 条件与模型继承树展开测试。
  - `test_config_manager.py`：配置原子写入、备份恢复与 JSON Schema 校验测试。

---

## 6. 系统与偏好设置防回归不变量契约

> [!IMPORTANT]
> 1. **配置写入原子性保障**：严禁直接打开主配置文件进行 `open('w')`，必须经由 `.tmp` 写入并在 `fsync` 后原子重命名。
> 2. **空材质包栈保护**：清空材质包栈必须只能通过用户在 UI 上的显式删除操作发生，配置加载异常或迁移失败时绝对禁止静默写入空列表。
> 3. **依赖加载沙盒化**：从 `wheels/` 解压或加载第三方库时，必须限制在插件自身的命名空间内，防止与用户安装的其他 Blender 插件产生包版本冲突。

---

## 7. 偏好设置 UI 架构与模块解耦 (UI Architecture)

偏好设置由以下模块协同组成：

- **`ui/preferences_packs.py`**：资源包层级管理（Resource Pack, Mod JAR, Vanilla JAR）、`MOZI_PG_resource_pack_entry` 属性组、`MOZI_UL_resource_packs_list` 绘制列表、分层排序（`reorder_resource_packs_by_tier`）及添加/移除/移动算子。
- **`ui/preferences_menus.py`**：右键菜单项配置属性组（`MOZI_PG_context_menu_item`, `MOZI_PG_available_menu_item`）、已添加/未添加列表绘制器及菜单导入/导出/重置算子。
- **`ui/preferences.py`**：顶层 `MOZI_AddonPreferences`，调度三大主选项卡（资源包栈、右键菜单、系统环境与存储后端）、预编译缓存算子（`MOZI_OT_precompile_cache`）以及跨模块符号重导出。
