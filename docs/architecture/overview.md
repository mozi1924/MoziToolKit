# 架构总览与防回归设计哲学

MoziToolKit 是一套专为 **Minecraft 资产转换、Voxel 风格高保真建模、贴图烘焙与自动化流水线** 设计的 Blender 生产力工具集。

```mermaid
graph TD
    subgraph UI_Layer [交互层 UI & Menus]
        Prefs[Addon Preferences]
        Menus[Dynamic Context Menus - Object/Edit/UV]
        ModalProgress[Modal Progress & Timer]
    end

    subgraph Pipeline_Layer [核心调度层 Modular Pipeline]
        PipeCore[Pipeline Runner]
        Ctx[Pipeline Context]
        Steps[Atomic Steps]
        Presets[Preset Workflows]
    end

    subgraph Engine_Layer [功能引擎层 Engine Subsystems]
        MatEngine[Material & Atlas Engine]
        BakerEngine[MC Baker & BlockState]
        GeoEngine[Geometry Nodes World Tree]
        SplitEngine[Adaptive Pixel Split]
        ExtrudeEngine[Auto Extrude Repair]
        MeshUtils[UV & Mesh Operators]
    end

    subgraph System_Layer [底层基础支撑 System & Deps]
        WheelManager[Python Wheels / Pillow Manager]
        I18n[i18n Translation Dictionary]
        ConfigIO[JSON Config Importer/Exporter]
        AutoLoad[Blender 4.2+ Auto Loader]
    end

    UI_Layer --> Pipeline_Layer
    Pipeline_Layer --> Engine_Layer
    Engine_Layer --> System_Layer
```

## 核心防回归原则 (Non-negotiable Invariants)

1. **数学确定性优于盲目插值**：Minecraft 的像素艺术美学建立在清晰的像素网格、最近邻插值（Nearest Neighbor）和严格的 UV 边界上。任何几何细分或 UV 变换都必须具有像素级别的数学确定性。
2. **图集安全边界（Atlas Boundary Safety）**：Atlas 图集必须时刻防范跨瓦片溢色（Tile Bleeding）与浮点漂移。着色器和几何脚本中对 UV 的变换必须严格遵循安全边距（Padding / Clamp）。
3. **外部模型容错性（External Model Tolerance）**：来自各类导出工具（jmc2obj、Mineways、Ice-Cube、Blockbench 等）的模型往往携带损坏的 Split Normals、畸变的 UV、冗余材质名称。工具集必须在清洗脏数据的同时，保留原模型的拓扑与 UV 意图。
4. **解耦与流水线化（Decoupled Pipeline）**：所有原子操作必须能作为独立的 Blender Operator 运行，也能在无 UI 的 `Pipeline` 环境中被批量编排调用。
