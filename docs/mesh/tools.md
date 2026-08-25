# 模块六：网格与 UV 实用工具集

## 1. 清除自定义分割法线 (Clear Custom Normals)
- **对应 Operator**：`mozi.clear_custom_normals` (`operators/mesh/op_clear_custom_normals.py`)
- **设计背景与核心价值**：
  - 从 jmc2obj、Mineways、Blockbench 等外部软件导入的 OBJ/FBX 模型，往往带有固化的 `custom_normal` 数据层或损坏的 Split Normals。这会导致在 Blender 中即便开启 Smooth Shading，模型表面依然发黑、产生撕裂硬阴影或法线计算异常。
  - **处理逻辑**：一键清除当前网格所有自定义分割法线数据（调用 `bpy.ops.mesh.customdata_custom_splitnormals_clear()`），重构标准面法线与顶点平滑法线。

## 2. 锐边与硬边选择 (Select Hard & Sharp Edges)
- **对应 Operator**：`mozi.select_edges` (`operators/mesh/op_select_edges.py`)
- **设计方向**：
  - 基于相邻面的二面角（Dihedral Angle）阈值（如 $> 30^\circ$）或网格已标记的 `sharp` 属性，快速在 Edit Mode 中批量选中所有硬朗边界边。
  - 便于后续一键标记缝合边（Mark Seam）或赋予倒角权重（Bevel Weight）。

## 3. UV 原地独立缩放 (Scale UV Individual - 边缘抗渗色)
- **对应 Operator**：`mozi.scale_uv` (`operators/uv/op_scale_uv.py`)
- **核心数学与设计意图**：
  - 在低分辨率像素贴图（如 16x16）渲染时，由于 GPU 纹理采样器的双线性滤波（Bilinear Filtering）或 Mipmap 衰减，面边缘的 UV 极易采样到贴图边界外的一个半像素，产生黑色接缝线或漏色。
  - **原地独立缩放算法**：
    对于网格中的每个面 $F_i$，独立计算其自身的 UV 几何中心：
    $$C_{uv} = \frac{1}{N} \sum_{k=1}^N UV_k$$
    对该面的每个顶点 UV 进行向心微距缩放：
    $$UV'_k = C_{uv} + (UV_k - C_{uv}) \times ScaleFactor$$
    （默认 $ScaleFactor = 0.8$ 或微距 $0.999$）。每个面在自己的中心独立收缩，完全不影响相邻面的几何拓扑，彻底解决黑边渗色。

## 4. 修复流体 UV (Repair Fluid UV)
- **对应 Operator**：`mozi.repair_fluid_uv` (`operators/uv/op_repair_fluid_uv.py`)
- **设计方向**：
  - Minecraft 中流动水体和岩浆具有斜面几何体（如 8 级水流斜坡）。地图导出工具生成的斜面 UV 经常出现上下颠倒、90 度旋转错位或横向拉伸。
  - **算法原理**：
    分析面的法线倾角与局部坐标系斜率，自动识别流体流动的主方向向量，重新校正 UV 坐标轴旋转，使其纹理流动方向与重力/下坡方向完全对齐。

## 5. 基于贴图 Alpha 通道智能选面 (Select Transparent Faces)
- **对应 Operator**：`mozi.select_transparent_faces` (`operators/uv/op_select_transparent_faces.py`)
- **设计方向**：
  - 许多 Minecraft 树叶方块、草丛多边形或镂空模型在几何上是完整面片，但贴图大部分区域为完全透明（Alpha = 0）。
  - **采样算法**：
    提供三种采样模式：
    - `CENTER`：采样面 UV 中心点单个像素的 Alpha。
    - `CORNERS`：采样面 UV 四个角顶点的 Alpha 值。
    - `AVERAGE`：在面 UV 包围盒范围内进行多点网格采样取平均 Alpha。
  - 根据透明度阈值（Alpha Threshold）批量选出全透或半透的面，供艺术家一键删除以优化渲染多边形。

## 6. 纹理插值模式一键切换 (Texture Interpolation: Closest / Linear)
- **对应 Operator**：`mozi.texture_interpolation` (`operators/object/op_texture_interpolation.py`)
- **设计方向**：
  - 批量递归遍历所有选中物体材质节点树中的 `ShaderNodeTexImage` 图像纹理节点。
  - 一键将其 `interpolation` 属性统一设置为 `Closest`（呈现原汁原味的清爽锐利像素风）或 `Linear`（用于平滑纹理）。

## 7. 网格/UV 工具防回归不变量契约
> [!IMPORTANT]
> 1. **Scale UV 必须 Per-Face 独立计算中心**：绝不能将所有选中的面统一按全局 UV 中心缩放，否则会导致多面之间的相对排布被打乱。
> 2. **Clear Custom Normals 的无损性**：清除自定义法线仅清理 Split Normals 属性，绝对不能破坏网格原有的顶点坐标与 UV 贴图层。
