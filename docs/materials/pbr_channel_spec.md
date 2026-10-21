# PBR 通道规范（MtkSurface / MtkPackedV1）

> 状态：v2.1 设计契约，2026-10-21。
> 本文是材质 PBR 通道的唯一事实源。Rust 解码/打包、`.mtkcache` 布局、Blender builder
> 与未来的 USD/Bedrock 导出都必须以此为准。
>
> 相关：[材质管线总览](material_pipeline.md)、[LabPBR 1.3 原始规范](../../../labpbr.md)。

---

## 1. 目标与边界

### 1.1 目标

1. **预编译期解码**：资源包里的 LabPBR `_n` / `_s`（以及未来的 Bedrock MER、通用
   metallic-roughness）在 Rust 预编译阶段被解码成一组 **canonical PBR 通道**。
2. **DCC 零解码**：Blender 材质只消费标准贴图与标准 Principled 输入，不再实例化
   `LabPBR 1.3 Decoder`，不再做 F0→IOR、DX→GL、smoothness→roughness 等运行时数学。
3. **多格式可扩展**：新增一种源格式 = 新增一个 decoder；新增一个目标 = 新增一个 packer。
   DCC 侧节点图不随源格式变化。
4. **可检查**：解码结果落成普通 PNG 通道，出问题可以直接看图，而不是在一个 60 节点
   的着色器里猜。

### 1.2 明确不做什么

- **不把“OpenPBR 贴图”当作缓存格式。** OpenPBR 是 surface shader 规范，不是贴图布局；
  它没有 AO 输入、没有 displacement 输入，UsdPreviewSurface 又没有 SSS/transmission。
  缓存存 canonical 通道，导出时再由 packer 生成目标格式所需贴图。
- **不在运行时保留逐面游戏语义。** `thin wall`、`transmission`、`sticker threshold`、
  `hardcoded emission` 不再从 `mtk_material_props` 读取，也不再在着色器里做比较/混合。
- **不保证 LabPBR 的 N/K 预设金属精确复现。** 当前实现本来就用 `metallic=1 + albedo`
  近似；本规范保持这一近似，并在 `aux` 预留金属类别通道供未来扩展。

### 1.3 版本与命名

- Canonical 数据模型：`MtkSurface`。
- 贴图打包布局：`MtkPackedV1`。
- 解码器版本：`decoder_version = 1`。
- 缓存格式版本：随 `ASSET_CACHE_FORMAT_VERSION` 递增；布局变化必须让旧缓存失效。

---

## 2. Canonical 通道（MtkSurface）

所有通道都是 **贴图空间、逐 texel** 的；没有“每面属性”这一层。

| 通道 | 分量 | 范围 | 色彩空间 | 语义 |
| :--- | :--- | :--- | :--- | :--- |
| `base_color` | RGB | 0–1 | sRGB | 反照率，不含 AO、不含光照 |
| `opacity` | 1 | 0–1 | Linear | 不透明度；1 = 不透明 |
| `normal` | RGB | 0–1 | Linear | 切线空间法线，**OpenGL（+Y up）**，已归一化 |
| `height` | 1 | 0–1 | Linear | 高度，1 = 最高；LabPBR 的 0 = 25% depth |
| `ao` | 1 | 0–1 | Linear | 1 = 无遮挡，0 = 全遮挡 |
| `roughness` | 1 | 0–1 | Linear | **perceptual** roughness；内部再平方为 GGX alpha |
| `metallic` | 1 | 0–1 | Linear | 0 = 电介质，1 = 金属；LabPBR 为二值 |
| `specular_ior` | 1 | 1–8 | Linear | 由 F0 反解；金属时无意义，固定 1.5 |
| `emission_mask` | 1 | 0–1 | Linear | 0 = 不发光；发光颜色复用 `base_color` |
| `porosity` | 1 | 0–1 | Linear | LabPBR 专有；当前 Blender 不消费，保留给未来 |
| `sss_weight` | 1 | 0–1 | Linear | 次表面散射权重 |
| `transmission_mask` | 1 | 0–1 | Linear | **v1 预留**；当前恒 0，未来用于玻璃/水 |
| `height_scale` | meta | 0–∞ | — | LabPBR = 0.25；用于 Bump/Displacement 的物理深度 |
| `height_midlevel` | meta | 0–1 | — | 高度图的“零位移”参考；LabPBR = 1.0 |

### 2.1 为什么 roughness 存 perceptual

LabPBR 文档写的是 `roughness = pow(1 - smoothness, 2.0)`，这是 **linear roughness /
GGX alpha** 的定义。Blender Principled、OpenPBR `specular_roughness`、glTF
`roughnessFactor` 都使用 **perceptual roughness**，内部再平方。

因此 canonical 统一存：

```text
roughness = 1 - perceptual_smoothness
```

如果某个目标明确要求 linear roughness，由该目标的 packer 执行 `roughness * roughness`。
**不要在解码器里平方，否则 Blender 会二次平方，所有材质偏光滑。**

### 2.2 为什么法线统一为 OpenGL

LabPBR 是 DirectX（Y−）。Blender 的 Normal Map 节点、OpenPBR `geometry_normal`、
UsdPreviewSurface `normal`、Bedrock `_normal.png` 都按 OpenGL（+Y up）解释。

解码时一次性转换：

```text
x = 2 * R_n / 255 - 1
y = 1 - 2 * G_n / 255          # DirectX Y- → OpenGL Y+
z = sqrt(max(0, 1 - x*x - y*y))
R_gl = (0.5 * x + 0.5) * 255
G_gl = (0.5 * y + 0.5) * 255
B_gl = (0.5 * z + 0.5) * 255
```

注意 `R_gl == R_n`、`G_gl == 255 - G_n`，Z 需要重建。若未来要导出 DirectX 目标
（Unreal 等），由 packer 翻回 `255 - G`。

### 2.3 高度约定

LabPBR `_n.A`：

- 0 → 纹理深度的 25%
- 255 → 0% 深度（表面最高点）

所以 `height = A_n / 255` 是单调正确的（255 = 最高）。物理深度由 `height_scale = 0.25`
描述；Blender 侧：

- Bump：`Distance = height_scale * user_scale`，`Height = height`，`Strength = 1.0`
- Displacement：`Midlevel = 1.0`，`Scale = height_scale * user_scale`，`Height = height`

这与旧解码器的 `(A - 1) * 0.25 * scale` 等价，只是把负偏移换成 `Midlevel`。

### 2.4 发射约定

LabPBR `_s.A`：

- 255 = **无数据**（RGB 图没有 alpha 时的默认值），不是 100%
- 254 = 100%
- 0 = 0%

解码：

```text
emission_mask = (A_s == 255) ? 0.0 : min(A_s, 254) / 254.0
```

发光颜色复用 `base_color`（Blender 中为 tint 后的 albedo，不含 AO）。发光强度由材质级
常量（当前 5.0）乘以 mask；不要把 5.0 烘进 8-bit mask，否则会截断。

---

## 3. Packed 布局（MtkPackedV1）

为了兼顾显存与标准语义，缓存使用 4 张 RGBA 贴图（overlay 另算）。所有贴图与 albedo
共享同一 atlas chunk 的 UV 布局。

| 文件 | R | G | B | A | 色彩空间 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `{stem}.png` | base_color R | base_color G | base_color B | opacity | sRGB |
| `{stem}_n.png` | normal X (GL) | normal Y (GL) | normal Z (GL) | height | Non-Color |
| `{stem}_orm.png` | ao | roughness | metallic | emission_mask | Non-Color |
| `{stem}_aux.png` | `(specular_ior - 1) / 7` | porosity | sss_weight | transmission_mask | Non-Color |
| `{stem}_overlay.png` | overlay R | overlay G | overlay B | overlay alpha | sRGB |

约定：

- 每张图都是 8-bit PNG；写入 `.mtkcache` 时使用 raw PNG chunk（与现有 albedo 一致）。
- `_n` 的 alpha 是 height；Blender 用 Image Texture 的 Alpha 输出接 Bump。
- `_orm` 的 alpha 是 emission mask；Blender 用 Separate Color 的 Alpha 输出。
- `_aux` 的 alpha 在 v1 恒 0；未来填 transmission mask 后，Blender 直接接
  Principled `Transmission Weight`，不需要额外节点。
- `specular_ior` 的 8-bit 编码范围是 [1, 8]。在 IOR 1.5 附近换算回 F0 的步长约 0.0035，
  与 LabPBR 源 F0 的 8-bit 步长 0.0039 相当；F0 > 0.605（IOR > 8）会被 clamp。
- 缺失的伴生图按需省略：
  - 无 normal：不写 `_n`，法线取 `(0.5, 0.5, 1.0)`，height = 0
  - 无 normal/specular：不写 `_orm` / `_aux`
  - 只有 normal：写 `_n` 和 `_orm`（AO 来自 normal.B；roughness 默认 0.707，metallic=0，
    emission=0），不写 `_aux`
  - 只有 specular：写 `_orm` / `_aux`，不写 `_n`；AO = 1，height = 0
- albedo 中 `alpha == 0` 的像素在预编译期把 RGB 填为白色（legacy clean albedo），避免 cutout 边缘双线性采样出现暗边。
- 全缺省像素（atlas 空隙或未覆盖 sprite）：
  - normal = (128, 128, 255)，height = 255
  - ao = 255，roughness = 255（即 1.0），metallic = 0，emission = 0
  - ior 编码 = `(1.5 - 1) / 7 ≈ 18/255`，porosity = 0，sss = 0，transmission = 0

### 3.1 `atlas_mapping.json`

每个 chunk 增加：

```json
{
  "has_normal": true,
  "has_specular": true,
  "has_orm": true,
  "has_aux": true,
  "pbr": {
    "layout": "mtk_packed_v1",
    "source_format": "labpbr13",
    "normal_convention": "opengl",
    "roughness_space": "perceptual",
    "height_scale": 0.25,
    "height_midlevel": 1.0,
    "ior_encoding": "range_1_8",
    "decoder_version": 1
  }
}
```

- `has_normal` / `has_specular` 表示 **源通道** 是否存在，继续用于 “这个 chunk 是否有 PBR”
  的判断与 layout hash。
- `has_orm` / `has_aux` 表示 **打包后的文件** 是否存在，用于 builder 选择贴图路径。
- 旧缓存缺少 `pbr` 字段时按 `decoder_version = 0`（legacy）处理；缓存格式版本 bump 后
  正常情况下不会读到旧缓存。

---

## 4. LabPBR 1.3 解码规则

输入：`normal: Option<&RgbaBuffer>`（`_n`）、`specular: Option<&RgbaBuffer>`（`_s`）。
输出：`normal_gl`、`orm`、`aux` 三张 `RgbaBuffer`，尺寸与输入 chunk 一致。

### 4.1 `_n` → `normal_gl` / `height` / `ao`

```text
ao      = B_n / 255
height  = A_n / 255
normal  = GL 重建（见 §2.2）
```

### 4.2 `_s` → roughness / metallic / specular_ior / sss / porosity / emission

```text
roughness = 1 - R_s / 255

F0 = min(G_s, 229) / 255
metallic = (G_s >= 230) ? 1 : 0
ior = metallic ? 1.5 : (1 + sqrt(F0)) / (1 - sqrt(F0))
ior = clamp(ior, 1.0, 8.0)

# B 通道分段
porosity = (B_s <= 64) ? clamp(B_s / 64.0, 0, 1) : 0
sss_weight = (B_s >= 65) ? clamp((B_s - 65) / 190.0, 0, 1) : 0

# A 通道
emission_mask = (A_s == 255) ? 0.0 : min(A_s, 254) / 254.0
```

注意：

- `G_s == 229` 仍是电介质，F0 = 229/255 ≈ 0.898，IOR 会 clamp 到 8。
- `G_s == 230..254` 全部按金属处理（当前实现不查 N/K 表）。
- `G_s == 255` 是自定义金属，`metallic=1`，`base_color` 直接作为 F0。
- `_s` 缺失时：roughness = 1 - 0.292893 = 0.707107，F0 = 0.04（IOR 1.5），
  metallic = 0，sss = 0，porosity = 0，emission = 0。这是旧解码器对
  `Specular (_s) Color` 默认值 `(0.292893, 0.04, 0, 1)` 的行为，必须保持。
- `_n` 缺失时：normal = (0.5, 0.5, 1.0)，height = 1.0，ao = 1.0。

### 4.3 编码到 packed 通道

```text
_n:   [normal.r, normal.g, normal.b, height]
_orm: [ao, roughness, metallic, emission_mask]
_aux: [(ior - 1) / 7, porosity, sss_weight, transmission_mask /* v1 = 0 */]
```

所有中间计算用 f32；写入 8-bit 时四舍五入到最近整数。不要在 sRGB 空间做这些运算；
`_n` / `_orm` / `_aux` 在 Blender 中必须标记为 `Non-Color`。

---

## 5. 目标映射

### 5.1 Blender（本阶段实现）

| Principled 输入 | 连接 |
| :--- | :--- |
| Base Color | tinted albedo × `_orm.R`（AO） |
| Metallic | `_orm.B` |
| Roughness | `_orm.G` |
| IOR | `_aux.R` → Multiply Add（×7 + 1） |
| Alpha | albedo alpha（v1；transmission 预留） |
| Normal | Normal Map(`_n`) → Normal；`_n.A` 高度保留但 v1 不接 Bump/Displacement（旧解码器默认 displacement scale = 0） |
| Emission Color | tinted albedo（不含 AO） |
| Emission Strength | `_orm.A` × 5.0 |
| Subsurface Weight | `_aux.B`（Disable 时 0） |
| Thin Wall | 不连接（默认 false） |
| Transmission Weight | 不连接（v1） |

非 PBR chunk（无 `_n` 且无 `_s`）：roughness 0.5、IOR 1.5、metallic 0、无 normal、
emission 0。不再有 `transmission → roughness 0` 的特殊分支。

### 5.2 OpenPBR Surface（未来导出）

| Canonical | OpenPBR 输入 |
| :--- | :--- |
| base_color | `base_color` |
| opacity | `geometry_opacity` |
| normal | `geometry_normal` |
| roughness | `specular_roughness` |
| metallic | `base_metalness` |
| specular_ior | `specular_ior` |
| emission_mask × base_color | `emission_color` + `emission_luminance` |
| sss_weight | `subsurface_weight` |
| transmission_mask | `transmission_weight` |
| ao | OpenPBR 无输入；packer 自行乘进 `base_color` 或交给 renderer AO |
| height | OpenPBR Surface 无输入；作为独立 MaterialX displacement |

### 5.3 UsdPreviewSurface（未来导出）

| Canonical | UsdPreviewSurface 输入 |
| :--- | :--- |
| base_color | `diffuseColor` |
| opacity | `opacity` |
| normal | `normal` |
| roughness | `roughness` |
| metallic | `metallic` |
| specular_ior | `ior` |
| emission_mask × base_color | `emissiveColor` |
| ao | `occlusion` |
| height | `displacement` |

UsdPreviewSurface 没有 SSS / transmission / thin wall；导出时降级或丢弃。

### 5.4 Bedrock（未来导出）

| Canonical | Bedrock |
| :--- | :--- |
| base_color | `color` |
| opacity | `color` alpha |
| normal | `_normal.png`（GL） |
| height | `_heightmap.png` |
| metallic | `_mer.png` R |
| emission_mask | `_mer.png` G |
| roughness | `_mer.png` B |
| ao | Bedrock 无 AO 通道；packer 烘进 color 或丢弃 |
| specular_ior / sss / transmission | Bedrock 无对应；丢弃或自定义扩展 |

MER 通道顺序以微软 `texture_set.json` 文档为准；实现前需用本地资产/官方文档复核。

### 5.5 glTF（未来导出）

| Canonical | glTF |
| :--- | :--- |
| base_color | `baseColorTexture` |
| metallic | `metallicRoughnessTexture.B` |
| roughness | `metallicRoughnessTexture.G` |
| normal | `normalTexture`（GL） |
| ao | `occlusionTexture.R` |
| emission_mask × base_color | `emissiveTexture` |
| specular_ior | `KHR_materials_ior`（标量，逐 texel 降级） |
| transmission_mask | `KHR_materials_transmission` |
| sss_weight | 无核心扩展；丢弃或自定义 |

---

## 6. 游戏语义移除（v1）

### 6.1 移除内容

- 材质不再读取 `mtk_material_props` / `mtk_emission`。
- 不再有 `thin wall`、`transmission`、`sticker threshold`、`hardcoded emission` 的
  运行时比较/混合。
- 不再有 `enable_game_semantics` / `transmission_mode` / `thin_wall_mode` 的材质分支。
- 玻璃/水在 v1 **只使用 albedo alpha**；albedo alpha = 1 的玻璃会不透明。
- 非 PBR 发光方块在 v1 **不发光**，直到内部 fallback PBR 层提供 emission mask。

### 6.2 预留路径

- `_aux.A` 定义为 `transmission_mask`。未来若要恢复玻璃/水：
  1. 在预编译期把 transmission（以及可选 sticker/threshold 逻辑）烘进 `_aux.A`；
  2. 把 albedo alpha 改为 `transmission > 0 ? 1 : original_alpha`（可烘进 albedo 的 alpha）；
  3. Blender 侧直接把 `_aux.A` 接到 `Transmission Weight`。
  仍然没有逐面属性、没有 compare/sticker 节点。
- 内部 fallback PBR 贴图作为资源栈的低优先级层插入，走现有 per-channel fallback；
  不写特殊代码，用户包可覆盖。
- `thin wall` 若以后需要，可作为 `_aux` 的 flag 位或单独通道；v1 不做。

### 6.3 分阶段清理

- **Phase 1**：Python builder 停止消费；`pipeline.py` 停止注入 `mtk_material_props`；
  `shading_config.py` 删除语义分支。Rust 侧保留旧 API，避免冻结期跨 crate 大改。
- **Phase 2**：删除 `mtk-core::ATTR_MATERIAL_PROPS`、`mtk-voxel` 的 `material_props`
  字段、`mtk-py` 的 `compute_flat_material_props_*`、`configs/material_properties.json`
  以及相关测试/UI 开关。`mtk_emission` 与 redstone 测试一起评估。

---

## 7. 缓存与失效

- `ASSET_CACHE_FORMAT_VERSION` bump；旧 `.mtkcache` 直接判为不可用并重建。
- `atlas_mapping.json` 必须包含 §3.1 的 `pbr` 元数据；缺失时按 legacy 处理。
- `uv_layers.py` 的 layout hash 必须纳入 `has_orm` / `has_aux`（以及 `pbr.layout`），
  否则 PBR 布局变化但 atlas UV 复用，导致材质贴图错位。
- `manifest` 的 fingerprint 需要包含 decoder 版本；解码规则变化必须让缓存失效。

---

## 8. 测试契约

### 8.1 Rust 单元测试

用 2×2 / 16×16 合成贴图覆盖：

- `G_s = 0, 229, 230, 254, 255`
- `B_s = 0, 64, 65, 255`
- `A_s = 0, 1, 254, 255`
- `R_s = 0, 128, 255`
- `_n` 的 `R/G` 边界与 Z 重建（含 `x²+y²>1` 的 clamp）
- `_n` / `_s` 缺失、只有其一、两者都有
- IOR 编码往返误差（在 [1,8] 内）
- atlas 空隙/未覆盖 sprite 的默认值

### 8.2 Python / Blender 测试

- mock：mapping flags、文件路径、builder 参数、无 `LabPBR Decoder` 节点。
- Blender 5.2：节点/链接、色彩空间、Bump/Displacement 参数、动画 chunk。
- 视觉回归：同一测试 pack，旧 decoder 材质 vs 新 baked 材质，固定相机/灯光渲染对比；
  重点看预设金属、F0 高的宝石、SSS、emission 边界。

### 8.3 已知可接受的差异

- 预设金属仍用 `metallic=1 + albedo`，与旧解码器一致；N/K 表未使用。
- 8-bit IOR 编码在高 F0（>0.605）会 clamp。
- emission 254/255 的归一化从旧实现的 `/255` 改为规范的 `/254`，最大 0.4% 亮度差。
- 玻璃/水 / 非 PBR 发光 / thin wall 在 v1 是已知效果回归，按 §6.1 记录。
