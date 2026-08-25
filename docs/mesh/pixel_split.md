# 模块四：自适应像素网格切分系统 (Adaptive Pixel Split)

- **对应 Operator**：`mozi.adaptive_pixel_split` (`operators/mesh/op_adaptive_pixel_split.py`)
- **核心实现模块**：`utils/pixel_split/` (`core.py`, `uv_analyzer.py`, `subdivider.py`, `types.py`)

## 1. 1面 = 1像素的几何分辨率自适应计算
- **设计方向**：
  - 传统 Blender 细分（Subdivide）只能按几何倍数（2/4/8 等）切分，无法感知材质贴图的真实像素网格。
  - `Adaptive Pixel Split` 自动分析目标面的 UV 边界大小与对应材质的贴图宽高（$W_{tex}, H_{tex}$），计算出该面在 UV 空间中占用的真实像素网格数：
    $$Grid_X = \max\left(1,\, \text{round}\left(UV_{width} \times \frac{W_{tex}}{PixelsPerFace}\right)\right)$$
    $$Grid_Y = \max\left(1,\, \text{round}\left(UV_{height} \times \frac{H_{tex}}{PixelsPerFace}\right)\right)$$
  - 将该面精确细分为 $Grid_X \times Grid_Y$ 的规则四边形网格，实现 **1 个 3D 面 = 1 个贴图像素**（或指定比例）。

## 2. 动画贴图单帧正方形与 Atlas 瓦片边界推断
- **关键设计考量（避免过度切分的重大防坑点）**：
  - 如果材质是一张纵向长条图（如 16x512 的流水贴图），若直接取贴图全高（512），会导致一个面被错误切分为 16x512 个面（过度切分导致卡死）。
  - **自适应逻辑**：`uv_analyzer.py` 会自动检测纹理的长宽比与帧数元数据。对于纵向动画贴图，以单帧尺寸（通常为正方形 $16 \times 16$）作为有效高度进行细分计算。
  - 对于图集贴图（Atlas），自动根据 UV 局部跨度换算瓦片实际像素尺寸。

## 3. 骨骼权重 (Vertex Groups) 与网格属性双线性插值保真
- **设计方向**：
  - 角色模型（如 Minecraft 皮肤模型）在切分前已经完成了骨骼绑定（Rigging）和权重绘制。
  - `subdivider.py` 在四边形切分网格生成新顶点时，对每个新顶点在其父级面的参数坐标 $(s, t) \in [0, 1]^2$ 上执行 **双线性插值（Bilinear Interpolation）**：
    $$W(s, t) = (1-s)(1-t)W_{00} + s(1-t)W_{10} + stW_{11} + (1-s)tW_{01}$$
  - 完美保留所有 Vertex Groups 权重与自定义网格属性（Color Attributes / Face Maps），切分后骨骼蒙皮动画丝毫不受破坏。

## 4. 拓扑缝合 (Weld) 与法线平滑重构
- 切分完成后，自动对相邻共享边界执行微距顶点缝合（Weld / Merge by Distance, $dist = 10^{-4}$），清理退化边面，并重新计算面法线，确保拓扑流形完整。

## 5. 像素网格切分防回归不变量契约
> [!IMPORTANT]
> 1. **动画贴图有效尺寸推断**：切分算子计算网格密度时，必须优先获取单帧有效尺寸，绝不能直接使用纵向长条图的绝对像素高度。
> 2. **顶点权重层必须前置 verify**：如果物体拥有 Vertex Groups，在 BMesh 操作前必须调用 `bm.verts.layers.deform.verify()`，否则新生成的顶点将丢失所有蒙皮权重。
