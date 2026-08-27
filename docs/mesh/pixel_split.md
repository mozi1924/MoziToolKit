# 模块四：自适应像素网格切分系统 (Adaptive Pixel Split)

- **对应 Operator**：`mozi.adaptive_pixel_split` ([`operators/mesh/op_adaptive_pixel_split.py`](file:///Users/jaxlocke/Desktop/MoziToolKit/operators/mesh/op_adaptive_pixel_split.py))
- **核心实现模块**：`utils/pixel_split/` ([`core.py`](file:///Users/jaxlocke/Desktop/MoziToolKit/utils/pixel_split/core.py), [`uv_analyzer.py`](file:///Users/jaxlocke/Desktop/MoziToolKit/utils/pixel_split/uv_analyzer.py), [`subdivider.py`](file:///Users/jaxlocke/Desktop/MoziToolKit/utils/pixel_split/subdivider.py), [`types.py`](file:///Users/jaxlocke/Desktop/MoziToolKit/utils/pixel_split/types.py))、`utils/mesh/subdivide.py`

```mermaid
graph TD
    SelectFace[选中的四边形多边形 BMFace] --> CheckDeform{物体是否具有 Vertex Groups?}
    CheckDeform -- 是 --> VerifyLayer[bm.verts.layers.deform.verify 激活权重层]
    CheckDeform -- 否 --> AnalyzeMat[uv_analyzer: 解析贴图与材质模式]
    VerifyLayer --> AnalyzeMat
    
    AnalyzeMat --> DetectMode{材质模式判定}
    DetectMode -- UNIFIED ATLAS --> DecodeAtlas[从 MC_Atlas_UV_Decoder 解析 tile_size 与瓦片跨度]
    DetectMode -- STANDALONE ANIMATED --> DetectStrip[纵向长条图单帧正方形 16x16 截断]
    DetectMode -- GENERIC STATIC --> RawRes[图像真实宽高 W_tex, H_tex]
    
    DecodeAtlas --> CalcGrid[计算目标自适应细分数 Grid_X / Grid_Y]
    DetectStrip --> CalcGrid
    RawRes --> CalcGrid
    
    CalcGrid --> QuadSubdiv[subdivide_quad_face 核心四边形网格切分]
    QuadSubdiv --> BilinearWeights[双线性插值蒙皮权重 W(s,t) & 顶点颜色]
    QuadSubdiv --> InterpolateUV[双线性插值 UV 坐标 & 继承边 Crease/Seam]
    QuadSubdiv --> WeldClean[cleanup_mesh_topology: 边界微距焊接 1e-4 & 重算法线]
```

---

## 1. 1面 = 1像素几何分辨率自适应计算

### 1.1 网格细分数学模型
传统 Blender 细分算子（Subdivide）只能按统一几何倍数切分，无法感知贴图像素。`Adaptive Pixel Split` 自动提取面在 UV 空间中占用的跨度（$UV_{width}, UV_{height}$）以及贴图的有效分辨率（$W_{tex}, H_{tex}$），计算目标横向与纵向切分数：
$$Grid_X = \min\left(MaxSubdiv,\, \max\left(1,\, \operatorname{round}\left(UV_{width} \times \frac{W_{tex}}{PixelsPerFace}\right)\right)\right)$$
$$Grid_Y = \min\left(MaxSubdiv,\, \max\left(1,\, \operatorname{round}\left(UV_{height} \times \frac{H_{tex}}{PixelsPerFace}\right)\right)\right)$$
- **`PixelsPerFace`**（默认 `1.0`）：控制一个 3D 网格面片对应几个贴图像素。若设为 `1.0`，切分后达到绝对的“**1个多边形面 = 1个贴图像素**”；若设为 `2.0` 则为 $2 \times 2$ 像素对应一个面。
- **`MaxSubdivisions`**（默认 `64`）：防止极端异常 UV 导致面数爆炸的安全钳位上限。

---

## 2. 纵向长条动画与图集有效瓦片边界推断 (`uv_analyzer.py`)

### 2.1 纵向长条动画单帧截断算法 (Critical Anti-Explosion Defense)
- **痛点场景**：Minecraft 流水贴图、火把或熔炉动态贴图通常保存为单张纵向垂直排列的长条纹理（例如 $16 \times 512$ 像素，包含 32 帧）。若粗暴使用贴图全高进行切分，单个方块面将被切分为 $16 \times 512 = 8192$ 个面，导致场景瞬间假死崩溃。
- **自适应识别逻辑**：
  1. 检查材质节点中是否存在 `MC_Animated_UV_Mapping` 节点组或 `.png.mcmeta` 动画元数据；
  2. 若为通用材质，检测长宽比 $\frac{H_{tex}}{W_{tex}} > 1$ 且 $H_{tex} \pmod{W_{tex}} == 0$；
  3. 自动将有效单帧尺寸收敛为正方形：
     $$H_{effective} = W_{tex}$$
     确保动画材质在切分时仅按单帧正方形基底（$16 \times 16$）细分，彻底根除面数爆炸。

### 2.2 Unified Atlas 图集跨度换算
对于图集材质，分析器读取 `MC_Atlas_UV_Decoder` 中的 `Tile Size`（如 16）或图集瓦片总行列数，依据面所跨越的图集局部 UV 区域，精准折算对应的有效像素宽度。

---

## 3. 骨骼权重与网格属性双线性插值保真 (`subdivide.py`)

### 3.1 顶点蒙皮权重插值 ($W(s,t)$)
对于 Minecraft 角色（如玩家皮肤、生物模型），切分前往往已完成骨骼绑定（Rigging）与权重绘制：
- 对于四边形面四个基底角点 $V_{00}, V_{10}, V_{11}, V_{01}$，在切分产生任意内插新顶点时，计算其在面局域归一化坐标 $(s, t) \in [0, 1]^2$；
- 提取角点上绑定的全部骨骼 Deform Group 权重字典，对每个骨骼权重值执行双线性插值：
  $$W_{bone}(s, t) = (1-s)(1-t)W_{00} + s(1-t)W_{10} + stW_{11} + (1-s)tW_{01}$$
- **前置验证契约**：在操作前严格调用 `bm.verts.layers.deform.verify()`。切分完成后骨骼蒙皮动画 100% 丝滑连续，绝无权重断层。

### 3.2 顶点颜色、UV 循环与外轮廓边界属性继承
- **Color Attributes**：向新面传递 Loop 顶点色彩（包括 Biome 染色属性）。
- **UV Loops**：内插新顶点在 UV 坐标系中按几何比例精确赋予子 UV 矩形。
- **边界保护**：原四边形外边界边的 `seam`（缝合边）、`sharp`（锐边）、`crease`（折痕权重）与 `bevel_weight` 自动迁移至新细分网格的外周对应边界边，内部新增切分边保持平滑。

---

## 4. 拓扑清理与流形缝合 (`cleanup_mesh_topology`)

- **微距顶点缝合 (Weld Vertices)**：切分完成后，自动对新生成的顶点集合调用 `bmesh.ops.weld_verts`，阈值 $dist = 1.0 \times 10^{-4}$，将相邻面切分后重合的边界顶点完美融合。
- **孤立边与退化面清理**：自动移除因细分产生的零面积退化面片（Degenerate Faces）。
- **法线统一重构**：统一调用 `bm.normal_update()` 重新计算顶点与面法线。

---

## 5. 自适应像素网格切分防回归不变量契约

> [!IMPORTANT]
> 1. **动画贴图有效尺寸推断不可旁路**：任何情况下切分算子计算垂直细分数时，必须优先截断为单帧正方形有效高度，严禁直接使用物理纵向长条图的高度。
> 2. **Vertex Group Deform 层的存在性保障**：若目标物体包含骨骼权重组，必须在 BMesh 初始化时调用 `bm.verts.layers.deform.verify()`，否则新生成的细分顶点将因缺失权重层被 Blender 默认剥离蒙皮。
> 3. **四边形顶点缠绕逆时针顺序保持**：在构建细分子面片时，顶点索引必须严格保持与父级面一致的逆时针法线朝向，禁止面法线反转。
