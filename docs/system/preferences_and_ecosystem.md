# 模块八：偏好设置、右键上下文菜单、扩展生态与工程规范

## 1. 右键上下文菜单动态注册与自由重排体系
- **实现机制**：`utils/system/menus.py`、`ui/preferences.py`、`ui/menu_*.py`
- **设计方向**：
  - 使用 `@register_menu_item(views=["mesh", "object", "uv"])` 装饰器对算子进行元数据注册。
  - **全自由偏好设置面板**：用户可在插件偏好设置中自由启用/禁用特定菜单项、通过上移/下移调整菜单项在 3D View（Object Mode, Edit Mode）和 UV Editor 右键上下文菜单中的显示顺序，并可自定义菜单条目的 Label 名称。

## 2. 偏好配置 JSON 序列化与跨环境导入导出
- **配置持久化**：
  所有菜单顺序、启用状态、材质替换全局偏好（材质模式、生物群系预设、材质包栈路径）均被序列化保存在 Blender 配置目录下的 JSON 文件中。
- **防丢失写入契约**：
  - 配置的读-改-写操作必须在进程内串行化，避免相邻 UI 回调互相覆盖未修改字段；例如保存材质模式时必须保留完整的 `resource_packs` 列表。
  - 必须先写入同目录临时文件、`flush + fsync` 后以原子替换发布主 JSON；同时维护一份最近一次完整配置的 `.bak` 备份。
  - 主文件损坏、截断或无法解析时，必须优先读取有效 `.bak`，并报告恢复行为；不得把解析失败静默解释为空配置后覆盖用户的材质包栈。
  - 空 `resource_packs` 只能由用户显式保存或导入产生，不能是默认值回写、异常处理或迁移失败的副作用。
  - 导入配置必须先完整验证 JSON 结构，再一次性替换有效字段；无效导入不得改变当前配置。
- **一键导入导出**：
  提供 `mozi.export_config` 和 `mozi.import_config` 算子，支持一键导出为 `.json` 配置文件或从 JSON 导入，极大方便团队资产规范共享。

## 3. Blender 4.2+ 扩展规范与 Python Wheels 隔离管理
- **生态合规**：
  全面适配 Blender 4.2+ / 5.x 的 **Extensions Platform** 体系。
- **Python Wheels 隔离机制**：
  - 图集烘焙依赖轻量图像库 `Pillow`。
  - 在 `wheels/` 目录下准备了覆盖 Windows x64/arm64、macOS Apple Silicon、Linux x64 的预编译 `.whl` 包，并在 `blender_manifest.toml` 中严格声明。
  - 插件加载时优先探测自带 Wheel 隔离环境，杜绝污染 Blender 内置 Python 环境或发生依赖冲突。

## 4. 完整多语言国际化 (i18n) 字典体系
- **`i18n/dictionary.py`**：
  采用统一的字典映射表，涵盖所有 Operator 标签、描述 Tooltips、偏好设置选项、错误警告与进度提示。
- **无缝切换**：深度支持简体中文（`zh_CN` / `zh_HANS`）与英文（`en_US`），随 Blender 语言设置自动实时切换。

## 5. 自动化构建 (Build) 与 CI 测试套件
- **构建脚本 (`build.py`)**：
  - 支持单包一键构建 (`python3 build.py -o dist`)。
  - 支持分平台轻量化独立构建 (`python3 build.py -o dist --split-platforms`)，自动为特定 OS 打包对应平台的 Wheel 文件。
- **测试套件 (`tests/run_tests.py`)**：
  - 在终端中通过 Blender 无头模式执行自动化单元测试：
    ```bash
    blender -b --python tests/run_tests.py
    ```
  - 覆盖网格细分算法、UV 变换精度、材质解包与生物群系映射逻辑。
